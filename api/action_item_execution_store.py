"""Durable action-item attempts, fenced leases, and shared budget reservations."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from api.postgres import connect, use_postgres_state
from paths import PROJECT_ROOT

SQLITE_PATH = PROJECT_ROOT / "tmp" / "action_item_executions.sqlite3"
LEASE_SECONDS = 120
ACTIVE = {"queued", "running"}


class ExecutionConflict(ValueError):
    pass


@contextmanager
def connection() -> Iterator[tuple[Any, bool]]:
    if use_postgres_state():
        with connect() as conn, conn.transaction():
            yield conn, True
        return
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(SQLITE_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS action_item_executions "
            "(run_id TEXT PRIMARY KEY, item_id TEXT NOT NULL, owner_id TEXT NOT NULL, "
            "created_at REAL NOT NULL, state_json TEXT NOT NULL)"
        )
        conn.execute("BEGIN IMMEDIATE")
        yield conn, False


def decode(row: Any) -> dict[str, Any]:
    value = row["state_json"]
    return json.loads(value) if isinstance(value, str) else dict(value)


def _save(conn: Any, pg: bool, state: dict[str, Any]) -> None:
    value: Any = json.dumps(state, ensure_ascii=False)
    if pg:
        from psycopg.types.json import Jsonb

        value = Jsonb(state)
    mark = "%s" if pg else "?"
    conn.execute(f"UPDATE action_item_executions SET state_json={mark} WHERE run_id={mark}", (value, state["run_id"]))


def runs(owner_id: str, item_id: str | None = None) -> list[dict[str, Any]]:
    with connection() as (conn, pg):
        mark = "%s" if pg else "?"
        where, args = f"owner_id={mark}", [owner_id]
        if item_id:
            where += f" AND item_id={mark}"
            args.append(item_id)
        return [
            decode(row)
            for row in conn.execute(
                f"SELECT state_json FROM action_item_executions WHERE {where} ORDER BY created_at DESC", args
            ).fetchall()
        ]


def get(run_id: str) -> dict[str, Any]:
    with connection() as (conn, pg):
        mark = "%s" if pg else "?"
        row = conn.execute(f"SELECT state_json FROM action_item_executions WHERE run_id={mark}", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return decode(row)


def mutate(run_id: str, change: Callable[[dict[str, Any]], None], *, lease: str | None = None) -> dict[str, Any]:
    with connection() as (conn, pg):
        mark, lock = ("%s", " FOR UPDATE") if pg else ("?", "")
        row = conn.execute(
            f"SELECT state_json FROM action_item_executions WHERE run_id={mark}{lock}", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        state = decode(row)
        if lease and (
            state.get("lease") != lease or state["status"] != "running" or state.get("lease_until", 0) <= time.time()
        ):
            raise ExecutionConflict("This worker no longer owns the execution.")
        change(state)
        state["updated_at"] = time.time()
        _save(conn, pg, state)
        return state


def create(snapshot: dict[str, Any], limits: dict[str, Any], *, automatic: bool = False) -> tuple[dict[str, Any], bool]:
    now = time.time()
    owner_id, item_id = snapshot["actor"]["actor_id"], snapshot["item_id"]
    with connection() as (conn, pg):
        mark = "%s" if pg else "?"
        if pg:
            # Serialize both per-item starts and the owner's daily/concurrency reservations.
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"action_items:{owner_id}",))
        existing = [
            decode(row)
            for row in conn.execute(
                f"SELECT state_json FROM action_item_executions WHERE owner_id={mark} ORDER BY created_at DESC",
                (owner_id,),
            ).fetchall()
        ]
        previous = next((s for s in existing if s["item_id"] == item_id), None)
        if previous:
            return previous, False
        today = datetime.now(UTC).date()
        daily = sum(
            s["max_cost_usd"]
            for s in existing
            if today.isoformat()
            in s.get("budget_dates", [datetime.fromtimestamp(s["created_at"], UTC).date().isoformat()])
        )
        if daily + limits["max_cost_usd"] > limits["daily_budget_usd"]:
            raise ExecutionConflict(
                "The daily research budget is fully reserved. Try again tomorrow or adjust the limit."
            )
        if sum(s["status"] in ACTIVE for s in existing) >= limits["max_concurrent"]:
            raise ExecutionConflict("The research concurrency limit has been reached.")
        state = {
            "run_id": str(uuid4()),
            "item_id": item_id,
            "owner_id": owner_id,
            "snapshot": snapshot,
            "status": "queued",
            "phase": "queued",
            "automatic": automatic,
            "created_at": now,
            "updated_at": now,
            "deadline": now + 20 * 60,
            "max_cost_usd": limits["max_cost_usd"],
            "charged_usd": 0.0,
            "calls": {},
            "steps": {},
            "approval_ids": [],
            "completion_approval_id": None,
            "lease": None,
            "lease_until": 0,
            "generation": 0,
            "job_id": None,
            "error": None,
            "budget_dates": [today.isoformat()],
        }
        value: Any = json.dumps(state)
        if pg:
            from psycopg.types.json import Jsonb

            value = Jsonb(state)
        conn.execute(
            f"INSERT INTO action_item_executions VALUES ({mark}, {mark}, {mark}, {mark}, {mark})",
            (state["run_id"], item_id, owner_id, now, value),
        )
        return state, True


def resume(
    run_id: str, limits: dict[str, Any], validate: Callable[[dict[str, Any]], None], *, instructions: str | None = None
) -> dict[str, Any]:
    state = get(run_id)
    with connection() as (conn, pg):
        mark = "%s" if pg else "?"
        if pg:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"action_items:{state['owner_id']}",)
            )
        all_runs = [
            decode(row)
            for row in conn.execute(
                f"SELECT state_json FROM action_item_executions WHERE owner_id={mark}", (state["owner_id"],)
            ).fetchall()
        ]
        state = next(s for s in all_runs if s["run_id"] == run_id)
        validate(state)
        allowed = {"failed", "cancelled", "needs_input"} if instructions else {"failed", "cancelled"}
        if state["status"] not in allowed:
            raise ExecutionConflict("Only interrupted executions can be retried.")
        if state["charged_usd"] >= state["max_cost_usd"]:
            raise ExecutionConflict("This execution has used its research budget.")
        if sum(s["status"] in ACTIVE for s in all_runs) >= limits["max_concurrent"]:
            raise ExecutionConflict("The research concurrency limit has been reached.")
        today = datetime.now(UTC).date().isoformat()
        if today not in state["budget_dates"]:
            reserved = sum(s["max_cost_usd"] for s in all_runs if today in s["budget_dates"])
            if reserved + state["max_cost_usd"] > limits["daily_budget_usd"]:
                raise ExecutionConflict("The daily research budget is fully reserved.")
            state["budget_dates"].append(today)
        if instructions:
            state.setdefault("history", []).append(
                {
                    "generation": state["generation"],
                    "steps": state["steps"],
                    "calls": state["calls"],
                    "approval_ids": state["approval_ids"],
                    "completion_approval_id": state["completion_approval_id"],
                    "error": state["error"],
                }
            )
            state["snapshot"]["clarification"] = instructions
            state.update(steps={}, calls={}, approval_ids=[], completion_approval_id=None)
            state.pop("target_hash", None)
        else:
            for step, call in list(state["calls"].items()):
                if call.get("settled") and call.get("status") in {"failed", "cancelled", "incomplete"}:
                    state.setdefault("call_history", []).append({"step": step, **call})
                    del state["calls"][step]
        state.update(
            status="queued",
            phase="queued",
            error=None,
            lease=None,
            lease_until=0,
            deadline=time.time() + 20 * 60,
            generation=state["generation"] + 1,
            updated_at=time.time(),
        )
        _save(conn, pg, state)
        return state


def claim(run_id: str, lease: str) -> dict[str, Any]:
    def change(state: dict[str, Any]) -> None:
        if state["status"] not in ACTIVE or (state.get("lease") and state["lease_until"] > time.time()):
            raise ExecutionConflict("Execution is already claimed or has finished.")
        if state["deadline"] <= time.time():
            raise ExecutionConflict("Execution reached its time allowance. Retry to continue retained work.")
        state.update(status="running", lease=lease, lease_until=time.time() + LEASE_SECONDS)

    return mutate(run_id, change)


def check(run_id: str, lease: str) -> dict[str, Any]:
    def change(state: dict[str, Any]) -> None:
        if state["deadline"] <= time.time():
            raise ExecutionConflict("Execution reached its 20-minute allowance; completed work is retained.")
        state["lease_until"] = time.time() + LEASE_SECONDS

    return mutate(run_id, change, lease=lease)
