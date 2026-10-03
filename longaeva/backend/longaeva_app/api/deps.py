"""FastAPI dependencies."""

from __future__ import annotations

from longaeva_app.config import get_settings
from longaeva_app.storage.local import LocalArtifactStore


def get_artifact_store() -> LocalArtifactStore:
    return LocalArtifactStore(get_settings().artifact_dir)
