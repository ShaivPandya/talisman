"""Durable research runs with transactional leases and shared spending reservations."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from api.postgres import connect, use_postgres_state
from paths import PROJECT_ROOT

SQLITE_PATH: Path = PROJECT_ROOT / "tmp" / "company_research" / "runs.sqlite3"
MAX_COST_USD = 25.0
MAX_DURATION_S = 55 * 60
FINISH_RESERVE_USD = 7.0
FINISH_RESERVE_S = 15 * 60
LEASE_S = 180


class ResearchLimitReached(RuntimeError):
    pass


class ResearchLeaseLost(RuntimeError):
    pass


@contextmanager
def _connection() -> Iterator[tuple[Any, bool]]:
    if use_postgres_state():
        with connect() as conn, conn.transaction():
            yield conn, True
        return
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS company_research_runs "
            "(run_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, created_at REAL NOT NULL, state_json TEXT NOT NULL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS research_runs_ticker ON company_research_runs(ticker, created_at)")
        conn.execute("BEGIN IMMEDIATE")
        yield conn, False
        conn.commit()
    finally:
        conn.close()


def _decode(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    value = row["state_json"]
    return cast(dict[str, Any], json.loads(value) if isinstance(value, str) else value)


def get_run(run_id: str) -> dict[str, Any]:
    with _connection() as (conn, pg):
        mark = "%s" if pg else "?"
        state = _decode(
            conn.execute(f"SELECT state_json FROM company_research_runs WHERE run_id={mark}", (run_id,)).fetchone()
        )
    if state is None:
        raise KeyError(run_id)
    return state


def latest_runs(ticker: str) -> list[dict[str, Any]]:
    with _connection() as (conn, pg):
        mark = "%s" if pg else "?"
        rows = conn.execute(
            f"SELECT state_json FROM company_research_runs WHERE ticker={mark} ORDER BY created_at DESC LIMIT 30",
            (ticker,),
        ).fetchall()
    return [state for row in rows if (state := _decode(row)) is not None]


def mutate_run(run_id: str, change: Callable[[dict[str, Any]], None], *, owner: str | None = None) -> dict[str, Any]:
    with _connection() as (conn, pg):
        mark = "%s" if pg else "?"
        lock = " FOR UPDATE" if pg else ""
        state = _decode(
            conn.execute(
                f"SELECT state_json FROM company_research_runs WHERE run_id={mark}{lock}", (run_id,)
            ).fetchone()
        )
        if state is None:
            raise KeyError(run_id)
        if owner is not None and state.get("lease_owner") != owner:
            raise ResearchLeaseLost("Another worker owns this research run.")
        change(state)
        state["updated_at"] = time.time()
        value: Any = json.dumps(state, ensure_ascii=False)
        if pg:
            from psycopg.types.json import Jsonb

            value = Jsonb(state)
        conn.execute(f"UPDATE company_research_runs SET state_json={mark} WHERE run_id={mark}", (value, run_id))
    return state


def create_run(snapshot: dict[str, Any], *, apply: bool = True) -> tuple[dict[str, Any], bool]:
    """Serialize starts for one ticker; a retry must explicitly name its original run."""
    now = time.time()
    ticker = snapshot["ticker"]
    with _connection() as (conn, pg):
        mark = "%s" if pg else "?"
        if pg:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"company_research:{ticker}",))
        rows = conn.execute(
            f"SELECT state_json FROM company_research_runs WHERE ticker={mark} ORDER BY created_at DESC LIMIT 30",
            (ticker,),
        ).fetchall()
        for row in rows:
            existing = _decode(row)
            if existing and existing["status"] in {"queued", "running"} and existing["deadline"] > now:
                if not set(snapshot["kinds"]).issubset(existing["snapshot"]["kinds"]):
                    raise ResearchLimitReached(
                        "Research is already running for this company. Finish it before adding another report."
                    )
                return existing, False
        state = {
            "schema_version": 2,
            "run_id": str(uuid4()),
            "ticker": ticker,
            "snapshot": snapshot,
            "apply": apply,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "deadline": now + MAX_DURATION_S,
            "max_cost_usd": MAX_COST_USD,
            "charged_usd": 0.0,
            "calls": {},
            "steps": {},
            "reports": {
                kind: {"status": "queued", "phase": "planning", "report_available": False} for kind in snapshot["kinds"]
            },
            "lease_owner": None,
            "lease_until": 0.0,
            "job_id": None,
        }
        value: Any = json.dumps(state, ensure_ascii=False)
        if pg:
            from psycopg.types.json import Jsonb

            value = Jsonb(state)
        conn.execute(
            f"INSERT INTO company_research_runs(run_id, ticker, created_at, state_json) VALUES ({mark}, {mark}, {mark}, {mark})",
            (state["run_id"], ticker, now, value),
        )
    return state, True


def claim_run(run_id: str, owner: str) -> bool:
    claimed = False

    def change(state: dict[str, Any]) -> None:
        nonlocal claimed
        now = time.time()
        if state["status"] == "done" or state["deadline"] <= now:
            return
        if state.get("lease_owner") and state.get("lease_until", 0) > now and state["lease_owner"] != owner:
            return
        state.update(lease_owner=owner, lease_until=now + LEASE_S, status="running")
        state.pop("finished_at", None)
        claimed = True

    mutate_run(run_id, change)
    return claimed


def check_run(run_id: str, owner: str, *, gathering: bool = False) -> dict[str, Any]:
    def change(state: dict[str, Any]) -> None:
        remaining = state["deadline"] - time.time()
        if remaining <= (FINISH_RESERVE_S if gathering else 0):
            raise ResearchLimitReached(
                "Source gathering reached its time allowance; completed evidence is retained."
                if gathering
                else "The 55-minute research limit was reached; completed evidence is retained."
            )
        if state["status"] != "running":
            raise ResearchLeaseLost("Research run is no longer active.")
        state["lease_until"] = time.time() + LEASE_S

    return mutate_run(run_id, change, owner=owner)


def reserved_usd(state: dict[str, Any]) -> float:
    return float(sum(call["reserved_usd"] for call in state["calls"].values() if not call.get("settled")))


def reserve_call(
    run_id: str, owner: str, call_id: str, amount: float, *, gathering: bool, details: dict[str, Any]
) -> dict[str, Any]:
    def change(state: dict[str, Any]) -> None:
        if call_id in state["calls"]:
            return
        remaining = state["deadline"] - time.time()
        if remaining <= (FINISH_RESERVE_S if gathering else 0):
            raise ResearchLimitReached("Research time allowance reached; completed evidence is retained.")
        reserve = FINISH_RESERVE_USD if gathering else 0
        if state["charged_usd"] + reserved_usd(state) + amount > state["max_cost_usd"] - reserve:
            raise ResearchLimitReached("Research spending allowance reached; completed evidence is retained.")
        if sum(not call.get("settled") for call in state["calls"].values()) >= 2:
            raise ResearchLimitReached("Two research requests are already in flight. Resume after they finish.")
        state["calls"][call_id] = {**details, "reserved_usd": amount, "settled": False, "created_at": time.time()}
        state["lease_until"] = time.time() + LEASE_S

    return cast(dict[str, Any], mutate_run(run_id, change, owner=owner)["calls"][call_id])


def settle_call(
    run_id: str, owner: str, call_id: str, *, actual_usd: float | None, usage: dict[str, Any], status: str
) -> None:
    def change(state: dict[str, Any]) -> None:
        call = state["calls"][call_id]
        if call.get("settled"):
            return
        # Unknown provider outcomes remain fully charged. A retry never frees that liability.
        charge = call["reserved_usd"] if actual_usd is None else max(0.0, actual_usd)
        call.update(
            settled=True,
            charged_usd=charge,
            usage=usage,
            status=status,
            finished_at=time.time(),
            estimated=actual_usd is None,
        )
        state["charged_usd"] = round(state["charged_usd"] + charge, 8)

    mutate_run(run_id, change, owner=owner)


def budget_summary(state: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    return {
        "run_id": state["run_id"],
        "elapsed_seconds": max(0, int(min(now, state.get("finished_at", now)) - state["created_at"])),
        "remaining_seconds": max(0, int(state["deadline"] - now)),
        "max_seconds": MAX_DURATION_S,
        "charged_usd": round(state["charged_usd"], 4),
        "reserved_usd": round(reserved_usd(state), 4),
        "max_cost_usd": state["max_cost_usd"],
        "deadline": datetime.fromtimestamp(state["deadline"], UTC).isoformat(),
        "estimated": any(call.get("estimated") for call in state["calls"].values()),
    }


def resume_run(run_id: str) -> dict[str, Any]:
    def change(state: dict[str, Any]) -> None:
        now = time.time()
        if state["deadline"] <= now or state["charged_usd"] >= state["max_cost_usd"]:
            raise ResearchLimitReached("The original research allowance is exhausted.")
        if state["status"] in {"queued", "done"} or state.get("lease_until", 0) > now:
            return
        state.update(
            status="queued",
            lease_owner=None,
            lease_until=0,
            dispatch_generation=state.get("dispatch_generation", 0) + 1,
        )
        state.pop("finished_at", None)
        for report in state["reports"].values():
            if report["status"] != "done":
                report.update(status="queued", error=None)

    return mutate_run(run_id, change)
