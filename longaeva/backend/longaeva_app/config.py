"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def normalize_database_url(url: str) -> str:
    """Rewrite postgresql:// to the psycopg3 SQLAlchemy dialect."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PACKAGE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = "postgresql://longaeva:longaeva@127.0.0.1:55432/longaeva"
    artifact_dir: Path = PACKAGE_ROOT / "var" / "artifacts"
    sec_user_agent: str = ""
    llm_provider: str = ""
    worker_id: str = "worker-1"
    worker_poll_interval_sec: float = 1.0
    worker_heartbeat_path: Path = Path("/tmp/longaeva-worker-heartbeat")

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_url(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_database_url(value)
        return value

    @field_validator("artifact_dir", mode="before")
    @classmethod
    def _default_artifact_dir(cls, value: object) -> object:
        if value is None or value == "":
            return PACKAGE_ROOT / "var" / "artifacts"
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
