from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


def _price_run(screen, tickers):
    return screen.get_data(
        tickers,
        pb_threshold=None,
        profit_type=None,
        check_min_drawdown=True,
        min_drawdown_pct=5,
        check_3m_pos_momentum=True,
        check_2m_pos_rel_momentum=True,
        benchmark_ticker="SPY",
    )


def test_screenshot_price_only_screen_uses_bounded_histories_and_retains_partial_failures(monkeypatch):
    from equities.long_screen import long_screen as screen
    from utils import yf_jobs

    calls = []
    progress = []
    prices = np.concatenate([np.linspace(80, 100, 160), np.linspace(100, 150, 29), np.linspace(90, 130, 63)])

    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            calls.append((self.symbol, kwargs))
            if self.symbol == "BAD":
                raise TimeoutError("provider timeout")
            return pd.DataFrame(
                {"Close": 100 if self.symbol == "SPY" else prices}, index=pd.date_range("2025-11-01", periods=252)
            )

    monkeypatch.setattr(yf_jobs.yf, "Ticker", Ticker)
    monkeypatch.setattr(yf_jobs.yf, "download", lambda *a, **kw: pytest.fail("legacy download path"))
    monkeypatch.setattr(
        screen, "_screen_long_fundamentals", lambda *a, **kw: pytest.fail("price-only run fetched fundamentals")
    )
    monkeypatch.setattr(
        screen, "_report_progress", lambda callback, phase, done, total: progress.append((phase, done, total))
    )

    result = _price_run(screen, ["AAA", "BAD", "AAA"])

    assert result["results_df"]["Ticker"].tolist() == ["AAA"]
    assert result["final_count"] == 1
    assert result["phase1_count"] == 2
    assert result["failed_tickers"] == ["BAD: price history unavailable"]
    assert sorted(t for t, _ in calls) == ["AAA", "BAD", "SPY"]
    assert all(k["timeout"] == 15 and k["raise_errors"] for _, k in calls)
    assert ("prices", 3, 3) in progress


@pytest.mark.parametrize("failure", ["all", "benchmark"])
def test_unavailable_prices_never_bypass_enabled_filters(monkeypatch, failure):
    from equities.long_screen import long_screen as screen
    from utils import yf_jobs

    def download(*args, **kwargs):
        if failure == "all":
            return pd.DataFrame(), ["AAA", "SPY"]
        return pd.concat({"Close": pd.DataFrame({"AAA": np.arange(252) + 100})}, axis=1), ["SPY"]

    monkeypatch.setattr(yf_jobs, "download_price_chunks", download)
    with pytest.raises(RuntimeError, match="unavailable|benchmark SPY"):
        _price_run(screen, ["AAA"])


def test_price_budget_retains_completed_symbols_and_stops_new_requests(monkeypatch):
    from utils import yf_jobs

    clock = [0.0]
    calls = []
    frame = pd.DataFrame({"Close": [10.0]}, index=pd.date_range("2026-11-01", periods=1))

    def ticker(symbol):
        def history(**kwargs):
            calls.append(symbol)
            clock[0] += 1
            return frame

        return SimpleNamespace(history=history)

    monkeypatch.setattr(yf_jobs, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda seconds: None))
    monkeypatch.setattr(yf_jobs, "_cooldown_until", 0)
    monkeypatch.setattr(yf_jobs.yf, "Ticker", ticker)
    data, failed = yf_jobs.download_price_chunks(
        ["AAA", "BBB", "CCC", "DDD"],
        max_chunks=1,
        workers_per_chunk=1,
        time_budget_s=2,
    )
    assert calls == ["AAA", "BBB"]
    assert list(data["Close"].columns) == ["AAA", "BBB"]
    assert failed == ["CCC", "DDD"]


def test_price_budget_also_bounds_waiting_for_another_download():
    from utils import yf_jobs

    with yf_jobs.shared._LOCK, pytest.raises(TimeoutError, match="busy with another download"):
        yf_jobs.download_price_chunks(["AAA"], time_budget_s=0.01)


def test_long_fundamentals_do_not_sleep_between_batches(monkeypatch):
    from equities.long_screen import long_screen as screen

    monkeypatch.setattr(screen, "screen_ticker_long", lambda ticker, *a, **kw: (True, {"ticker": ticker}))
    monkeypatch.setattr("time.sleep", lambda *a: pytest.fail("fixed batch pause"))
    tickers = [f"T{i}" for i in range(205)]
    rows, failures = screen._screen_long_fundamentals(
        tickers,
        pb_threshold=None,
        profit_type=None,
        check_revenue=False,
        min_revenue_growth=5,
        check_eps=False,
        min_eps_growth=5,
        check_ebit_multiple=False,
        max_ebit_multiple=20,
    )
    assert len(rows) == len(tickers)
    assert failures == []


@pytest.fixture
def weekly_frame(monkeypatch):
    from api.idea_scan import store
    from tests.test_idea_scan_screening import liquidity_rows, make_frame

    frame = make_frame(liquidity_rows())
    monkeypatch.setattr(store, "latest_completed_run", lambda **kwargs: {"run_id": "weekly-1", "week": "2026-W45"})
    monkeypatch.setattr(store, "load_frame", lambda run_id: frame)
    return frame


def test_long_liquidity_filter_matches_digest_and_uses_full_peer_set(weekly_frame):
    from api.idea_scan.presets import LiquidityCoverageFilter
    from api.idea_scan.screening import evaluate_preset
    from api.routers.long_screen import _liquid_covered_tickers
    from tests.test_idea_scan_screening import preset

    selected, failed, source = _liquid_covered_tickers(list(weekly_frame.index), LiquidityCoverageFilter())
    digest = evaluate_preset(preset("long-liquid-covered"), weekly_frame)
    assert set(selected) == {hit["ticker"] for hit in digest.hits}
    assert failed == []
    assert source["week"] == "2026-W45"
    # S6 would rank 100th percentile if the comparison were incorrectly restricted to this custom input.
    assert _liquid_covered_tickers(["S6"], LiquidityCoverageFilter())[0] == []


def test_liquidity_filter_precedes_live_price_calls_and_preserves_provenance(weekly_frame, monkeypatch):
    from api.routers import long_screen as router
    from equities.long_screen import long_screen as screen

    calls = []

    def get_data(**kwargs):
        calls.append(kwargs)
        return {"results_df": [], "failed_tickers": [], "phase1_count": 1, "final_count": 0}

    monkeypatch.setattr(screen, "get_data", get_data)
    req = router.LongScreenRequest(input_mode="Custom Tickers", tickers="S6,S9,MISSING", liquidity_coverage={})
    result = router._compute_long_screen(req)
    assert calls[0]["tickers"] == ["S9"]
    assert result["phase1_count"] == 3
    assert result["liquidity_coverage_pass_count"] == 1
    assert result["liquidity_coverage_source"]["run_id"] == "weekly-1"
    assert result["failed_tickers"] == ["MISSING: missing weekly liquidity/coverage data"]
    calls.clear()
    result = router._compute_long_screen(req.model_copy(update={"tickers": "S6"}))
    assert result["final_count"] == 0
    assert calls == []


def test_liquidity_filter_never_silently_skips_missing_weekly_data(monkeypatch):
    from api.idea_scan import store
    from api.routers.long_screen import LongScreenRequest, _compute_long_screen

    monkeypatch.setattr(store, "latest_completed_run", lambda **kwargs: None)
    with pytest.raises(ValueError, match="Run the idea scan first"):
        _compute_long_screen(LongScreenRequest(input_mode="Custom Tickers", tickers="AAA", liquidity_coverage={}))


def test_liquidity_source_and_threshold_change_long_screen_cache_key(weekly_frame, monkeypatch):
    from api.idea_scan import store
    from api.routers.long_screen import LongScreenRequest, _cache_key

    plain = LongScreenRequest()
    filtered = LongScreenRequest(liquidity_coverage={})
    first = _cache_key(filtered)
    assert _cache_key(plain) != first
    assert _cache_key(LongScreenRequest(liquidity_coverage={"min_dollar_volume_industry_pct": 0.95})) != first
    monkeypatch.setattr(store, "latest_completed_run", lambda **kw: {"run_id": "weekly-2"})
    assert _cache_key(filtered) != first
