"""Auth query budgets and migration checks on disposable Postgres (opt in).

Set TEST_AUTH_POSTGRES_URL to a disposable database. Each run creates its own
schema. Auth needs no vector types, so only the unrelated vector adapter setup
is skipped; the real shared pool, facade, SQL, and migrations are exercised.
"""

import os
import runpy
import uuid
from pathlib import Path

import pgvector.psycopg
import psycopg
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg.conninfo import make_conninfo

from api import auth_store, postgres
from api.performance import TimingState, timing_context


@pytest.fixture(scope="module")
def auth_database():
    url = os.getenv("TEST_AUTH_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_AUTH_POSTGRES_URL must point at a disposable Postgres database")
    schema = f"tl183_{uuid.uuid4().hex}"
    engine = sa.create_engine(
        sa.engine.make_url(url).set(drivername="postgresql+psycopg"),
        connect_args={"options": f"-csearch_path={schema},public"},
    )
    migrations = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema)))
        try:
            with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
                runpy.run_path(str(migrations / "20260602_0001_auth_users_sessions.py"))["upgrade"]()
                runpy.run_path(str(migrations / "20261021_0001_auth_email_lower_index.py"))["upgrade"]()
            yield make_conninfo(url, options=f"-csearch_path={schema},public")
        finally:
            postgres.close_pools()
            engine.dispose()
            admin.execute(psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(psycopg.sql.Identifier(schema)))


@pytest.fixture
def pg_session(auth_database, monkeypatch):
    postgres.close_pools()
    monkeypatch.setenv("DATABASE_URL", auth_database)
    monkeypatch.setenv("STATE_DB_BACKEND", "postgres")
    monkeypatch.setenv("POSTGRES_POOL_MIN_SIZE", "1")
    monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "1")
    monkeypatch.setenv("AUTH_PASSWORD_HASH", "")
    monkeypatch.delenv("AUTH_SMOKE_PASSWORD_HASH", raising=False)
    monkeypatch.setattr(pgvector.psycopg, "register_vector", lambda conn: None)
    auth_store.ensure_auth_users_seeded()
    with auth_store._get_conn() as conn:
        user = auth_store._upsert_user(
            conn, username=f"member-{uuid.uuid4().hex}", password_hash=None, email=None, roles=("viewer", "analyst")
        )
    session = auth_store.create_session(user)
    yield session
    postgres.close_pools()


def test_postgres_session_and_csrf_query_budgets(pg_session):
    state = TimingState()
    with timing_context(state):
        assert auth_store.lookup_session(pg_session.session_token).user == pg_session.user
        assert state.counters["db_calls"] == 1
        state.counters.clear()
        assert auth_store.lookup_session(pg_session.session_token).user == pg_session.user
        assert state.counters.get("db_calls", 0) == 0
        assert auth_store.verify_csrf(pg_session.session_token, pg_session.csrf_token)
        assert state.counters["db_calls"] == 1
        state.counters.clear()
        refreshed = auth_store.refresh_session_csrf(pg_session.session_token)
        assert refreshed is not None and refreshed.user == pg_session.user
        assert state.counters["db_calls"] == 1
    assert not auth_store.verify_csrf(pg_session.session_token, pg_session.csrf_token)
    assert auth_store.verify_csrf(pg_session.session_token, refreshed.csrf_token)
    auth_store.revoke_session(pg_session.session_token)
    assert auth_store.lookup_session(pg_session.session_token) is None


def test_postgres_refresh_rejects_expired_session(pg_session):
    with auth_store._get_conn() as conn:
        conn.execute(
            "UPDATE auth_sessions SET expires_at = ? WHERE id = ?", ("2000-01-01T00:00:00Z", pg_session.session_id)
        )
        conn.commit()
    assert auth_store.refresh_session_csrf(pg_session.session_token) is None


def test_postgres_http_session_lifecycle(pg_session, monkeypatch):
    from typing import Annotated

    import bcrypt
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from api.main import _csrf_middleware
    from api.routers import auth
    from ontology.policy import Actor

    # Only the unrelated ontology audit sink is omitted from this auth-only schema.
    monkeypatch.setattr(auth, "emit_audit_event", lambda *args, **kwargs: None)
    with auth_store._get_conn() as conn:
        conn.execute(
            "UPDATE auth_users SET password_hash = ? WHERE id = ?",
            (bcrypt.hashpw(b"postgres-test-password", bcrypt.gensalt(4)).decode(), pg_session.user.id),
        )
        conn.commit()
    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    app.middleware("http")(_csrf_middleware)

    @app.api_route("/api/session-budget", methods=["GET", "POST"])
    def protected(actor: Annotated[Actor, Depends(auth.require_actor)]):
        return {"username": actor.actor_id, "roles": list(actor.roles)}

    client = TestClient(app)
    login = client.post(
        "/api/auth/login", json={"username": pg_session.user.username, "password": "postgres-test-password"}
    )
    assert login.status_code == 200
    session_token = client.cookies.get("__session")
    state = TimingState()
    with timing_context(state):
        assert client.get("/api/session-budget").status_code == 200
        assert state.counters["db_calls"] == 1
        state.counters.clear()
        assert client.get("/api/session-budget").status_code == 200
        assert state.counters.get("db_calls", 0) == 0
        refreshed = client.get("/api/auth/me")
        assert refreshed.status_code == 200 and refreshed.json()["roles"] == ["analyst", "viewer"]
        assert state.counters["db_calls"] == 1
        state.counters.clear()
        csrf = refreshed.json()["csrfToken"]
        assert client.post("/api/session-budget", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert state.counters["db_calls"] == 1
    assert client.post("/api/session-budget", headers={"X-CSRF-Token": login.json()["csrfToken"]}).status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    client.cookies.set("__session", session_token)
    assert client.get("/api/session-budget").status_code == 401


def test_email_index_migration_is_reversible_and_used(auth_database):
    migration = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "migrations/versions/20261021_0001_auth_email_lower_index.py")
    )
    engine = sa.create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(auth_database))
    try:
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            conn.exec_driver_sql(
                """
                INSERT INTO auth_users (id, username, email, active, created_at, updated_at)
                SELECT 'index-' || i, 'index-' || i, 'Member' || i || '@Example.com', true, 'now', 'now'
                FROM generate_series(1, 10000) AS i
                """
            )
            conn.exec_driver_sql("ANALYZE auth_users")
            plan = conn.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM auth_users WHERE lower(email) = 'member5000@example.com'"
            ).scalar_one()
            assert "ix_auth_users_email_lower" in str(plan)
            migration["downgrade"]()
            assert not conn.exec_driver_sql("SELECT to_regclass('ix_auth_users_email_lower')").scalar_one()
            migration["upgrade"]()
            assert conn.exec_driver_sql("SELECT to_regclass('ix_auth_users_email_lower')").scalar_one()
    finally:
        engine.dispose()
