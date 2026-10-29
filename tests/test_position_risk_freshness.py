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


def test_survey_failure_preserves_fresh_volatility_and_degraded_status(tmp_path, monkeypatch):
    from api import position_risk, snapshot_store
    from ontology.sources.macro import SentimentAdapter

    monkeypatch.setattr(snapshot_store, "_SQLITE_PATH", tmp_path / "snapshots.db")
    config = position_risk._MODULES["sentiment"]
    old = {"put_call": {}, "surveys": {}, "volatility": [{"date": "2026-07-31", "vvix": 90}]}
    snapshot_store.write_snapshot_success(config.snapshot_key, old, as_of_date="2026-07-31")
    current = {
        "put_call": {},
        "surveys": {"errors": {"naaim": "Current data requires subscription"}},
        "volatility": [{"date": "2026-10-28", "vvix": 115}],
    }
    monkeypatch.setattr(SentimentAdapter, "fetch", lambda _self: current)
    now = datetime(2026, 10, 29, 14, 0, tzinfo=EASTERN)
    state, data = position_risk._load_module(config, now=now, force_refresh=True)
    assert state["accepted"] is True
    assert state["used"] is True
    assert state["status"] == "partial"
    assert state["quality"] == "degraded"
    assert state["as_of"] == "2026-10-28"
    assert "naaim" in state["detail"]
    assert data.latest_vvix == 115
    saved = snapshot_store.read_snapshot(config.snapshot_key)
    assert saved.status == "ok"
    assert saved.payload == current
    assert saved.as_of_date == "2026-10-28"

    monkeypatch.setattr(
        SentimentAdapter,
        "fetch",
        lambda _self: (_ for _ in ()).throw(AssertionError("fresh partial data should be reused")),
    )
    cached_state, cached_data = position_risk._load_module(config, now=now)
    assert cached_state["status"] == "partial"
    assert cached_data.latest_vvix == 115


def test_survey_failure_without_usable_volatility_does_not_replace_prior_snapshot(tmp_path, monkeypatch):
    from api import position_risk, snapshot_store
    from ontology.sources.macro import SentimentAdapter

    monkeypatch.setattr(snapshot_store, "_SQLITE_PATH", tmp_path / "snapshots.db")
    config = position_risk._MODULES["sentiment"]
    old = {"put_call": {}, "surveys": {}, "volatility": [{"date": "2026-07-31", "vvix": 90}]}
    snapshot_store.write_snapshot_success(config.snapshot_key, old, as_of_date="2026-07-31")
    monkeypatch.setattr(
        SentimentAdapter,
        "fetch",
        lambda _self: {"put_call": {}, "surveys": {"errors": {"naaim": "subscription required"}}, "volatility": []},
    )
    state, data = position_risk._load_module(
        config, now=datetime(2026, 10, 29, 14, 0, tzinfo=EASTERN), force_refresh=True
    )
    assert state["accepted"] is False
    assert data is None
    assert snapshot_store.read_snapshot(config.snapshot_key).payload == old


def test_risk_input_modules_load_concurrently_in_module_order(monkeypatch):
    import threading

    from api import position_risk

    names = [*position_risk.REQUIRED_MODULES[1:], *position_risk.OPTIONAL_MODULES]
    in_flight = threading.Barrier(len(names), timeout=5)

    def load(config, **_kwargs):
        in_flight.wait()  # passes only once every module loads at the same time
        return {"status": "ok", "snapshot_key": config.snapshot_key}, {"module": config.name}

    monkeypatch.setattr(position_risk, "_load_module", load)
    monkeypatch.setattr(position_risk, "_compute_components", lambda _: {})
    bundle = position_risk.load_global_risk_input_bundle()

    assert list(bundle.source_status) == names
    assert list(bundle.input_snapshots) == names
    assert bundle.module_data == {name: {"module": name} for name in names}
