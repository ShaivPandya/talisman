from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def isolated_chart_cache(monkeypatch):
    from api import cache
    from api.routers import chart

    clock = [0.0]
    monkeypatch.setattr(chart, "short_cache", cache.ApiCache(maxsize=128, ttl=300, timer=lambda: clock[0]))
    monkeypatch.setattr(cache, "_DISK_CACHE_ENABLED", False)
    monkeypatch.setattr(cache, "_gcs_cache_enabled", lambda: False)
    return clock


def _json(response):
    import json

    return json.loads(response.body)


def test_fetch_full_price_history_formats_close_prices(monkeypatch):
    import portfolio.technical_analysis.technical_analysis as technical_analysis

    def fake_yf_download(*args, **kwargs):
        assert args[0] == "MU"
        assert kwargs["period"] == "max"
        return pd.DataFrame(
            {"Close": [10.125, None, 11.5]},
            index=pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]),
        )

    monkeypatch.setattr(technical_analysis, "yf_download", fake_yf_download)

    df = technical_analysis.fetch_full_price_history("MU")

    assert list(df.columns) == ["Date", "Close"]
    assert df.to_dict("records") == [
        {"Date": "2020-01-02", "Close": 10.125},
        {"Date": "2020-01-06", "Close": 11.5},
    ]


@pytest.mark.parametrize("multi_index", [False, True])
@pytest.mark.parametrize("observations", [1, 21, 22, 260])
def test_chart_returns_prices_with_limited_history(auth_client, monkeypatch, multi_index, observations):
    import portfolio.technical_analysis.technical_analysis as technical

    dates = pd.bdate_range("2025-01-02", periods=observations, tz="America/New_York", name="Date")
    raw = pd.DataFrame({"Close": [100.0 + i for i in range(observations)]}, index=dates)
    if multi_index:
        raw.columns = pd.MultiIndex.from_tuples([("Close", "LPRO")], names=["Price", "Ticker"])
    monkeypatch.setattr(technical, "yf_download", lambda *args, **kwargs: raw)
    monkeypatch.setattr(technical, "yf_ticker_info", lambda ticker: {})

    response = auth_client.post("/api/chart", json={"ticker": "LPRO", "lookback": "1Y"})

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ticker"] == "LPRO"
    assert len(data["price_data"]) == observations
    assert data["price_data"][-1]["Date"] == dates[-1].tz_localize(None).isoformat()
    assert data["price_data"][-1]["Close"] == 100.0 + observations - 1
    assert len(data["roc_data"]) == observations
    roc_indicators = {row["Indicator"] for row in data["summary"] if row["Indicator"].endswith(" ROC")}
    expected_roc = {
        label for label, periods in [("1M ROC", 21), ("3M ROC", 63), ("12M ROC", 252)] if observations > periods
    }
    assert roc_indicators == expected_roc
    if observations <= 21:
        assert data["summary"] == []
        assert data["roc_data"][-1]["1M ROC"] is None
    else:
        expected_change = ((100.0 + observations - 1) / (100.0 + observations - 22) - 1) * 100
        assert data["roc_data"][-1]["1M ROC"] == pytest.approx(expected_change)
    if observations >= 200:
        assert data["price_data"][-1]["200D SMA"] == pytest.approx(100.0 + observations - 100.5)
        assert any(row["Indicator"] == "Price vs 200D SMA" for row in data["summary"])


def test_fetch_daily_drops_missing_prices_and_preserves_dates(monkeypatch):
    import portfolio.technical_analysis.technical_analysis as technical

    dates = pd.date_range("2025-01-02", periods=3, tz="America/New_York")
    raw = pd.DataFrame({"Close": [None, 12.5, None]}, index=dates)
    monkeypatch.setattr(technical, "yf_download", lambda *args, **kwargs: raw)

    close = technical._fetch_daily("LPRO")

    pd.testing.assert_series_equal(close, pd.Series([12.5], index=dates[1:2].tz_localize(None), name="Close"))


@pytest.mark.parametrize("values", [[], [None], [None, None]])
def test_fetch_daily_rejects_missing_price_history(monkeypatch, values):
    import portfolio.technical_analysis.technical_analysis as technical

    raw = pd.DataFrame({"Close": values}, index=pd.date_range("2025-01-02", periods=len(values)))
    monkeypatch.setattr(technical, "yf_download", lambda *args, **kwargs: raw)

    with pytest.raises(ValueError, match="No (data|close prices) returned for ticker 'LPRO'"):
        technical._fetch_daily("LPRO")


def test_download_price_history_csv(auth_client, monkeypatch):
    import portfolio.technical_analysis.technical_analysis as technical_analysis

    def fake_fetch_full_price_history(ticker: str):
        assert ticker == "BRK-B"
        return pd.DataFrame(
            [
                {"Date": "2020-01-02", "Close": 10.5},
                {"Date": "2020-01-03", "Close": 11.25},
            ]
        )

    monkeypatch.setattr(technical_analysis, "fetch_full_price_history", fake_fetch_full_price_history)

    resp = auth_client.get("/api/chart/price-history/brk-b")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'filename="BRK_B_price_history.csv"' in resp.headers["content-disposition"]
    assert resp.text == "Date,Close\n2020-01-02,10.5\n2020-01-03,11.25\n"


def test_chart_cache_normalizes_ticker_keys_lookback_and_expires(monkeypatch, isolated_chart_cache):
    from datetime import datetime

    import portfolio.technical_analysis.technical_analysis as technical
    from api.routers.chart import ChartRequest, run_chart

    calls = []

    def fetch(ticker, lookback):
        calls.append((ticker, lookback))
        return {"prices": pd.DataFrame({"Close": [float("nan"), 11.5]}), "timestamp": datetime(2026, 1, 2)}

    monkeypatch.setattr(technical, "get_data", fetch)
    first = _json(run_chart(ChartRequest(ticker=" mu ")))
    second = _json(run_chart(ChartRequest(ticker="MU")))
    assert first["prices"] == second["prices"] == [{"index": 0, "Close": None}, {"index": 1, "Close": 11.5}]
    assert first["timestamp"] == "2026-01-02T00:00:00"
    assert first["_meta"]["cache_ttl"] == 300
    assert second["_meta"]["fetched_at"] == first["_meta"]["fetched_at"]
    assert second["_meta"]["data_age_seconds"] == 0
    run_chart(ChartRequest(ticker="MU", lookback="1Y"))
    assert calls == [("MU", "2Y"), ("MU", "1Y")]
    isolated_chart_cache[0] = 301
    run_chart(ChartRequest(ticker="MU"))
    assert calls[-1] == ("MU", "2Y") and len(calls) == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol_a": "QQQ"},
        {"symbol_b": "IWM"},
        {"start_date": "2025-01-01"},
        {"end_date": "2026-01-01"},
        {"method": "other"},
    ],
)
def test_ratio_cache_isolates_all_parameters(monkeypatch, changes):
    import portfolio.technical_analysis.technical_analysis as technical
    from api.routers.chart import RatioChartRequest, run_chart_ratio

    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        return {"value": len(calls)}

    monkeypatch.setattr(technical, "get_ratio_data", fetch)
    args = {"symbol_a": "SPY", "symbol_b": "TLT"}
    assert _json(run_chart_ratio(RatioChartRequest(**args)))["value"] == 1
    assert _json(run_chart_ratio(RatioChartRequest(symbol_a=" spy ", symbol_b="tlt")))["value"] == 1
    assert _json(run_chart_ratio(RatioChartRequest(**(args | changes))))["value"] == 2
    assert len(calls) == 2


def test_chart_failure_is_not_cached(monkeypatch):
    import portfolio.technical_analysis.technical_analysis as technical
    from api.routers.chart import ChartRequest, run_chart

    calls = []

    def fetch(*args, **kwargs):
        calls.append(1)
        return {"error": "provider unavailable"} if len(calls) == 1 else {"value": 42}

    monkeypatch.setattr(technical, "get_data", fetch)
    from fastapi import HTTPException

    with pytest.raises(HTTPException, match="provider unavailable"):
        run_chart(ChartRequest(ticker="MU"))
    assert _json(run_chart(ChartRequest(ticker="MU")))["value"] == 42
    assert _json(run_chart(ChartRequest(ticker="MU")))["value"] == 42
    assert len(calls) == 2


def test_csv_cache_expires_and_retries_failures(monkeypatch, isolated_chart_cache):
    import portfolio.technical_analysis.technical_analysis as technical
    from api.exceptions import DataFetchError
    from api.routers.chart import download_price_history

    calls = []

    def fetch(ticker):
        calls.append(ticker)
        if len(calls) == 1:
            raise RuntimeError("provider unavailable")
        return pd.DataFrame({"Date": ["2020-01-02"], "Close": [10.5]})

    monkeypatch.setattr(technical, "fetch_full_price_history", fetch)
    with pytest.raises(DataFetchError):
        download_price_history("MU")
    assert download_price_history("mu").body == download_price_history(" MU ").body
    assert calls == ["MU", "MU"]
    download_price_history("SPY")
    isolated_chart_cache[0] = 301
    download_price_history("MU")
    assert calls == ["MU", "MU", "SPY", "MU"]


def test_concurrent_charts_share_one_provider_call(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import portfolio.technical_analysis.technical_analysis as technical
    from api.routers.chart import ChartRequest, run_chart

    entered = threading.Event()
    release = threading.Event()
    calls = []

    def fetch(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return {"value": 42}

    monkeypatch.setattr(technical, "get_data", fetch)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(run_chart, ChartRequest(ticker="MU")) for _ in range(6)]
        try:
            assert entered.wait(2)
        finally:
            release.set()
        assert [_json(future.result(timeout=3))["value"] for future in futures] == [42] * 6
    assert len(calls) == 1
