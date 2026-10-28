from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from api.idea_scan import data as d


@pytest.fixture(autouse=True)
def sleeps(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "_LOCAL_ROOT", tmp_path / "datasets")
    monkeypatch.setattr(d, "CHECKPOINT_CHUNK", 3)
    calls: list[float] = []
    monkeypatch.setattr(d, "_sleep", calls.append)
    return calls


def _fake_prices(calls):
    def fetch(tickers):
        calls.append(list(tickers))
        idx = pd.bdate_range(end="2026-10-23", periods=10)
        return pd.DataFrame({t: range(10) for t in [*tickers, "SPY"]}, index=idx, dtype=float), []

    return fetch


def _fake_fundamentals(calls, fail=()):
    def fetch(ticker):
        calls.append(ticker)
        if ticker in fail:
            return d.TickerFundamentals(error="no data returned")
        frame = pd.DataFrame({pd.Timestamp("2025-12-31"): {"Total Revenue": 100.0}})
        return d.TickerFundamentals(info={"sector": "Technology", "marketCap": 1.0}, financials=frame)

    return fetch


def test_prices_and_fundamentals_fetched_once_and_resumed(monkeypatch):
    price_calls, fundamental_calls = [], []
    monkeypatch.setattr(d, "fetch_prices", _fake_prices(price_calls))
    monkeypatch.setattr(d, "fetch_ticker_fundamentals", _fake_fundamentals(fundamental_calls, fail={"EEE"}))
    membership = {t: ["sp500"] for t in ["AAA", "BBB", "CCC", "DDD", "EEE"]}
    now = datetime(2026, 10, 28, tzinfo=UTC)

    first = d.fetch_dataset(membership, workers=2, now=now)
    assert len(price_calls) == 1
    assert sorted(fundamental_calls) == sorted(membership)
    assert first.failed == {"EEE": "no data returned"}
    assert first.reused_chunks == 0
    assert first.fundamentals["AAA"].financials.loc["Total Revenue"].iloc[0] == 100.0

    second = d.fetch_dataset(membership, workers=2, now=now)
    assert len(price_calls) == 1, "prices come from the week's checkpoint"
    assert len(fundamental_calls) == len(membership), "fundamentals come from the week's checkpoint"
    assert second.reused_chunks == 2
    assert isinstance(second.fundamentals["AAA"].financials.columns[0], pd.Timestamp)
    assert list(second.prices.columns) == list(first.prices.columns)


def test_new_week_starts_a_new_dataset(monkeypatch):
    price_calls, fundamental_calls = [], []
    monkeypatch.setattr(d, "fetch_prices", _fake_prices(price_calls))
    monkeypatch.setattr(d, "fetch_ticker_fundamentals", _fake_fundamentals(fundamental_calls))
    membership = {"AAA": ["sp500"]}
    a = d.dataset_key(membership, now=datetime(2026, 10, 28, tzinfo=UTC))
    b = d.dataset_key(membership, now=datetime(2026, 11, 4, tzinfo=UTC))
    assert a != b
    assert d.dataset_key({"AAA": [], "BBB": []}, now=datetime(2026, 10, 28, tzinfo=UTC)) != a


def test_membership_dedupes_across_universes(monkeypatch):
    universes = {"sp500": ["AAA", "BBB"], "sp400": ["CCC"], "russell2000": ["BBB", "DDD"]}
    monkeypatch.setattr("equities.common.get_universe_tickers", lambda key: universes[key])
    membership = d.resolve_membership(["sp500", "sp400", "russell2000"])
    assert membership == {"AAA": ["sp500"], "BBB": ["sp500", "russell2000"], "CCC": ["sp400"], "DDD": ["russell2000"]}
    narrowed = d.resolve_membership(["sp500"], tickers=["bbb", "ZZZ"])
    assert narrowed == {"BBB": ["sp500"], "ZZZ": []}


def test_primary_benchmark_prefers_largest_index():
    dataset = d.ScanDataset(
        key="k",
        membership={"A": ["russell2000", "sp600"], "B": ["russell2000"], "C": []},
        prices=pd.DataFrame(),
        fundamentals={},
        failed={},
        fetched_at="",
    )
    assert dataset.primary_benchmark("A") == "IJR"
    assert dataset.primary_benchmark("B") == "IWM"
    assert dataset.primary_benchmark("C") == "SPY"


def test_eps_revision_from_trend():
    trend = pd.DataFrame(
        {"current": [1.0, 1.2, 4.0, 5.0], "30daysAgo": [1.0, 1.2, 4.4, 5.0]}, index=["0q", "+1q", "0y", "+1y"]
    )
    assert d.eps_revision_from_trend(trend) == pytest.approx((-0.4 / 4.4) / 2)
    assert d.eps_revision_from_trend(None) is None
    assert d.eps_revision_from_trend(pd.DataFrame()) is None


def test_prices_go_in_batches_of_fifty_a_second(monkeypatch, sleeps):
    batches = []

    def fake_chunks(symbols, **kwargs):
        batches.append((list(symbols), kwargs["chunk_size"], kwargs["max_chunks"]))
        idx = pd.bdate_range(end="2026-10-23", periods=5)
        good = [s for s in symbols if s != "FLAKY" or len(batches) > 3]
        frame = pd.concat(
            {s: pd.DataFrame({"Close": range(5)}, index=idx, dtype=float) for s in good},
            axis=1,
            names=["Ticker", "Price"],
        )
        return frame.swaplevel(0, 1, axis=1), [s for s in symbols if s not in good]

    monkeypatch.setattr("utils.yf_jobs.download_price_chunks", fake_chunks)
    tickers = [f"T{i:03d}" for i in range(105)] + ["FLAKY"]
    prices, failed = d.fetch_prices(tickers)
    first_pass = [b for b in batches[:3]]
    assert [len(b[0]) for b in first_pass] == [50, 50, 10]
    assert all(size == 50 and chunks == 1 for _, size, chunks in first_pass)
    assert len([s for s in sleeps if s <= d.PRICE_BATCH_INTERVAL_S]) == 2, "pause between first-pass batches"
    assert d.RATE_LIMIT_BACKOFF_S in sleeps, "failed symbols retried after a backoff"
    assert failed == []
    assert "FLAKY" in prices.columns and "SPY" in prices.columns
    assert prices.columns.is_unique


def _limited_then_ok(calls, *, limited_rounds=1, limited=("BBB",)):
    seen: dict[str, int] = {}

    def fetch(ticker):
        calls.append(ticker)
        seen[ticker] = seen.get(ticker, 0) + 1
        if ticker in limited and seen[ticker] <= limited_rounds:
            return d.TickerFundamentals(error=f"{ticker}.info: Too Many Requests. Rate limited.")
        return d.TickerFundamentals(info={"sector": "Technology"})

    return fetch


def test_rate_limited_tickers_are_retried(monkeypatch, sleeps):
    calls = []
    monkeypatch.setattr(d, "fetch_prices", _fake_prices([]))
    monkeypatch.setattr(d, "fetch_ticker_fundamentals", _limited_then_ok(calls))
    dataset = d.fetch_dataset(
        {t: ["sp500"] for t in ["AAA", "BBB", "CCC"]}, workers=1, now=datetime(2026, 10, 28, tzinfo=UTC)
    )
    assert calls.count("BBB") == 2
    assert d.RATE_LIMIT_BACKOFF_S in sleeps
    assert dataset.failed == {}


def test_resume_refetches_names_that_stayed_rate_limited(monkeypatch):
    calls = []
    monkeypatch.setattr(d, "RATE_LIMIT_RETRIES", 0)
    monkeypatch.setattr(d, "fetch_prices", _fake_prices([]))
    monkeypatch.setattr(d, "fetch_ticker_fundamentals", _limited_then_ok(calls))
    membership = {t: ["sp500"] for t in ["AAA", "BBB", "CCC"]}
    now = datetime(2026, 10, 28, tzinfo=UTC)
    first = d.fetch_dataset(membership, workers=1, now=now)
    assert "BBB" in first.failed
    second = d.fetch_dataset(membership, workers=1, now=now)
    assert second.failed == {}
    assert sorted(calls) == ["AAA", "BBB", "BBB", "CCC"]


def test_deadline_stops_new_fetches(monkeypatch):
    calls = []
    monkeypatch.setattr(d, "fetch_prices", _fake_prices([]))
    monkeypatch.setattr(d, "fetch_ticker_fundamentals", _limited_then_ok(calls, limited=()))
    membership = {t: ["sp500"] for t in ["AAA", "BBB", "CCC", "DDD", "EEE"]}
    now = datetime(2026, 10, 28, tzinfo=UTC)
    stopped = d.fetch_dataset(membership, workers=1, now=now, deadline_s=0)
    assert calls == []
    assert set(stopped.failed.values()) == {d.NOT_FETCHED}
    resumed = d.fetch_dataset(membership, workers=1, now=now)
    assert sorted(calls) == sorted(membership)
    assert resumed.failed == {}


def test_expired_crumb_is_retried(monkeypatch, sleeps):
    calls = []
    seen = {"n": 0}

    def fetch(ticker):
        calls.append(ticker)
        if ticker == "BBB" and seen["n"] == 0:
            seen["n"] += 1
            return d.TickerFundamentals(error='info: HTTP Error 401: {"description":"Invalid Crumb"}')
        return d.TickerFundamentals(info={"sector": "Technology"})

    monkeypatch.setattr(d, "fetch_prices", _fake_prices([]))
    monkeypatch.setattr(d, "fetch_ticker_fundamentals", fetch)
    dataset = d.fetch_dataset({t: ["sp500"] for t in ["AAA", "BBB"]}, workers=1, now=datetime(2026, 10, 28, tzinfo=UTC))
    assert calls.count("BBB") == 2 and dataset.failed == {}
