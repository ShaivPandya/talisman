from __future__ import annotations

import threading
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from macro.liquidity.liquidity import (
    add_japan_derived_series,
    build_component_as_of,
    build_data_quality,
    build_weekly_panel,
    cap_weekly_panel_to_completed_week,
)


def test_completed_week_cap_drops_partial_future_bucket():
    raw = pd.DataFrame(
        {"on_rrp": [3719.0, 2034.0]},
        index=pd.to_datetime(["2026-05-13", "2026-05-14"]),
    )

    weekly = build_weekly_panel(raw, week_ending="W-WED")
    assert weekly.index[-1] == pd.Timestamp("2026-05-20")

    capped, suppressed = cap_weekly_panel_to_completed_week(
        weekly,
        now=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
        week_ending="W-WED",
    )

    assert capped.index[-1] == pd.Timestamp("2026-05-13")
    assert suppressed == pd.Timestamp("2026-05-20")


def test_japan_yoy_uses_native_frequency_before_weekly_alignment():
    raw_index = pd.DatetimeIndex(
        sorted(
            {
                *pd.date_range("2025-04-01", "2026-04-01", freq="MS").to_pydatetime().tolist(),
                *pd.to_datetime(["2024-07-01", "2024-10-01", "2025-01-01", "2025-04-01", "2025-07-01"]).to_pydatetime(),
                *pd.date_range("2026-05-08", "2026-05-14", freq="D").to_pydatetime().tolist(),
            }
        )
    )
    raw = pd.DataFrame(index=raw_index, columns=["boj_assets", "jpn_m3_yoy", "jpn_credit_private"], dtype=float)

    for month in pd.date_range("2025-04-01", "2026-03-01", freq="MS"):
        raw.loc[month, "boj_assets"] = 100.0
    raw.loc[pd.Timestamp("2026-04-01"), "boj_assets"] = 90.0

    raw.loc[pd.Timestamp("2025-11-01"), "jpn_m3_yoy"] = 1.2

    for date, value in {
        "2024-07-01": 100.0,
        "2024-10-01": 101.0,
        "2025-01-01": 102.0,
        "2025-04-01": 103.0,
        "2025-07-01": 80.0,
    }.items():
        raw.loc[pd.Timestamp(date), "jpn_credit_private"] = value

    weekly = pd.DataFrame(index=pd.date_range("2025-07-02", "2026-05-13", freq="W-WED"))
    result = add_japan_derived_series(weekly, raw, week_ending="W-WED")

    assert result.loc[pd.Timestamp("2026-05-13"), "boj_assets_yoy"] == pytest.approx(-10.0)
    assert result.loc[pd.Timestamp("2026-05-13"), "jpn_credit_yoy"] == pytest.approx(-20.0)
    assert result.loc[pd.Timestamp("2026-05-13"), "jpn_m3_yoy"] == pytest.approx(1.2)


def test_data_quality_warns_for_suppressed_future_bucket_and_lagged_component():
    quality = build_data_quality(
        pd.Timestamp("2026-05-13"),
        {
            "net_liquidity": "2026-05-13",
            "jpn_m3_yoy": "2025-11-01",
        },
        suppressed_future_date=pd.Timestamp("2026-05-20"),
    )

    assert quality["status"] == "degraded"
    assert any("Suppressed partial weekly bucket ending 2026-05-20" in warning for warning in quality["warnings"])
    assert any("M3 YoY is lagged" in warning for warning in quality["warnings"])


def test_quarterly_source_dates_use_period_end_for_freshness():
    raw = pd.DataFrame(
        {"jpn_credit_private": [1_135_794.3]},
        index=pd.to_datetime(["2025-07-01"]),
    )

    component_as_of = build_component_as_of(raw, None, pd.Timestamp("2026-05-27"))

    assert component_as_of["jpn_credit_yoy"] == "2025-09-30"

    quality = build_data_quality(pd.Timestamp("2026-05-27"), component_as_of)

    assert quality == {"status": "ok", "warnings": []}


def _weekly_point() -> pd.Series:
    return pd.Series([1.0], index=pd.to_datetime(["2026-01-07"]))


def test_fred_series_download_concurrently_in_series_order(monkeypatch):
    from macro.liquidity import liquidity

    in_flight = threading.Barrier(len(liquidity.SERIES), timeout=5)

    def fetch(_fred, _sid):
        in_flight.wait()  # passes only once every series is being fetched at the same time
        return _weekly_point()

    monkeypatch.setattr(liquidity, "fred_get_series", fetch)
    assert list(liquidity.fetch_fred_series(object()).columns) == list(liquidity.SERIES)


def test_fred_series_failures_are_reported_together(monkeypatch):
    from macro.liquidity import liquidity

    def fetch(_fred, sid):
        if sid == "NFCI":
            return pd.Series(dtype=float)
        if sid == "GDP":
            raise RuntimeError("boom")
        return _weekly_point()

    monkeypatch.setattr(liquidity, "fred_get_series", fetch)
    with pytest.raises(RuntimeError) as caught:
        liquidity.fetch_fred_series(object())
    assert "nfci (NFCI) returned empty series" in str(caught.value)
    assert "gdp (GDP) error: boom" in str(caught.value)


def test_ecb_series_download_concurrently_and_keep_partial_results(monkeypatch):
    from macro.liquidity import liquidity

    in_flight = threading.Barrier(len(liquidity.ECB_SERIES), timeout=5)
    failing_key = liquidity.ECB_SERIES["ecb_net_liquidity_effect"]

    class Client:
        def __init__(self, source):
            assert source == "ECB"

        def data(self, flow, *, key, timeout):
            in_flight.wait()
            if key == failing_key:
                raise TimeoutError("ECB slow")
            return key

    monkeypatch.setattr(liquidity, "SDMX_AVAILABLE", True)
    monkeypatch.setattr(liquidity, "sdmx", SimpleNamespace(Client=Client, to_pandas=lambda _key: _weekly_point()))
    df = liquidity.fetch_ecb_series()
    assert list(df.columns) == ["ecb_excess_liquidity"]


def test_fred_and_ecb_inputs_are_fetched_at_the_same_time(monkeypatch):
    from macro.liquidity import liquidity

    both = threading.Barrier(2, timeout=5)
    ecb = pd.DataFrame({"ecb_excess_liquidity": [1.0]})

    def fred(_client):
        both.wait()
        return pd.DataFrame({"on_rrp": [2.0]})

    def fetch_ecb():
        both.wait()
        return ecb

    monkeypatch.setattr(liquidity, "fetch_fred_series", fred)
    monkeypatch.setattr(liquidity, "fetch_ecb_series", fetch_ecb)
    df, df_ecb = liquidity.fetch_inputs(object())
    assert df["on_rrp"].iloc[0] == 2000.0  # scaled from billions to millions
    assert df_ecb is ecb


def test_fetch_inputs_can_skip_ecb(monkeypatch):
    from macro.liquidity import liquidity

    monkeypatch.setattr(liquidity, "fetch_fred_series", lambda _client: pd.DataFrame({"m2": [1.0]}))
    monkeypatch.setattr(liquidity, "fetch_ecb_series", lambda: pytest.fail("ECB should not be fetched"))
    assert liquidity.fetch_inputs(object(), include_ecb=False)[1] is None
