from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from api.alternative_data_adapters import SourceAccessError
from macro.economic_growth import backdrop


def test_fred_confirmed_identifiers_missing_data_and_license_gate(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "utils.retry.fred_get_series",
        lambda fred, series, **kwargs: (
            calls.append(series) or pd.Series([2.0, float("nan")], index=pd.to_datetime(["2026-08-01", "2026-09-01"]))
        ),
    )
    monkeypatch.delenv("ALTERNATIVE_DATA_CASE_SHILLER_PERMISSION_CONFIRMED", raising=False)
    result = backdrop.fred_reading("payrolls", fred=object())
    assert result["value"] is None and result["as_of"] == "2026-09-01"
    assert result["values"] == [2, None] and result["unit"] == "thousands of persons"
    assert backdrop.fred_reading("case_shiller", fred=object())["status"] == "license_required"
    assert calls == ["PAYEMS"]
    assert backdrop.FRED_SERIES["lending_standards"][0] == "DRTSCILM"


def test_gscpi_uses_latest_vintage_without_filling_missing_values():
    result = backdrop.normalize_gscpi("Date,Sep-26,Oct-26\n31-Aug-2026,1,2\n30-Sep-2026,3,\n,,\n")
    assert result["value"] is None and result["as_of"] == "2026-09-30" and result["vintage"] == "Oct-26"
    with pytest.raises(SourceAccessError):
        backdrop.normalize_gscpi("renamed,bad\n1,2")


def test_nyfed_forecast_period_vintage_and_publisher_release_note():
    result = backdrop.normalize_nyfed(
        "Update,Year,Nowcast\n16-Oct,2026,2.5\n23-Oct,2026,\n30-Oct,,\n", "2026Q3", "Fridays except federal holidays"
    )[0]
    assert result["value"] is None and result["vintage_date"] == "2026-10-23"
    assert result["kind"] == "publisher_nowcast" and result["forecast_period"] == "2026Q3"
    assert result["next_release_note"] == "Fridays except federal holidays"


def test_cleveland_uses_publisher_vintage_not_retrieval_or_target_month():
    data = [
        {
            "chart": {"_comment": "2026-10-23 00:00", "subcaption": "2026-10"},
            "dataset": [
                {"seriesname": name, "data": [{"value": "1.2"}, {"value": ""}]}
                for name in ("CPI Inflation", "Core CPI Inflation", "PCE Inflation", "Core PCE Inflation")
            ],
        }
    ]
    rows = backdrop.normalize_cleveland(data)
    assert len(rows) == 4 and all(row["value"] is None and row["as_of"] == "2026-10-23" for row in rows)
    assert rows[0]["forecast_period"] == "2026-10"
    with pytest.raises((ValueError, KeyError)):
        backdrop.normalize_cleveland([{"changed": []}])


def test_imf_reuses_client_and_keeps_country_coverage_and_edition(monkeypatch):
    year = date.today().year
    meta = {
        indicator: {
            "label": label,
            "dataset": "WEO",
            "source": "World Economic Outlook (October 2026)",
            "unit": "Annual percent change",
            "last-modified": "2026-10-08 14:43:32",
        }
        for indicator, label in [("NGDP_RPCH", "Real GDP growth"), ("PCPIPCH", "Inflation")]
    }

    class Client:
        def json(self, url):
            return {"indicators": meta} if url.endswith("indicators") else {"values": {"NGDP_RPCH": {}, "PCPIPCH": {}}}

    monkeypatch.setattr("fx.model.src.data_imf.fetch_imf_datamapper_json", Client().json)
    calls = []

    def fetch(indicator, iso, cache, *, payload):
        calls.append((indicator, iso))
        return pd.Series([2.2, float("nan")], index=pd.to_datetime([f"{year}-12-31", f"{year + 1}-12-31"]))

    monkeypatch.setattr("fx.model.src.data_imf.fetch_imf_datamapper_indicator", fetch)
    rows = backdrop.imf()
    assert len(rows) == 36 and len(calls) == 18
    assert {r["country"] for r in rows} == set(backdrop.COUNTRIES)
    assert rows[0]["vintage"] == "World Economic Outlook (October 2026)"
    assert rows[0]["vintage_date"] == "2026-10-08" and rows[1]["value"] is None


def test_backdrop_route_and_existing_agent_read_use_same_snapshot(auth_client, monkeypatch):
    from api.agent_tools import execute_tool
    from api.cache import daily_cache, delete_cached
    from api.routers import economic_growth

    delete_cached(daily_cache, "economic_backdrop")
    payload = {"readings": [], "as_of": None, "fetched_at": "2026-10-24T12:00:00Z", "note": "publisher forecasts"}
    monkeypatch.setattr(economic_growth, "get_snapshot_backed_response", lambda **kwargs: payload)
    response = auth_client.get("/api/economic-growth/backdrop")
    assert response.status_code == 200 and response.json() == payload
    result = json.loads(execute_tool("get_economic_growth", {"section": "backdrop"}))
    assert result["readings"] == [] and result["note"] == payload["note"]
