"""Opt-in checks against a disposable Postgres 16 + pgvector database.

Run with TEST_POSTGRES_URL pointing at a dedicated test database. Each run uses
and drops its own schema. The relevant existing upgrades are applied directly:
the full historical chain currently re-creates schema_definitions.
"""

from __future__ import annotations

import os
import runpy
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Thread

import psycopg
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from api import auth_store, llm_settings, memory_db, postgres, retrieval
from api.postgres_state import PostgresStateConnection


@pytest.fixture(scope="module")
def migrated_database():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL must point at a disposable Postgres + pgvector database")
    schema = f"tl181_{uuid.uuid4().hex}"
    engine = sa.create_engine(
        sa.engine.make_url(url).set(drivername="postgresql+psycopg"),
        connect_args={"options": f"-csearch_path={schema},public"},
    )
    migrations = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    upgrades = (
        "20260429_0001_gcp_state_schema.py",
        "20260502_0002_app_settings.py",
        "20260505_0007_ontology_native_retrieval.py",
        "20260515_0002_conversation_session_titles.py",
        "20260602_0001_auth_users_sessions.py",
        "20261017_0001_company_research_runs.py",
    )
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema)))
        try:
            with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
                for migration in upgrades:
                    runpy.run_path(str(migrations / migration))["upgrade"]()
            yield make_conninfo(url, options=f"-csearch_path={schema},public", application_name=schema)
        finally:
            postgres.close_pools()
            engine.dispose()
            admin.execute(psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(psycopg.sql.Identifier(schema)))


@pytest.fixture
def pg_state(migrated_database, monkeypatch):
    postgres.close_pools()
    monkeypatch.setenv("DATABASE_URL", migrated_database)
    monkeypatch.setenv("STATE_DB_BACKEND", "postgres")
    monkeypatch.setenv("POSTGRES_POOL_MIN_SIZE", "0")
    monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "2")
    monkeypatch.setenv("POSTGRES_POOL_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("AUTH_PASSWORD_HASH", "test-only-hash")
    monkeypatch.delenv("AUTH_SMOKE_PASSWORD_HASH", raising=False)
    monkeypatch.setattr(auth_store, "_seeded", False)
    for store in (auth_store, memory_db, llm_settings):
        if store._conn is not None:
            store._conn.close()
        # Teardown must not restore a SQLite connection that we just closed.
        store._conn = None

    def no_direct_connections(*args, **kwargs):
        raise AssertionError("a runtime caller bypassed the shared pool")

    monkeypatch.setattr(postgres, "open_connection", no_direct_connections)
    monkeypatch.setattr(postgres, "_new_direct_connection", no_direct_connections)
    yield migrated_database
    postgres.close_pools()


def test_stores_and_retrieval_share_a_single_slot_without_nested_checkout(pg_state, monkeypatch):
    monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "1")
    auth_store.ensure_auth_users_seeded()
    user = auth_store.get_or_create_cloudflare_user("admin@tl181.example")
    session = auth_store.create_session(user)
    assert auth_store.lookup_session(session.session_token).user == user
    assert auth_store.verify_csrf(session.session_token, session.csrf_token)
    auth_store.revoke_session(session.session_token)
    assert auth_store.lookup_session(session.session_token) is None

    saved = memory_db.save_session([{"role": "user", "content": "pool integration"}])
    sid = saved["session_id"]
    assert memory_db.rename_session(sid, "Pool test")["title"] == "Pool test"
    assert memory_db.get_or_create_session(sid)["title"] == "Pool test"
    assert (
        memory_db.begin_turn(
            sid, {"role": "user", "client_turn_id": "t1"}, {"role": "assistant", "client_turn_id": "t1"}
        )
        == 3
    )
    assert memory_db.turn_exists(sid, "t1")

    llm_settings.set_setting("tl181.setting", "saved")
    assert llm_settings.get_settings(["tl181.setting"])["tl181.setting"]["value"] == "saved"
    assert llm_settings.ensure_setting("tl181.setting", "ignored")["value"] == "saved"

    monkeypatch.setattr(retrieval, "_embed", lambda texts: [[1.0] + [0.0] * 383 for _ in texts])
    doc_id = retrieval.index_document("thesis", "Postgres connection pool integration test.", ticker="POOL")
    assert retrieval.get_indexed_count()["thesis"] >= 1
    assert (
        retrieval._pg_search([1.0] + [0.0] * 383, doc_types=["thesis"], tickers=["POOL"], top_k=1)[0]["doc_id"]
        == doc_id
    )
    assert (
        retrieval._pg_lexical_search(
            "connection pool", doc_types=["thesis"], tickers=["POOL"], top_k=1, fallback_reason="test"
        )[0]["doc_id"]
        == doc_id
    )
    assert retrieval.delete_document(doc_id)
    assert len(postgres._POOLS) == 1
    assert postgres._get_pool().get_stats()["pool_size"] == 1
    assert auth_store._conn is None and memory_db._conn is None and llm_settings._conn is None


def test_concurrent_transactions_are_independent(pg_state):
    key = f"tl181.isolation.{uuid.uuid4().hex}"
    with PostgresStateConnection() as writer:
        writer.execute("INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)", (key, "pending", "now"))
        with postgres.connect(read_only=True) as reader:
            assert reader.execute("SELECT value FROM app_settings WHERE key = %s", (key,)).fetchone() is None
    assert llm_settings.get_setting(key)["value"] == "pending"

    rolled_back = f"tl181.rollback.{uuid.uuid4().hex}"
    with pytest.raises(ValueError, match="abort"), PostgresStateConnection() as writer:
        writer.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)", (rolled_back, "discard", "now")
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(llm_settings.set_setting, key, "committed elsewhere").result(timeout=3)
        raise ValueError("abort")
    assert llm_settings.get_setting(rolled_back) is None
    assert llm_settings.get_setting(key)["value"] == "committed elsewhere"


def test_mixed_concurrent_callers_never_exceed_pool_max(pg_state):
    done = Event()
    counts = []
    failures = []

    def monitor():
        try:
            with psycopg.connect(pg_state, autocommit=True, application_name="tl181-observer") as admin:
                while not done.is_set():
                    counts.append(
                        admin.execute(
                            "SELECT count(*) FROM pg_stat_activity WHERE application_name = %s",
                            (conninfo_to_dict(pg_state)["application_name"],),
                        ).fetchone()[0]
                    )
                    done.wait(0.005)
        except BaseException as exc:
            failures.append(exc)

    def read(i):
        if i % 3 == 0:
            return llm_settings.get_setting("tl181.missing")
        if i % 3 == 1:
            with PostgresStateConnection(read_only=True) as conn:
                return conn.execute("SELECT pg_sleep(?), 1 AS value", (0.02,)).fetchone()["value"]
        with postgres.connect(read_only=True) as conn:
            return conn.execute("SELECT pg_sleep(%s), 1 AS value", (0.02,)).fetchone()["value"]

    observer = Thread(target=monitor)
    observer.start()
    try:
        with ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(read, range(30)))
    finally:
        done.set()
        observer.join(5)
    assert not observer.is_alive() and not failures
    assert counts and max(counts) == 2
    assert postgres._get_pool().get_stats()["pool_size"] == 2


def test_stale_backend_is_replaced_for_an_idempotent_store_read(pg_state, monkeypatch):
    monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "1")
    with postgres.connect(read_only=True) as conn:
        stale_pid = conn.info.backend_pid
    with psycopg.connect(pg_state, autocommit=True) as admin:
        assert admin.execute("SELECT pg_terminate_backend(%s)", (stale_pid,)).fetchone()[0]
    assert llm_settings.get_setting("tl181.missing") is None
    with postgres.connect(read_only=True) as conn:
        assert conn.info.backend_pid != stale_pid


@pytest.mark.parametrize("caller", ["raw", "facade", "settings", "retrieval"])
def test_warm_single_query_read_has_one_protocol_exchange(pg_state, monkeypatch, tmp_path, caller):
    monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "1")
    with postgres.connect(read_only=True) as physical:
        physical.execute("SELECT 1").fetchall()
    trace_path = tmp_path / "protocol.log"
    with trace_path.open("wb") as trace:
        try:
            physical.pgconn.trace(trace.fileno())
        except psycopg.NotSupportedError:
            pytest.skip("libpq protocol tracing requires Linux")
        try:
            if caller == "raw":
                with postgres.connect(read_only=True) as conn:
                    conn.execute("SELECT 42 AS value").fetchall()
            elif caller == "facade":
                with PostgresStateConnection(read_only=True) as conn:
                    conn.execute("SELECT 42 AS value").fetchall()
            elif caller == "settings":
                llm_settings.get_setting("tl181.missing")
            else:
                retrieval.get_indexed_count()
        finally:
            physical.pgconn.untrace()
    protocol = trace_path.read_text()
    assert protocol.count("ReadyForQuery") == 1, protocol
    assert all(command not in protocol for command in ("BEGIN", "COMMIT", "ROLLBACK")), protocol
