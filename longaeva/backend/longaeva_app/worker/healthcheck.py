"""Worker heartbeat file for container healthchecks."""

from __future__ import annotations

import time
from pathlib import Path


def write_heartbeat(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{time.time():.6f}\n", encoding="utf-8")


def heartbeat_is_fresh(path: Path, max_age_sec: float) -> bool:
    if not path.is_file():
        return False
    try:
        stamp = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return (time.time() - stamp) <= max_age_sec


def check_heartbeat_cli(path: Path, max_age_sec: float) -> int:
    """Exit 0 if fresh, 1 otherwise (used as Docker HEALTHCHECK)."""
    return 0 if heartbeat_is_fresh(path, max_age_sec) else 1
