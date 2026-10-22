"""Provider pacing, daily reference freshness and independent job I/O contracts."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

from utils import yf_jobs
from utils.reference_data import daily_reference


@pytest.fixture
def reference_clock(monkeypatch):
    from api import cache

    clock = [0.0]
    monkeypatch.setattr(cache, "daily_cache", cache.ApiCache(maxsize=128, ttl=86400, timer=lambda: clock[0]))
    monkeypatch.setattr(cache, "_DISK_CACHE_ENABLED", False)
    monkeypatch.setattr(cache, "_gcs_get", lambda *_args: None)
    monkeypatch.setattr(cache, "_gcs_set", lambda *_args: None)
    return clock


def test_daily_reference_is_single_flight_and_expires_without_caching_failures(reference_clock):
    started = threading.Event()
    release = threading.Event()

    def load():
        started.set()
        assert release.wait(2)
        return {"currency": "GBp"}

    loader = Mock(side_effect=load)
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(daily_reference, "currency", "aapl", loader)
        assert started.wait(2)
        rest = [pool.submit(daily_reference, "currency", "AAPL", loader) for _ in range(3)]
        release.set()
        assert [f.result() for f in [first, *rest]] == [{"currency": "GBp"}] * 4
    assert loader.call_count == 1
    reference_clock[0] = 86401
    assert daily_reference("currency", "AAPL", loader) == {"currency": "GBp"}
    assert loader.call_count == 2
    empty = Mock(side_effect=[{}, {"sector": "Technology"}])
    assert daily_reference("momentum", "OTHER", empty) == {}
    assert daily_reference("momentum", "OTHER", empty) == {"sector": "Technology"}
    assert empty.call_count == 2


def test_currency_and_momentum_reference_values_are_reused(reference_clock, monkeypatch):
    from portfolio.momentum.price_momentum import momentum
    from portfolio.portfolio_optimizer import portfolio_analyzer as analyzer
    from utils import retry

    currency = Mock(return_value=SimpleNamespace(currency="GBp"))
    info = Mock(return_value={"marketCap": 1_000_000, "sector": "Technology", "quoteType": "ETF"})

    class Ticker:
        fast_info = property(lambda _self: currency())
        info = property(lambda _self: info())

    monkeypatch.setattr(retry.yf, "Ticker", lambda _symbol: Ticker())
    for _ in range(2):
        assert analyzer.fetch_currencies(["AAPL"]) == {"AAPL": "GBp"}
        assert momentum.fetch_ticker_metadata("AAPL") == (1_000_000, "Technology", True)
    assert currency.call_count == info.call_count == 1
    assert analyzer.fetch_currencies([]) == {}


def test_currency_error_defaults_are_not_memoized(reference_clock, monkeypatch):
    from portfolio.portfolio_optimizer import portfolio_analyzer as analyzer

    class Ticker:
        @property
        def fast_info(self):
            raise TimeoutError

    monkeypatch.setattr(analyzer.yf, "Ticker", lambda _symbol: Ticker())
    info = Mock(side_effect=[{}, {"currency": "EUR"}])
    monkeypatch.setattr(analyzer, "yf_ticker_info", info)
    assert analyzer.fetch_currencies(["AAPL"]) == {"AAPL": "USD"}
    assert analyzer.fetch_currencies(["AAPL"]) == {"AAPL": "EUR"}
    assert info.call_count == 2


def test_chunks_overlap_and_preserve_ohlcv_and_daily_dates(monkeypatch):
    rendezvous = threading.Barrier(3)
    queries = []
    index = pd.date_range("2026-01-01", periods=2, tz="America/New_York")
    expected = pd.DataFrame({"Close": [10.0, 11.0], "Volume": [5, 6]}, index=index)

    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            queries.append((self.symbol, kwargs))
            rendezvous.wait(2)
            return expected

    monkeypatch.setattr(yf_jobs.yf, "Ticker", Ticker)
    monkeypatch.setattr(yf_jobs, "_cooldown_until", 0.0)
    output, failed = yf_jobs.download_price_chunks(
        ["aaa", "BBB", "CCC", "AAA"], chunk_size=1, workers_per_chunk=1, period="1y", auto_adjust=False
    )
    assert failed == []
    assert set(output["Close"].columns) == {"AAA", "BBB", "CCC"}
    assert output.columns.names == ["Price", "Ticker"]
    for symbol in ("AAA", "BBB", "CCC"):
        pd.testing.assert_frame_equal(
            output.xs(symbol, level="Ticker", axis=1), expected.tz_localize(None).rename_axis(columns="Price")
        )
    assert len(queries) == 3
    assert all(kwargs == {"actions": False, "period": "1y", "auto_adjust": False} for _, kwargs in queries)


@pytest.mark.parametrize("auto_adjust", [False, True])
@pytest.mark.parametrize("symbols", [["AAA"], ["AAA", "BBB"]])
def test_chunk_output_matches_pinned_yfinance_download(monkeypatch, auto_adjust, symbols):
    from yfinance import multi

    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            zone = "America/New_York" if self.symbol == "AAA" else "Europe/London"
            index = pd.date_range("2026-01-01", periods=2, tz=zone, name="Date")
            fields = {"Close": [1.0, 2.0], "High": [2.0, 3.0], "Low": [0.5, 1.0], "Volume": [10, 20]}
            if not kwargs["auto_adjust"]:
                fields["Adj Close"] = [0.9, 1.8]
            return pd.DataFrame(fields, index=index)

    monkeypatch.setattr(yf_jobs.yf, "Ticker", Ticker)
    monkeypatch.setattr(multi, "Ticker", Ticker)
    monkeypatch.setattr(yf_jobs, "_cooldown_until", 0.0)
    expected = yf_jobs.yf.download(symbols, period="1y", auto_adjust=auto_adjust, threads=False, progress=False)
    output, failed = yf_jobs.download_price_chunks(
        symbols, chunk_size=1, period="1y", auto_adjust=auto_adjust, actions=False
    )
    assert failed == []
    pd.testing.assert_frame_equal(output, expected)


def test_history_throttling_is_shared_and_only_429_retries(monkeypatch):
    clock = [1.0]
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        clock[0] += delay

    monkeypatch.setattr(yf_jobs, "_cooldown_until", 0.0)
    monkeypatch.setattr(yf_jobs, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    frame = pd.DataFrame({"Close": [1.0]}, index=pd.date_range("2026-01-01", periods=1))
    history = Mock(side_effect=[YFRateLimitError(), frame, ValueError("invalid symbol"), pd.DataFrame()])
    monkeypatch.setattr(yf_jobs.yf, "Ticker", lambda _ticker: SimpleNamespace(history=history))
    pd.testing.assert_frame_equal(yf_jobs._history("AAA", {}), frame)
    assert sleeps == [0.25]
    assert yf_jobs._history("BAD", {}).empty
    assert yf_jobs._history("EMPTY", {}).empty
    assert history.call_count == 4
    assert sleeps == [0.25]


def test_partial_price_failure_keeps_other_symbols(monkeypatch):
    frame = pd.DataFrame({"Close": [1.0]}, index=pd.date_range("2026-01-01", periods=1))

    def ticker(symbol):
        history = Mock(side_effect=ValueError("missing")) if symbol == "BAD" else Mock(return_value=frame)
        return SimpleNamespace(history=history)

    monkeypatch.setattr(yf_jobs.yf, "Ticker", ticker)
    monkeypatch.setattr(yf_jobs, "_cooldown_until", 0.0)
    output, failed = yf_jobs.download_price_chunks(["AAA", "BAD", "CCC"], chunk_size=1)
    assert failed == ["BAD"]
    assert list(output["Close"].columns) == ["AAA", "CCC"]
    assert yf_jobs.download_price_chunks([])[0].empty


def test_exhausted_throttling_still_cools_down_other_tickers(monkeypatch):
    clock = [1.0]
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        clock[0] += delay

    monkeypatch.setattr(yf_jobs, "_cooldown_until", 0.0)
    monkeypatch.setattr(yf_jobs, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    frame = pd.DataFrame({"Close": [1.0]}, index=pd.date_range("2026-01-01", periods=1))
    history = Mock(side_effect=[*[YFRateLimitError() for _ in range(4)], frame])
    monkeypatch.setattr(yf_jobs.yf, "Ticker", lambda _ticker: SimpleNamespace(history=history))
    assert yf_jobs._history("THROTTLED", {}).empty
    assert sleeps == [0.25, 0.5, 1.0]
    pd.testing.assert_frame_equal(yf_jobs._history("OTHER", {}), frame)
    assert sleeps == [0.25, 0.5, 1.0, 2.0]
    assert history.call_count == 5


def test_price_history_honors_retry_after(monkeypatch):
    import requests

    clock = [1.0]
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        clock[0] += delay

    monkeypatch.setattr(yf_jobs, "_cooldown_until", 0.0)
    monkeypatch.setattr(yf_jobs, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    response = requests.Response()
    response.status_code = 429
    response.headers["Retry-After"] = "2"
    frame = pd.DataFrame({"Close": [1.0]}, index=pd.date_range("2026-01-01", periods=1))
    history = Mock(side_effect=[requests.HTTPError(response=response), frame])
    monkeypatch.setattr(yf_jobs.yf, "Ticker", lambda _ticker: SimpleNamespace(history=history))
    pd.testing.assert_frame_equal(yf_jobs._history("AAA", {}), frame)
    assert sleeps == [2.0]


def test_chunk_failures_cannot_interleave_with_yfinance_download_buffers(monkeypatch):
    from yfinance import multi

    download_started = threading.Event()
    release_download = threading.Event()
    history_started = threading.Event()
    frame = pd.DataFrame({"Close": [1.0]}, index=pd.date_range("2026-01-01", periods=1))

    def download(*args, **kwargs):
        download_started.set()
        assert release_download.wait(2)
        return frame

    def history(**kwargs):
        history_started.set()
        return frame

    monkeypatch.setattr(multi, "_download_impl", download)
    monkeypatch.setattr(yf_jobs.yf, "Ticker", lambda _symbol: SimpleNamespace(history=history))
    with ThreadPoolExecutor(max_workers=2) as pool:
        existing = pool.submit(yf_jobs.yf.download, "EXISTING")
        assert download_started.wait(2)
        incoming = pool.submit(yf_jobs.download_price_chunks, ["AAA"])
        try:
            assert not history_started.wait(0.05)
        finally:
            release_download.set()
        pd.testing.assert_frame_equal(existing.result(), frame)
        assert list(incoming.result()[0]["Close"].columns) == ["AAA"]
    assert history_started.is_set()


def test_source_reads_overlap_and_keep_source_order_and_hashes(monkeypatch):
    from portfolio.portfolio_optimizer import portfolio_analyzer as analyzer

    rendezvous = threading.Barrier(4)
    positions = pd.DataFrame({"ticker": ["BBB", "AAA"]})
    monkeypatch.setattr(analyzer, "_positions_df_for_universe", lambda _mode: positions)

    def read(ticker):
        rendezvous.wait(2)
        return f"{ticker} content"

    monkeypatch.setattr(analyzer, "_read_overview_markdown", read)
    monkeypatch.setattr(analyzer, "_read_management_quality_markdown", read)
    token = analyzer.analyzer_source_cache_token()
    expected = [
        {
            "ticker": t,
            "overview_hash": analyzer._sha256_text(f"{t} content"),
            "management_quality_hash": analyzer._sha256_text(f"{t} content"),
        }
        for t in ("AAA", "BBB")
    ]
    assert token["qualitative_sources"] == expected


def test_source_documents_need_no_exists_round_trips(monkeypatch):
    from api import state_storage
    from portfolio import management_quality_content
    from portfolio.portfolio_optimizer import portfolio_analyzer as analyzer

    read = Mock(return_value="overview")
    management = Mock(return_value="management")
    exists = Mock(side_effect=AssertionError("a separate existence probe is unnecessary"))
    monkeypatch.setattr(state_storage, "read_text", read)
    monkeypatch.setattr(state_storage, "exists_text", exists)
    monkeypatch.setattr(management_quality_content, "management_quality_exists", exists)
    monkeypatch.setattr(management_quality_content, "read_management_quality", management)
    assert analyzer._read_overview_markdown("aapl") == "overview"
    assert analyzer._read_management_quality_markdown("aapl") == "management"
    assert read.call_count == management.call_count == 1
    exists.assert_not_called()


def test_missing_management_document_still_renders_ontology_assessment(monkeypatch):
    from api.routers import management_quality as router
    from ontology.runtime_read_service import OntologyRuntimeReadService
    from portfolio import management_quality_content
    from portfolio.portfolio_optimizer import portfolio_analyzer as analyzer

    monkeypatch.setattr(management_quality_content, "read_management_quality", Mock(side_effect=FileNotFoundError))
    monkeypatch.setattr(
        OntologyRuntimeReadService, "management_quality_assessment", lambda _self, ticker: {"ticker": ticker}
    )
    render = Mock(return_value="rendered management")
    monkeypatch.setattr(router, "_render_management_quality_markdown", render)
    assert analyzer._read_management_quality_markdown("aapl") == "rendered management"
    render.assert_called_once_with("AAPL", {"ticker": "AAPL"})


def test_analyzer_prices_start_before_currencies_and_preserve_fx(monkeypatch):
    from portfolio.portfolio_optimizer import portfolio_analyzer as analyzer

    rendezvous = threading.Barrier(2)
    index = pd.date_range("2026-01-01", periods=2)
    queries = []

    def currencies(tickers):
        rendezvous.wait(2)
        return dict.fromkeys(tickers, "EUR")

    def prices(tickers, fx_tickers):
        queries.append((tickers, fx_tickers))
        if tickers:
            rendezvous.wait(2)
        return pd.DataFrame({t: [1.0, 2.0] for t in [*tickers, *fx_tickers]}, index=index)

    monkeypatch.setattr(analyzer, "fetch_currencies", currencies)
    monkeypatch.setattr(analyzer, "download_prices", prices)
    output, currencies = analyzer._fetch_prices_and_currencies(["AAA"])
    assert list(output.columns) == ["AAA", "EURUSD=X"]
    assert currencies == {"AAA": "EUR"}
    assert queries == [(["AAA"], []), ([], ["EURUSD=X"])]


def test_overlapping_currency_failure_does_not_pollute_asset_prices(reference_clock, monkeypatch):
    from yfinance import shared

    from portfolio.portfolio_optimizer import portfolio_analyzer as analyzer

    rendezvous = threading.Barrier(2)
    frame = pd.DataFrame({"Close": [100.0, 102.0]}, index=pd.date_range("2026-01-01", periods=2))
    monkeypatch.setattr(shared, "_DFS", {})

    class Ticker:
        @property
        def fast_info(self):
            rendezvous.wait(2)
            # Pinned yfinance's history error path writes these globals, even
            # when a fast_info lookup triggered the history request.
            shared._DFS["UNRELATED"] = pd.DataFrame()
            raise KeyError("currency")

        def history(self, **kwargs):
            rendezvous.wait(2)
            return frame

    monkeypatch.setattr(yf_jobs.yf, "Ticker", lambda _symbol: Ticker())
    monkeypatch.setattr(analyzer, "yf_ticker_info", lambda _ticker: {})
    monkeypatch.setattr(yf_jobs, "_cooldown_until", 0.0)
    output, currencies = analyzer._fetch_prices_and_currencies(["AAA"])
    assert output["AAA"].tolist() == [100.0, 102.0]
    assert list(output.columns) == ["AAA"]
    assert currencies == {"AAA": "USD"}


def test_momentum_prices_overlap_metadata_and_choose_same_benchmarks(monkeypatch):
    from portfolio.momentum.price_momentum import momentum

    rendezvous = threading.Barrier(2)
    monkeypatch.setattr(momentum, "load_universe", lambda _universe: ["AAA", "BBB"])

    def metadata(tickers):
        rendezvous.wait(2)
        return {"AAA": (1_000_000, None, False), "BBB": (50_000_000_000, "Technology", False)}

    def prices(tickers, years):
        rendezvous.wait(2)
        assert set(tickers) == {"AAA", "BBB", "SPY", "IWM", "QQQ"}
        return dict.fromkeys(tickers, pd.Series([1.0, 2.0])), {}

    monkeypatch.setattr(momentum, "fetch_metadata_batch", metadata)
    monkeypatch.setattr(momentum, "fetch_prices_batch", prices)
    monkeypatch.setattr(
        momentum, "analyze_ticker", lambda *args, **kwargs: {"ticker": args[0], "date": pd.Timestamp("2026-01-01")}
    )
    output = momentum.get_data("test")
    assert {row["ticker"]: row["benchmark"] for row in output["results"]} == {"AAA": "IWM", "BBB": "QQQ"}


def test_sec_requests_share_a_rolling_budget_across_hosts(monkeypatch):
    import requests

    from utils import rate_limit, retry

    clock = [100.0]
    starts = []

    def sleep(delay):
        clock[0] += delay

    monkeypatch.setattr(rate_limit, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    monkeypatch.setattr(rate_limit, "_buckets", {})

    def request(method, url, **kwargs):
        starts.append(clock[0])
        response = requests.Response()
        response.status_code = 200
        return response

    monkeypatch.setattr(retry._requests, "request", request)
    for index in range(18):
        host = "data.sec.gov" if index % 2 else "www.sec.gov"
        assert retry.requests_get(f"https://{host}/test").status_code == 200
    assert 1.7 < starts[-1] - starts[0] < 2.0
    for start in starts:
        assert sum(start <= value < start + 1.0 - 1e-8 for value in starts) <= 10
    before = clock[0]
    retry.requests_get("https://example.test/ordinary")
    assert clock[0] == before


def test_each_sec_retry_takes_a_token_without_pacing_other_hosts(monkeypatch):
    import requests

    from utils import retry

    bucket = SimpleNamespace(acquire=Mock())
    providers = Mock(return_value=bucket)
    monkeypatch.setattr(retry, "provider_limiter", providers)
    throttled = requests.Response()
    throttled.status_code = 429
    ok = requests.Response()
    ok.status_code = 200
    request = Mock(side_effect=[throttled, ok, ok, ok])
    monkeypatch.setattr(retry._requests, "request", request)
    monkeypatch.setattr(retry, "time", SimpleNamespace(sleep=Mock()))
    assert retry.requests_get("https://data.sec.gov/test", max_retries=1, backoff_base=0).status_code == 200
    assert retry.requests_get("https://www.sec.gov/test").status_code == 200
    assert bucket.acquire.call_count == 3
    assert retry.requests_get("https://data.sec.gov.example.test/ordinary").status_code == 200
    assert bucket.acquire.call_count == 3
    assert all(call.args == ("sec",) for call in providers.call_args_list)


def test_edgar_network_calls_overlap_across_both_fetchers(monkeypatch):
    import requests

    from equities.short_screen import short_screen
    from portfolio.momentum.fundamental_momentum import edgar_fetcher
    from utils import retry

    rendezvous = threading.Barrier(3)
    bucket = SimpleNamespace(acquire=Mock())
    monkeypatch.setattr(retry, "provider_limiter", lambda _provider: bucket)
    monkeypatch.setattr(short_screen, "_edgar_facts_cache", {})

    def request(method, url, **kwargs):
        rendezvous.wait(2)
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}"
        return response

    monkeypatch.setattr(retry._requests, "request", request)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(edgar_fetcher._rate_limited_get, "https://data.sec.gov/one")
        second = pool.submit(edgar_fetcher._rate_limited_get, "https://data.sec.gov/two")
        short = pool.submit(short_screen._fetch_edgar_facts, "123")
        assert first.result().status_code == second.result().status_code == 200
        assert short.result() == {}
    assert bucket.acquire.call_count == 3
