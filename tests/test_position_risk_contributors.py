from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from api import position_risk, position_risk_store
from ontology.sector_mapper import SectorResolution


@pytest.fixture
def isolated_risk_store(tmp_path, monkeypatch):
    monkeypatch.setattr(position_risk_store, "_SQLITE_PATH", tmp_path / "risk.sqlite3")


def position_snapshots():
    # Separate stock and option legs must still count toward portfolio totals.
    tickers = ["ALFA", "BETA", "GAMMA", *(["NOVA"] * 3), "NOVA2", "OMEGA", *(["RIDE"] * 5)]
    return [
        {
            "ticker": ticker,
            "result_id": f"position-risk:{ticker}:{index}",
            "risk_score": 0.3936 if ticker == "RIDE" else 0.378,
            "risk_level": "low",
            "quality": "degraded",
            "confidence": 0.97,
            "evidence": [{"component": "volatility_cluster", "contribution": 0.1575}],
        }
        for index, ticker in enumerate(tickers)
    ]


def test_latest_risk_repairs_legacy_contributors_without_rewriting_snapshot(isolated_risk_store):
    positions = position_snapshots()
    original = {
        "result_id": "portfolio-risk:legacy",
        "computed_at": "2026-10-16T11:22:29+00:00",
        "position_count": 13,
        "risk_buckets": {"high": 0, "medium": 0, "low": 13},
        "position_snapshots": positions,
        "top_contributors": [{"ticker": "RIDE", "risk_score": 0.3936}] * 5,
    }
    position_risk_store.write_portfolio_risk_snapshot(original)

    latest = position_risk.get_latest_portfolio_risk()

    assert latest is not None
    contributors = latest["top_contributors"]
    assert [row["ticker"] for row in contributors] == ["RIDE", "OMEGA", "NOVA2", "NOVA", "GAMMA"]
    assert contributors[0]["position_count"] == 5
    assert contributors[0]["risk_snapshot_id"] == positions[8]["result_id"]
    assert contributors[3]["position_count"] == 3
    assert latest["position_count"] == 13
    assert latest["risk_buckets"] == original["risk_buckets"]
    assert position_risk_store.read_latest_portfolio_risk() == original


def test_portfolio_refresh_groups_contributors_and_preserves_all_position_scores(isolated_risk_store, monkeypatch):
    now = datetime(2026, 10, 16, 11, 22, tzinfo=UTC)
    positions = [{"ticker": row["ticker"], "asset": "equity"} for row in position_snapshots()]
    bundle = position_risk.RiskInputBundle(
        now=now,
        source_status={
            "sentiment": {
                "status": "partial",
                "quality": "degraded",
                "required": False,
                "accepted": False,
                "detail": "NAAIM current data requires member access",
            }
        },
        module_data={},
        input_snapshots={},
        components={
            "volatility_cluster": 0.45,
            "breadth_stress": 0.3,
            "sector_scores": {"Technology": 0.4},
            "macro_regime": 0.3,
        },
        market_snapshot_as_of="2026-10-14",
    )
    monkeypatch.setattr(position_risk, "_load_portfolio_positions", lambda **kwargs: deepcopy(positions))
    monkeypatch.setattr(position_risk, "load_global_risk_input_bundle", lambda **kwargs: bundle)
    monkeypatch.setattr(
        position_risk.SectorMapper,
        "resolve_sector",
        lambda *args: SectorResolution("Technology", "test"),
    )

    snapshot = position_risk.refresh_portfolio_risk()

    assert snapshot["position_count"] == len(snapshot["position_snapshots"]) == 13
    assert snapshot["risk_buckets"] == {"high": 0, "medium": 0, "low": 13}
    assert snapshot["average_risk_score"] == snapshot["max_risk_score"] == 0.3775
    assert len({row["ticker"] for row in snapshot["top_contributors"]}) == 5
    assert snapshot["top_contributors"][0]["position_count"] == 5
    assert snapshot["quality"] == "degraded"
    assert snapshot["degraded_modules"][0]["required"] is False


def test_contributors_keep_highest_score_for_each_ticker():
    positions = position_snapshots()
    positions[-1]["risk_score"] = 0.7
    positions[-1]["risk_level"] = "medium"

    contributors = position_risk._top_risk_contributors(positions, limit=2)

    assert [row["ticker"] for row in contributors] == ["RIDE", "OMEGA"]
    assert contributors[0]["risk_score"] == 0.7
    assert contributors[0]["risk_level"] == "medium"
    assert contributors[0]["position_count"] == 5
    assert contributors[0]["risk_snapshot_id"] == positions[-1]["result_id"]
