"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import Generator
from urllib.parse import urlparse, urlunparse

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.config import normalize_database_url
from longaeva_app.db.session import reset_engine

REQUIRE_DB = os.environ.get("LONGAEVA_REQUIRE_DB", "").strip() in {"1", "true", "yes"}
TEST_DB_NAME = os.environ.get("LONGAEVA_TEST_DB", "longaeva_test")
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

TRUNCATE_SQL = """
TRUNCATE TABLE
    evaluation_result,
    forecast,
    run,
    scenario,
    parameter_update_observation,
    parameter_update,
    parameter_set,
    mapping_rule,
    review_decision,
    observation,
    document_text,
    source_retrieval,
    source,
    job
RESTART IDENTITY CASCADE
"""


def _clear_settings_cache() -> None:
    from longaeva_app.config import get_settings

    get_settings.cache_clear()
    reset_engine()


def _admin_url() -> str:
    raw = os.environ.get("DATABASE_URL", "postgresql://longaeva:longaeva@127.0.0.1:55432/longaeva")
    url = normalize_database_url(raw)
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path="/postgres"))


def _test_url() -> str:
    raw = os.environ.get("DATABASE_URL", "postgresql://longaeva:longaeva@127.0.0.1:55432/longaeva")
    url = normalize_database_url(raw)
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{TEST_DB_NAME}"))


def _db_reachable() -> bool:
    try:
        engine = create_engine(_admin_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:  # noqa: BLE001
        return False


def _ensure_test_database() -> None:
    engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": TEST_DB_NAME},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    engine.dispose()


def _alembic_config(url: str) -> Config:
    cfg = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_ROOT, "migrations"))
    os.environ["DATABASE_URL"] = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return cfg


@pytest.fixture(scope="session")
def db_available() -> bool:
    ok = _db_reachable()
    if not ok and REQUIRE_DB:
        pytest.fail("Postgres is required (LONGAEVA_REQUIRE_DB=1) but unreachable")
    return ok


@pytest.fixture(scope="session")
def test_engine(db_available: bool) -> Generator[Engine, None, None]:
    if not db_available:
        pytest.skip("Postgres unreachable")
    _ensure_test_database()
    url = _test_url()
    cfg = _alembic_config(url)
    command.upgrade(cfg, "head")
    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        with test_engine.begin() as conn:
            conn.execute(text(TRUNCATE_SQL))


@pytest.fixture()
def client(test_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    url = test_engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url.replace("postgresql+psycopg://", "postgresql://", 1))
    _clear_settings_cache()

    # Import after env is set so settings/engine pick up the test DB.
    from longaeva_app.api.main import app
    from longaeva_app.db.session import get_db

    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def _override_db() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    _clear_settings_cache()
    with test_engine.begin() as conn:
        conn.execute(text(TRUNCATE_SQL))
