"""Simulation code version and library fingerprints (LON-23 / FR-09)."""

from __future__ import annotations

import hashlib
import platform
from pathlib import Path
from typing import Any

import numpy as np

from longaeva_app import __version__

_PACKAGE_DIR = Path(__file__).resolve().parents[1]


def simulation_source_files() -> list[Path]:
    """Python sources that participate in the engine code-version hash."""
    roots = [
        _PACKAGE_DIR / "engine",
        _PACKAGE_DIR / "companies",
        _PACKAGE_DIR / "hashing.py",
    ]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
            continue
        files.extend(path for path in root.rglob("*.py") if path.is_file())
    return sorted({path.resolve() for path in files})


def files_digest(paths: list[Path], *, extra: bytes = b"") -> str:
    """SHA-256 of relative path names plus file bytes (optional extra for tests)."""
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        rel = path.resolve().relative_to(_PACKAGE_DIR).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    if extra:
        digest.update(extra)
    return digest.hexdigest()


def code_version() -> str:
    """Package version plus a truncated digest of simulation sources (no git)."""
    digest = files_digest(simulation_source_files())
    return f"{__version__}+{digest[:16]}"


def _blas_name() -> str:
    try:
        cfg = np.show_config(mode="dicts")
        blas = cfg.get("Build Dependencies", {}).get("blas", {})
        if isinstance(blas, dict):
            return str(blas.get("name") or "unknown")
    except Exception:  # noqa: BLE001 — fingerprinting must never fail a run
        return "unknown"
    return "unknown"


def _simd_flags() -> str:
    try:
        import numpy._core._multiarray_umath as umath  # type: ignore[import-not-found]

        features = getattr(umath, "__cpu_features__", {}) or {}
        return ",".join(sorted(name for name, enabled in features.items() if enabled))
    except Exception:  # noqa: BLE001
        return ""


def lib_versions() -> dict[str, Any]:
    """Library and machine fingerprint of the process that computed outputs."""
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "blas": _blas_name(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "simd": _simd_flags(),
    }


__all__ = [
    "code_version",
    "files_digest",
    "lib_versions",
    "simulation_source_files",
]
