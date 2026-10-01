"""Worker heartbeat helpers."""

from __future__ import annotations

import time
from pathlib import Path

from longaeva_app.worker.healthcheck import check_heartbeat_cli, heartbeat_is_fresh, write_heartbeat


def test_write_and_fresh_heartbeat(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    write_heartbeat(path)
    assert heartbeat_is_fresh(path, max_age_sec=5.0) is True
    assert check_heartbeat_cli(path, 5.0) == 0


def test_stale_heartbeat(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    path.write_text(f"{time.time() - 30:.6f}\n", encoding="utf-8")
    assert heartbeat_is_fresh(path, max_age_sec=5.0) is False
    assert check_heartbeat_cli(path, 5.0) == 1


def test_missing_heartbeat(tmp_path: Path) -> None:
    path = tmp_path / "missing"
    assert heartbeat_is_fresh(path, max_age_sec=5.0) is False
    assert check_heartbeat_cli(path, 5.0) == 1
