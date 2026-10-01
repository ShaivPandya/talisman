"""Tests for settings and URL normalization."""

from __future__ import annotations

import pytest

from longaeva_app.config import Settings, normalize_database_url


def test_normalize_database_url_postgresql() -> None:
    assert normalize_database_url("postgresql://u:p@localhost:5432/db") == "postgresql+psycopg://u:p@localhost:5432/db"


def test_normalize_database_url_postgres_scheme() -> None:
    assert normalize_database_url("postgres://u:p@localhost/db") == "postgresql+psycopg://u:p@localhost/db"


def test_normalize_database_url_already_psycopg() -> None:
    url = "postgresql+psycopg://u:p@localhost/db"
    assert normalize_database_url(url) == url


def test_settings_normalizes_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from longaeva_app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://longaeva:longaeva@db:5432/longaeva")
    monkeypatch.delenv("ARTIFACT_DIR", raising=False)
    settings = Settings()
    assert settings.database_url.startswith("postgresql+psycopg://")
    get_settings.cache_clear()
