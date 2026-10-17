from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from api.position_risk import _freshness_state

EASTERN = ZoneInfo("America/New_York")


def test_position_risk_market_freshness_uses_nyse_holidays():
    freshness = _freshness_state(
        "2026-05-22",
        now=datetime(2026, 5, 25, 18, 0, tzinfo=EASTERN),
        policy="market_day",
    )

    assert freshness["fresh"] is True
    assert freshness["policy"] == "market_session"
    assert freshness["expected_as_of_date"] == "2026-05-22"
    assert freshness["expected_market_date"] == "2026-05-22"


def test_position_risk_macro_freshness_uses_source_window():
    freshness = _freshness_state(
        "2026-05-22",
        now=datetime(2026, 5, 31, 12, 0, tzinfo=EASTERN),
        policy="max_age_days",
        max_age_days=10,
    )

    assert freshness["fresh"] is True
    assert freshness["oldest_acceptable_date"] == "2026-05-21"


def test_scheduled_optional_refresh_fetches_new_weekly_report_before_old_one_expires(tmp_path, monkeypatch):
    from api import position_risk, snapshot_store
    from ontology.sources.macro import PositioningAdapter

    monkeypatch.setattr(snapshot_store, "_SQLITE_PATH", tmp_path / "snapshots.db")
    config = position_risk._MODULES["positioning_summary"]
    snapshot_store.write_snapshot_success(
        config.snapshot_key,
        {"rows": [{"instrument": "SP500", "report_date": "2026-10-06", "lf_z": 1.0}]},
        as_of_date="2026-10-06",
    )
    calls = []

    def fetch(_self):
        calls.append(True)
        return [{"instrument": "SP500", "report_date": "2026-10-13", "lf_z": 1.5}]

    monkeypatch.setattr(PositioningAdapter, "fetch", fetch)
    now = datetime(2026, 10, 16, 17, 0, tzinfo=EASTERN)
    cached_state, _ = position_risk._load_module(config, now=now)
    assert cached_state["accepted"] is True
    assert cached_state["as_of"] == "2026-10-06"
    assert calls == []

    refreshed, _ = position_risk._load_module(config, now=now, force_refresh=True)
    assert refreshed["accepted"] is True
    assert refreshed["as_of"] == "2026-10-13"
    assert calls == [True]
    assert snapshot_store.read_snapshot(config.snapshot_key).as_of_date == "2026-10-13"


def test_forced_optional_refresh_does_not_mask_provider_failure(tmp_path, monkeypatch):
    from api import position_risk, snapshot_store
    from ontology.sources.macro import PositioningAdapter

    monkeypatch.setattr(snapshot_store, "_SQLITE_PATH", tmp_path / "snapshots.db")
    config = position_risk._MODULES["positioning_summary"]
    snapshot_store.write_snapshot_success(
        config.snapshot_key,
        {"rows": [{"instrument": "SP500", "report_date": "2026-10-13", "lf_z": 1.0}]},
        as_of_date="2026-10-13",
    )

    def fail(_self):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(PositioningAdapter, "fetch", fail)
    state, data = position_risk._load_module(
        config,
        now=datetime(2026, 10, 16, 17, 0, tzinfo=EASTERN),
        force_refresh=True,
    )
    assert state["accepted"] is False
    assert state["status"] == "error"
    assert data is None
    assert state["prior_snapshot"]["as_of"] == "2026-10-13"


def test_scheduled_risk_refresh_forces_only_optional_inputs(monkeypatch):
    from api import position_risk

    calls = {}

    def load(config, **kwargs):
        calls[config.name] = kwargs["force_refresh"]
        return {}, None

    monkeypatch.setattr(position_risk, "_load_module", load)
    monkeypatch.setattr(position_risk, "_compute_components", lambda _: {})
    position_risk.load_global_risk_input_bundle(refresh_optional_sources=True)
    assert all(calls[name] for name in position_risk.OPTIONAL_MODULES)
    assert not any(calls[name] for name in position_risk.REQUIRED_MODULES if name != "portfolio")
