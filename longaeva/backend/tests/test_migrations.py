"""Alembic upgrade/downgrade round-trip."""

from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


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

    command.upgrade(cfg, "head")
    with test_engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        assert "job" in tables
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == "0001_job_queue"

    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    with test_engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == "0001_job_queue"
