"""User-owned screener snapshots, retained until explicitly deleted."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from api.postgres import connect, use_postgres_state
from paths import PROJECT_ROOT

SQLITE_PATH = PROJECT_ROOT / "tmp" / "screener_runs.sqlite3"


@contextmanager
def _connection() -> Iterator[tuple[Any, str]]:
    if use_postgres_state():
        with connect() as conn, conn.transaction():
            yield conn, "%s"
        return
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(SQLITE_PATH, timeout=30)) as conn, conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS screener_runs ("
            "run_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, screen TEXT NOT NULL, "
            "name TEXT NOT NULL, created_at TEXT NOT NULL, snapshot_json TEXT NOT NULL)"
        )
        yield conn, "?"


def save(owner_id: str, screen: str, name: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    row = {
        "run_id": str(uuid4()),
        "screen": screen,
        "name": name,
        "created_at": datetime.now(UTC).isoformat(),
    }
    with _connection() as (conn, mark):
        conn.execute(
            "INSERT INTO screener_runs (run_id, owner_id, screen, name, created_at, snapshot_json) "
            f"VALUES ({', '.join([mark] * 6)})",
            (row["run_id"], owner_id, screen, name, row["created_at"], json.dumps(snapshot, allow_nan=False)),
        )
    return {**row, **snapshot}


def list_runs(owner_id: str, screen: str, *, limit: int, offset: int) -> list[dict[str, Any]]:
    with _connection() as (conn, mark):
        rows = conn.execute(
            "SELECT run_id, screen, name, created_at FROM screener_runs "
            f"WHERE owner_id={mark} AND screen={mark} ORDER BY created_at DESC, run_id DESC "
            f"LIMIT {mark} OFFSET {mark}",
            (owner_id, screen, limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]


def get(owner_id: str, run_id: str) -> dict[str, Any]:
    with _connection() as (conn, mark):
        row = conn.execute(
            "SELECT run_id, screen, name, created_at, snapshot_json FROM screener_runs "
            f"WHERE owner_id={mark} AND run_id={mark}",
            (owner_id, run_id),
        ).fetchone()
    if row is None:
        raise KeyError(run_id)
    result = dict(row)
    snapshot = json.loads(result.pop("snapshot_json"))
    return {**result, **snapshot}


def delete(owner_id: str, run_id: str) -> bool:
    with _connection() as (conn, mark):
        return (
            conn.execute(
                f"DELETE FROM screener_runs WHERE owner_id={mark} AND run_id={mark}",
                (owner_id, run_id),
            ).rowcount
            > 0
        )
