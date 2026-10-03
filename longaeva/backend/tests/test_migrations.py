"""Alembic upgrade/downgrade round-trip and model/metadata drift check."""

from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from longaeva_app.db import models as _models  # noqa: F401 — register models
from longaeva_app.db.base import Base

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HEAD_REVISION = "0004_run_replay"
PREV_REVISION = "0001_job_queue"

CORE_TABLES = {
    "source",
    "source_retrieval",
    "document_text",
    "observation",
    "review_decision",
    "mapping_rule",
    "parameter_set",
    "parameter_update",
    "parameter_update_observation",
    "scenario",
    "run",
    "forecast",
    "evaluation_result",
}


def _cfg(url: str) -> Config:
    cfg = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_ROOT, "migrations"))
    os.environ["DATABASE_URL"] = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return cfg


@pytest.mark.db
def test_migrations_upgrade_downgrade_upgrade(test_engine: Engine) -> None:
    url = test_engine.url.render_as_string(hide_password=False)
    cfg = _cfg(url)

    command.downgrade(cfg, "base")
    with test_engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        assert "job" not in tables
        assert not CORE_TABLES.intersection(tables)

    command.upgrade(cfg, "head")
    with test_engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        assert "job" in tables
        assert CORE_TABLES.issubset(tables)
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == HEAD_REVISION

    command.downgrade(cfg, PREV_REVISION)
    with test_engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        assert "job" in tables
        assert not CORE_TABLES.intersection(tables)
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == PREV_REVISION

    command.upgrade(cfg, "head")
    with test_engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == HEAD_REVISION


@pytest.mark.db
def test_models_match_migrated_schema(test_engine: Engine) -> None:
    with test_engine.connect() as conn:
        context = MigrationContext.configure(conn)
        diffs = compare_metadata(context, Base.metadata)
    # Filter out noise that is equivalent (e.g. server defaults formatting).
    meaningful = [diff for diff in diffs if diff[0] not in {"remove_index"}]
    assert meaningful == [], f"Model/metadata drift detected: {meaningful}"
