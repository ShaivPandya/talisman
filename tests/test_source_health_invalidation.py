from contextlib import contextmanager

import pytest

from api import snapshot_store as store
from api.source_health_cache import cached_source_health_value
from ontology.temporal_repository import SnapshotVersionWrite, TemporalOntologyRepository


def seed():
    assert cached_source_health_value("test", lambda: "old") == "old"


def assert_invalidated():
    assert cached_source_health_value("test", lambda: "new") == "new"


@pytest.mark.parametrize("operation", ["success", "failure", "delete"])
def test_sqlite_snapshot_mutations_invalidate(operation, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_SQLITE_PATH", tmp_path / "snapshots.sqlite3")
    store.write_snapshot_success("test", {"value": 1}, as_of_date="2026-10-21")
    seed()
    if operation == "success":
        store.write_snapshot_success("test", {"value": 2}, as_of_date="2026-10-21")
    elif operation == "failure":
        store.write_snapshot_failure("test", "vendor timeout")
    else:
        store.delete_snapshot("test")
    assert_invalidated()


@pytest.mark.parametrize("status", ["ok", "error"])
def test_direct_temporal_write_invalidates_only_after_commit(status, monkeypatch):
    seed()
    committed = []

    class Conn:
        def execute(self, *args):
            return self

        def fetchone(self):
            return {"snapshot_key": "test", "status": status}

        def commit(self):
            assert cached_source_health_value("test", lambda: "unexpected") == "old"
            committed.append(True)

    @contextmanager
    def connect(*args, **kwargs):
        yield Conn()

    repo = TemporalOntologyRepository()
    monkeypatch.setattr(repo, "_connect", connect)
    monkeypatch.setattr(repo, "_find_equivalent_current_snapshot", lambda *a, **kw: None)
    repo.write_computed_snapshot_version(
        SnapshotVersionWrite(
            snapshot_key="test",
            payload_hash="hash",
            valid_from="2026-10-21",
            payload={"value": 1},
            status=status,
        )
    )
    assert committed == [True]
    assert_invalidated()


def test_postgres_delete_invalidates_after_commit(monkeypatch):
    seed()

    class Conn:
        def execute(self, sql, params):
            assert "UPDATE computed_snapshot_versions" in sql

        def commit(self):
            assert cached_source_health_value("test", lambda: "unexpected") == "old"

    @contextmanager
    def connect(*args, **kwargs):
        yield Conn()

    monkeypatch.setattr(store, "use_postgres_state", lambda: True)
    monkeypatch.setattr(TemporalOntologyRepository, "_connect", connect)
    store.delete_snapshot("test")
    assert_invalidated()


@pytest.mark.parametrize("postgres", [False, True])
def test_portfolio_risk_write_invalidates(monkeypatch, postgres):
    from api import position_risk_store as risk_store

    seed()
    monkeypatch.setattr(risk_store, "use_postgres_state", lambda: postgres)

    def write(*args):
        assert cached_source_health_value("test", lambda: "unexpected") == "old"

    monkeypatch.setattr(risk_store, "_write_portfolio_postgres", write)
    monkeypatch.setattr(risk_store, "_write_portfolio_sqlite", write)
    risk_store.write_portfolio_risk_snapshot({"result_id": "risk:1"})
    assert_invalidated()


def test_failed_commit_keeps_cache(monkeypatch):
    seed()

    class Conn:
        def execute(self, *args):
            return self

        def fetchone(self):
            return {"snapshot_key": "test"}

        def commit(self):
            raise RuntimeError("commit failed")

    @contextmanager
    def connect(*args, **kwargs):
        yield Conn()

    repo = TemporalOntologyRepository()
    monkeypatch.setattr(repo, "_connect", connect)
    monkeypatch.setattr(repo, "_find_equivalent_current_snapshot", lambda *a, **kw: None)
    with pytest.raises(RuntimeError, match="commit failed"):
        repo.write_computed_snapshot_version(
            SnapshotVersionWrite(
                snapshot_key="test",
                payload_hash="hash",
                valid_from="2026-10-21",
                payload={"value": 1},
            )
        )
    assert cached_source_health_value("test", lambda: "unexpected") == "old"


def test_postgres_signal_projection_and_default_full_read(monkeypatch):
    queries = []

    class Conn:
        def execute(self, sql, params):
            queries.append(sql)
            return self

        def fetchone(self):
            return {"snapshot_key": "test", "payload_json": {"value": 1}}

    @contextmanager
    def connect(*args, **kwargs):
        yield Conn()

    repo = TemporalOntologyRepository()
    monkeypatch.setattr(repo, "_connect", connect)
    repo.read_computed_snapshot_version("test", include_raw_modules=False)
    repo.read_computed_snapshot_version("test")
    assert "payload_json - 'raw_modules' AS payload_json" in queries[0]
    assert "SELECT *" not in queries[0]
    assert "SELECT *" in queries[1]
