"""The migration job owns current schema definitions, including API bodies."""

from __future__ import annotations

import sqlite3

import pytest

from api import migrate
from ontology.schema_definitions import create_schema_registry_tables


def test_schema_seed_covers_all_kinds_and_is_idempotent():
    with sqlite3.connect(":memory:") as conn:
        create_schema_registry_tables(conn)
        migrate.seed_runtime_schema_registry(conn)
        before = conn.execute("SELECT * FROM schema_definitions ORDER BY schema_kind, schema_name").fetchall()
        migrate.seed_runtime_schema_registry(conn)
        after = conn.execute("SELECT * FROM schema_definitions ORDER BY schema_kind, schema_name").fetchall()
        kinds = {row[0] for row in after}
        assert {"ontology_object", "ontology_relation", "domain_action", "api_request"} <= kinds
        assert any(row[0] == "api_request" and row[1] == "post:/api/agent/chat" for row in after)
        assert before == after


def test_seed_refuses_degraded_routes(monkeypatch):
    from api import safe_import

    monkeypatch.setattr(safe_import, "get_degraded_modules", lambda: {"api.routers.sizer": "failed"})
    with sqlite3.connect(":memory:") as conn, pytest.raises(RuntimeError, match="incomplete API schema registry"):
        migrate.seed_runtime_schema_registry(conn)


@pytest.mark.parametrize("failure", [None, "upgrade", "seed"])
def test_migration_job_orders_upgrade_and_transactional_seed(monkeypatch, failure):
    from alembic import command

    from api import postgres, postgres_state

    events = []

    def upgrade(config, revision):
        assert config.config_file_name == "alembic.ini"
        assert revision == "head"
        events.append("upgrade")
        if failure == "upgrade":
            raise RuntimeError("upgrade failed")

    class Connection:
        def __enter__(self):
            events.append("connect")
            return self

        def __exit__(self, exc_type, *_args):
            events.append("rollback" if exc_type else "commit")

    def seed(conn):
        assert isinstance(conn, Connection)
        events.append("seed")
        if failure == "seed":
            raise RuntimeError("seed failed")

    monkeypatch.setattr(command, "upgrade", upgrade)
    monkeypatch.setattr(postgres_state, "PostgresStateConnection", Connection)
    monkeypatch.setattr(postgres, "close_pools", lambda: events.append("close"))
    monkeypatch.setattr(migrate, "seed_runtime_schema_registry", seed)
    if failure:
        with pytest.raises(RuntimeError, match=f"{failure} failed"):
            migrate.main()
    else:
        migrate.main()
    expected = {
        None: ["upgrade", "connect", "seed", "commit", "close"],
        "upgrade": ["upgrade", "close"],
        "seed": ["upgrade", "connect", "seed", "rollback", "close"],
    }
    assert events == expected[failure]
