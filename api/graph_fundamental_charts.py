"""User-owned chart layouts, using the screener-runs storage convention."""

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

SQLITE_PATH = PROJECT_ROOT / "tmp" / "graph_fundamental_charts.sqlite3"


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
            "CREATE TABLE IF NOT EXISTS graph_fundamental_charts (chart_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, state_json TEXT NOT NULL)"
        )
        yield conn, "?"


def _decode(row) -> dict:
    result = dict(row)
    result["state"] = json.loads(result.pop("state_json"))
    result.pop("owner_id", None)
    return result


def save(owner: str, name: str, state: dict, chart_id: str | None = None) -> dict:
    now = datetime.now(UTC).isoformat()
    encoded = json.dumps(state, allow_nan=False, separators=(",", ":"))
    with _connection() as (conn, mark):
        if chart_id:
            changed = conn.execute(
                f"UPDATE graph_fundamental_charts SET name={mark}, state_json={mark}, updated_at={mark} WHERE chart_id={mark} AND owner_id={mark}",
                (name, encoded, now, chart_id, owner),
            ).rowcount
            if not changed:
                raise KeyError(chart_id)
        else:
            chart_id = str(uuid4())
            conn.execute(
                f"INSERT INTO graph_fundamental_charts (chart_id, owner_id, name, created_at, updated_at, state_json) VALUES ({', '.join([mark] * 6)})",
                (chart_id, owner, name, now, now, encoded),
            )
        row = conn.execute(
            f"SELECT * FROM graph_fundamental_charts WHERE chart_id={mark} AND owner_id={mark}", (chart_id, owner)
        ).fetchone()
        return _decode(row)


def list_charts(owner: str, limit: int, offset: int) -> list[dict]:
    with _connection() as (conn, mark):
        return [
            dict(row)
            for row in conn.execute(
                f"SELECT chart_id, name, created_at, updated_at FROM graph_fundamental_charts WHERE owner_id={mark} ORDER BY updated_at DESC, chart_id DESC LIMIT {mark} OFFSET {mark}",
                (owner, limit, offset),
            ).fetchall()
        ]


def get(owner: str, chart_id: str) -> dict:
    with _connection() as (conn, mark):
        row = conn.execute(
            f"SELECT * FROM graph_fundamental_charts WHERE chart_id={mark} AND owner_id={mark}", (chart_id, owner)
        ).fetchone()
        if row is None:
            raise KeyError(chart_id)
        return _decode(row)


def delete(owner: str, chart_id: str) -> bool:
    with _connection() as (conn, mark):
        changed = conn.execute(
            f"DELETE FROM graph_fundamental_charts WHERE chart_id={mark} AND owner_id={mark}", (chart_id, owner)
        ).rowcount
        return bool(changed > 0)
