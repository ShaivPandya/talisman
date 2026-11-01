"""Idea scan runs as JSON documents in state storage (GCS in production, local files otherwise).

A small index document lists every run so the digest page can show history
without opening each run.
"""

from __future__ import annotations

import io
import json
import secrets
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from api import state_storage
from paths import PROJECT_ROOT

if TYPE_CHECKING:
    import pandas as pd

LOCAL_ROOT: Path = PROJECT_ROOT / "data_cache" / "idea_scan" / "runs"
GCS_ROOT = "idea_scan/runs"
INDEX_NAME = "index.json"
INDEX_LIMIT = 200

_lock = threading.Lock()


class RunNotFound(KeyError):
    pass


def _paths(name: str) -> tuple[Path, str]:
    return LOCAL_ROOT / name, f"{GCS_ROOT}/{name}"


def _read_json(name: str) -> Any:
    local, remote = _paths(name)
    if not state_storage.exists_text(local, remote):
        return None
    return json.loads(state_storage.read_text(local, remote))


def _write_json(name: str, value: Any) -> None:
    local, remote = _paths(name)
    state_storage.write_text(
        local,
        remote,
        json.dumps(value, default=str, separators=(",", ":")),
        content_type="application/json",
    )


def new_run_id(now: datetime | None = None) -> str:
    when = now or datetime.now(UTC)
    return f"{when.strftime('%Y%m%dT%H%M%S%fZ')}-{secrets.token_hex(3)}"


def iso_week(now: datetime | None = None) -> str:
    year, week, _ = (now or datetime.now(UTC)).isocalendar()
    return f"{year}-W{week:02d}"


def _index_entry(run: dict[str, Any]) -> dict[str, Any]:
    stats = run.get("stats") or {}
    cost = run.get("cost") or {}
    return {
        "run_id": run["run_id"],
        "week": run.get("week"),
        "status": run.get("status"),
        "source": run.get("source"),
        "created_at": run.get("created_at"),
        "completed_at": run.get("completed_at"),
        "candidates": stats.get("candidates"),
        "reviewed": stats.get("reviewed"),
        "spent_usd": cost.get("spent_usd"),
        "limited": bool(run.get("limited")),
    }


def list_runs(limit: int = 52) -> list[dict[str, Any]]:
    index = _read_json(INDEX_NAME) or []
    rows = [row for row in index if isinstance(row, dict)]
    rows.sort(key=lambda row: str(row.get("run_id") or ""), reverse=True)
    return rows[:limit]


def get_run(run_id: str) -> dict[str, Any]:
    if not run_id or "/" in run_id or ".." in run_id:
        raise RunNotFound(run_id)
    value = _read_json(f"{run_id}.json")
    if not isinstance(value, dict):
        raise RunNotFound(run_id)
    return value


def save_run(run: dict[str, Any]) -> dict[str, Any]:
    run = {**run, "updated_at": datetime.now(UTC).isoformat()}
    with _lock:
        _write_json(f"{run['run_id']}.json", run)
        index = [row for row in (_read_json(INDEX_NAME) or []) if isinstance(row, dict)]
        index = [row for row in index if row.get("run_id") != run["run_id"]]
        index.append(_index_entry(run))
        index.sort(key=lambda row: str(row.get("run_id") or ""), reverse=True)
        _write_json(INDEX_NAME, index[:INDEX_LIMIT])
    return run


def mutate_run(run_id: str, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with _lock:
        run = get_run(run_id)
    change(run)
    return save_run(run)


def _frame_name(run_id: str) -> str:
    if not run_id or "/" in run_id or ".." in run_id:
        raise RunNotFound(run_id)
    return f"frames/{run_id}.parquet"


def save_frame(run_id: str, frame: pd.DataFrame) -> None:
    """Keep a run's factor frame so the Screeners page can rerun presets on it without refetching."""
    buffer = io.BytesIO()
    frame.to_parquet(buffer)
    local, remote = _paths(_frame_name(run_id))
    state_storage.write_bytes(local, remote, buffer.getvalue(), content_type="application/vnd.apache.parquet")


def load_frame(run_id: str) -> pd.DataFrame | None:
    import pandas as pd

    local, remote = _paths(_frame_name(run_id))
    if not state_storage.exists_text(local, remote):
        return None
    frame = pd.read_parquet(io.BytesIO(state_storage.read_bytes(local, remote)))
    frame["universes"] = frame["universes"].apply(lambda u: [str(x) for x in u] if u is not None else [])
    return frame


def latest_completed_run(*, before_run_id: str | None = None, full_only: bool = True) -> dict[str, Any] | None:
    """The newest completed run, optionally older than ``before_run_id``; limited test runs are skipped."""
    for row in list_runs(limit=INDEX_LIMIT):
        if row.get("status") != "completed":
            continue
        if before_run_id and str(row.get("run_id")) >= before_run_id:
            continue
        if full_only and row.get("limited"):
            continue
        try:
            return get_run(str(row["run_id"]))
        except RunNotFound:
            continue
    return None
