"""Local artifact store under ARTIFACT_DIR (adapted from Talisman state_storage patterns)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath

from longaeva_app.hashing import sha256_hex


class ArtifactStoreError(ValueError):
    """Invalid artifact key or store operation."""


class LocalArtifactStore:
    """Filesystem artifact store with content-addressed originals and explicit keys.

    Keys are relative POSIX paths only. Absolute paths and ``..`` segments are rejected
    so database rows never store host-specific absolute paths.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve_key(self, key: str) -> Path:
        """Map a relative POSIX key to an absolute path under ``root``."""
        normalized = self._normalize_key(key)
        path = (self.root / Path(*PurePosixPath(normalized).parts)).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ArtifactStoreError(f"Key escapes artifact root: {key!r}") from exc
        return path

    def exists(self, key: str) -> bool:
        return self.resolve_key(key).is_file()

    def read_bytes(self, key: str) -> bytes:
        path = self.resolve_key(key)
        if not path.is_file():
            raise FileNotFoundError(f"Artifact not found: {key}")
        return path.read_bytes()

    def write_bytes(self, key: str, data: bytes, *, overwrite: bool = False) -> str:
        """Write ``data`` atomically to ``key``. Returns the normalized relative key."""
        normalized = self._normalize_key(key)
        path = self.resolve_key(normalized)
        if path.exists() and not overwrite:
            raise ArtifactStoreError(f"Artifact already exists: {normalized}")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(path, data)
        return normalized

    def put_original(self, data: bytes) -> tuple[str, str]:
        """Store bytes under ``originals/<ab>/<sha256>``. Returns ``(key, content_hash)``."""
        digest = sha256_hex(data)
        key = f"originals/{digest[:2]}/{digest}"
        path = self.resolve_key(key)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(path, data)
        return key, digest

    def write_once(self, key: str, data: bytes) -> str:
        """Write under an explicit key (``runs/`` or ``reports/``) without overwrite."""
        normalized = self._normalize_key(key)
        if not (normalized.startswith("runs/") or normalized.startswith("reports/")):
            raise ArtifactStoreError(f"write_once requires runs/ or reports/ prefix, got {normalized!r}")
        return self.write_bytes(normalized, data, overwrite=False)

    @staticmethod
    def _normalize_key(key: str) -> str:
        if not key or key.strip() != key:
            raise ArtifactStoreError(f"Invalid artifact key: {key!r}")
        if key.startswith("/") or key.startswith("\\"):
            raise ArtifactStoreError(f"Absolute paths are not allowed: {key!r}")
        posix = PurePosixPath(key.replace("\\", "/"))
        if posix.is_absolute() or ".." in posix.parts or any(part == "" for part in posix.parts):
            raise ArtifactStoreError(f"Invalid artifact key: {key!r}")
        if posix.parts and posix.parts[0] in {".", ".."}:
            raise ArtifactStoreError(f"Invalid artifact key: {key!r}")
        return posix.as_posix()

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
