from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

from api import snapshot_store as store


def test_snapshot_store_roundtrip_and_meta(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_SQLITE_PATH", tmp_path / "snapshots.sqlite3")
    record = store.write_snapshot_success(
        "unit:test",
        {"value": 42},
        as_of_date="2026-05-01",
        fetched_at=(datetime.now() - timedelta(hours=1)).isoformat(),
    )

    assert record.payload == {"value": 42}

    response = store.get_snapshot_response("unit:test")
    assert response is not None
    assert response["value"] == 42
    assert response["_meta"]["snapshot"]["key"] == "unit:test"
    assert response["_meta"]["snapshot"]["as_of"] == "2026-05-01"
    assert response["_meta"]["snapshot"]["stale"] is False


def test_snapshot_store_marks_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_SQLITE_PATH", tmp_path / "snapshots.sqlite3")
    store.write_snapshot_success(
        "unit:stale",
        {"value": 1},
        as_of_date="2026-04-30",
        fetched_at=(datetime.now() - timedelta(days=3)).isoformat(),
    )

    response = store.get_snapshot_response("unit:stale", max_age_seconds=60)
    assert response is not None
    assert response["_meta"]["snapshot"]["stale"] is True


def test_snapshot_failure_preserves_last_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_SQLITE_PATH", tmp_path / "snapshots.sqlite3")
    store.write_snapshot_success("unit:failure", {"value": "old"}, as_of_date="2026-05-01")

    record = store.write_snapshot_failure("unit:failure", "vendor timeout")
    assert record is not None
    assert record.payload == {"value": "old"}
    assert record.status == "error"

    response = store.get_snapshot_response("unit:failure")
    assert response is not None
    assert response["value"] == "old"
    assert response["_meta"]["snapshot"]["refresh_status"] == "error"
    assert response["_meta"]["snapshot"]["error"] == "vendor timeout"


def test_postgres_snapshot_listing_reads_current_temporal_versions_directly(monkeypatch):
    sql_calls: list[str] = []

    class _Result:
        def fetchall(self):
            return [
                {
                    "snapshot_key": "unit:current",
                    "quality": "degraded",
                    "as_of": "2026-06-15",
                    "load_time": "2026-06-15T21:00:00+00:00",
                    "status": "ok",
                    "error": None,
                    "version": 1,
                    "artifact_uri": None,
                }
            ]

    class _Conn:
        def execute(self, sql: str):
            sql_calls.append(sql)
            return _Result()

    class _Repo:
        @contextmanager
        def _connect(self):
            yield _Conn()

    monkeypatch.setattr(store, "use_postgres_state", lambda: True)
    monkeypatch.setattr(store, "TemporalOntologyRepository", _Repo)

    records = store.list_snapshot_records()

    assert records[0].payload is None
    assert records[0].quality == "degraded"
    assert "SELECT DISTINCT ON (snapshot_key) *" not in sql_calls[0]
    assert "payload_json->>'quality'" in sql_calls[0]
    assert records[0].as_of_date == "2026-06-15"
    assert "computed_snapshot_versions" in sql_calls[0]
    assert "DISTINCT ON (snapshot_key)" in sql_calls[0]
    assert "ontology_current_computed_snapshot_read_model" not in sql_calls[0]


def test_metadata_listing_omits_payload_and_preserves_embedded_quality(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_SQLITE_PATH", tmp_path / "snapshots.sqlite3")
    store.write_snapshot_success(
        "portfolio_risk_dashboard:current:v1",
        {"quality": "degraded", "large": ["x"] * 10000},
        as_of_date="2026-10-21",
    )
    records = store.list_snapshot_records()
    assert len(records) == 1
    assert records[0].payload is None
    assert records[0].quality == "degraded"
    store.write_snapshot_failure("missing", "refresh failed")
    missing = {r.snapshot_key: r for r in store.list_snapshot_records()}["missing"]
    assert missing.payload is None
    assert missing.status == "error"


def test_signal_projection_excludes_raw_before_decoding_and_copies_once(monkeypatch, tmp_path):
    from api.signal_snapshot import get_signal_aggregator_snapshot_response
    from api.snapshot_keys import SNAPSHOT_SIGNAL_AGGREGATOR

    monkeypatch.setattr(store, "_SQLITE_PATH", tmp_path / "snapshots.sqlite3")
    payload = {
        "raw_modules": {"large": ["raw-sentinel"] * 1000},
        "regime": {"score": 0},
        "history": {"series": [{"date": f"2026-01-{i:02}", "score": i} for i in range(1, 31)]},
    }
    store.write_snapshot_success(SNAPSHOT_SIGNAL_AGGREGATOR, payload, as_of_date="2026-10-21")
    original_decode = store.json.loads
    original_copy = store.copy.deepcopy
    copies = []

    def decode(raw, *args, **kwargs):
        assert "raw-sentinel" not in raw
        return original_decode(raw, *args, **kwargs)

    def deepcopy(value, *args, **kwargs):
        copies.append(value)
        return original_copy(value, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(store.json, "loads", decode)
        patch.setattr(store.copy, "deepcopy", deepcopy)
        compact = get_signal_aggregator_snapshot_response(lookback_weeks=26, include_raw_modules=False)
    assert compact is not None
    assert "raw_modules" not in compact
    assert len(compact["history"]["series"]) == 26
    assert len(copies) == 1
    compact["history"]["series"][0]["score"] = 999
    full = get_signal_aggregator_snapshot_response(lookback_weeks=156, include_raw_modules=True)
    assert full["raw_modules"] == payload["raw_modules"]
    assert len(full["history"]["series"]) == 30
    assert full["history"]["series"][4]["score"] == 5
