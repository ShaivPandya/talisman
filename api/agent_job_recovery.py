"""Heartbeat leases and retryable transcript repair for durable chat turns."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any

from api import job_queue

logger = logging.getLogger(__name__)
_claim: ContextVar[tuple[str, str] | None] = ContextVar("agent_job_claim", default=None)


class AgentLeaseLost(RuntimeError):
    """A recovered worker may no longer publish output or change the transcript."""


def _seconds(name: str, default: float) -> float:
    try:
        return max(0.01, min(default, float(os.getenv(name) or default)))
    except ValueError:
        return default


def lease_seconds() -> float:
    return _seconds("AGENT_JOB_LEASE_SECONDS", 45.0)


def heartbeat_seconds() -> float:
    return min(_seconds("AGENT_JOB_HEARTBEAT_SECONDS", 10.0), lease_seconds() / 3)


def check_claim(row: Any) -> None:
    claim = _claim.get()
    if claim is not None and (not row or row["status"] != "running" or row["claimed_by"] != claim[1]):
        raise AgentLeaseLost("The chat worker no longer owns this turn")


def fence_transcript_write(conn: Any) -> None:
    """Lock the claim in the transcript transaction, excluding concurrent expiry."""
    claim = _claim.get()
    if claim is None:
        return
    if job_queue.postgres_jobs_enabled():
        row = conn.execute(
            "SELECT status, claimed_by FROM async_jobs WHERE job_id = ? FOR UPDATE", (claim[0],)
        ).fetchone()
    else:
        row = job_queue.get_job(claim[0])
    check_claim(row)


@contextmanager
def claimed_turn(row: dict[str, Any]) -> Iterator[bool]:
    """Renew on a separate thread, including while a provider or tool blocks."""
    owner = str(row.get("claimed_by") or "")
    if row.get("job_type") != "agent_chat_turn" or not owner.startswith(job_queue.AGENT_LEASE_PREFIX):
        yield True
        return
    job_id = str(row["job_id"])
    if not job_queue.renew_agent_job_lease(job_id, owner):
        yield False
        return
    stop = threading.Event()

    def heartbeat() -> None:
        while not stop.wait(heartbeat_seconds()):
            try:
                if not job_queue.renew_agent_job_lease(job_id, owner):
                    return
            except Exception:
                # Let the lease expire if the database stays unavailable. A transient
                # checkout error must not kill a healthy stream on its own.
                logger.warning("Chat heartbeat failed job_id=%s", job_id, exc_info=True)

    token = _claim.set((job_id, owner))
    thread = threading.Thread(target=heartbeat, name=f"chat-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield True
    finally:
        _claim.reset(token)
        stop.set()
        thread.join(timeout=1.0)


def recover_expired_turns(*, job_id: str | None = None, now: datetime | None = None) -> int:
    from api import memory_db
    from api.job_events import append_job_event
    from api.job_registry import get_job_spec

    cutoff = (now or datetime.now(UTC)) - timedelta(seconds=lease_seconds())
    job_queue.expire_agent_job_leases(cutoff, job_id=job_id, failed_ttl_s=get_job_spec("agent_chat_turn").failed_ttl_s)
    rows = job_queue.pending_agent_turn_recoveries(job_id=job_id)
    for row in rows:
        payload = row.get("payload_json") or {}
        session_id, turn_id = payload.get("session_id"), payload.get("client_turn_id")
        if session_id and turn_id:
            # No replacement content: preserve the last durable partial response.
            # Bypass the best-effort manager so a DB error leaves repair pending.
            memory_db.fail_turn(str(session_id), str(turn_id), status="failed", job_id=str(row["job_id"]))
        append_job_event(
            str(row["job_id"]),
            "error",
            {"message": row.get("error") or "Chat turn failed", "session_id": session_id},
            once=True,
        )
        job_queue.finish_agent_turn_recovery(str(row["job_id"]))
    return len(rows)


def start_recovery_loop(stop: threading.Event) -> threading.Thread:
    """Run in both the API and worker, independent of queued/running compute."""

    def recover() -> None:
        while not stop.is_set():
            try:
                recover_expired_turns()
            except Exception:
                logger.exception("Chat worker recovery failed; will retry")
            stop.wait(_seconds("AGENT_JOB_RECOVERY_INTERVAL_SECONDS", 5.0))

    thread = threading.Thread(target=recover, name="chat-lease-recovery", daemon=True)
    thread.start()
    return thread
