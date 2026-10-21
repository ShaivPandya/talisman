"""Durable event storage for replayable async job output."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from api.job_queue import get_job, postgres_jobs_enabled
from api.postgres import connect, retry_read

_memory_events: dict[str, list[dict[str, Any]]] = {}
_memory_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(UTC)


def _row_to_event(row: Any) -> dict[str, Any]:
    return {
        "seq": int(row["seq"]),
        "event_type": str(row["event_type"]),
        "payload": row["payload_json"] if row["payload_json"] is not None else {},
        "created_at": row["created_at"].isoformat()
        if hasattr(row["created_at"], "isoformat")
        else str(row["created_at"]),
    }


def append_job_event(job_id: str, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append one event to a job's replay log and return the stored event."""
    body = payload or {}
    now = _now()
    if not postgres_jobs_enabled():
        with _memory_lock:
            events = _memory_events.setdefault(job_id, [])
            event: dict[str, Any] = {
                "seq": len(events) + 1,
                "event_type": event_type,
                "payload": body,
                "created_at": now.isoformat(),
            }
            events.append(event)
        from api.job_event_notifications import publish_local_job_event

        publish_local_job_event(job_id, int(event["seq"]))
        return dict(event)

    from psycopg.types.json import Jsonb

    with connect() as conn:
        # Lock the parent job row so concurrent API cancellation and worker
        # writes cannot race on the next sequence number.
        conn.execute("SELECT job_id FROM async_jobs WHERE job_id = %s FOR UPDATE", (job_id,)).fetchone()
        row = conn.execute(
            """
            WITH inserted AS (
                INSERT INTO async_job_events (job_id, seq, event_type, payload_json, created_at)
                SELECT %s, COALESCE(MAX(seq), 0) + 1, %s, %s, %s
                FROM async_job_events
                WHERE job_id = %s
                RETURNING seq, event_type, payload_json, created_at
            )
            SELECT seq, event_type, payload_json, created_at,
                   pg_notify('talisman_job_events', json_build_array(%s::text, seq)::text)
            FROM inserted
            """,
            (job_id, event_type, Jsonb(body), now, job_id, job_id),
        ).fetchone()
        conn.commit()
        return _row_to_event(row)


def list_job_events(job_id: str, *, after_seq: int = 0, limit: int = 500) -> list[dict[str, Any]]:
    """Return events with sequence numbers greater than ``after_seq``."""
    after = max(0, int(after_seq))
    capped_limit = max(1, min(int(limit), 1000))
    if not postgres_jobs_enabled():
        with _memory_lock:
            events = _memory_events.get(job_id, [])
            return [dict(event) for event in events if int(event["seq"]) > after][:capped_limit]

    def _read() -> list[dict[str, Any]]:
        with connect(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT seq, event_type, payload_json, created_at
                FROM async_job_events
                WHERE job_id = %s AND seq > %s
                ORDER BY seq ASC
                LIMIT %s
                """,
                (job_id, after, capped_limit),
            ).fetchall()
            return [_row_to_event(row) for row in rows]

    return retry_read(_read)


def read_job_events_snapshot(
    job_id: str, *, after_seq: int = 0, limit: int = 500
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Read status and a replay page in one statement, omitting request blobs.

    Active jobs don't transfer result blobs either. The small payload projection
    retains session identity and the actor used by optional read auditing.
    """
    after = max(0, int(after_seq))
    capped_limit = max(1, min(int(limit), 1000))
    if not postgres_jobs_enabled():
        row = get_job(job_id)
        if row is None:
            return None, []
        payload = row.get("payload_json") or {}
        snapshot = {
            key: row.get(key)
            for key in (
                "job_id",
                "job_type",
                "status",
                "error",
                "progress_json",
                "cache_key",
                "created_at",
                "started_at",
            )
        }
        snapshot["payload_json"] = {key: payload.get(key) for key in ("session_id", "actor")}
        snapshot["result_json"] = row.get("result_json") if row.get("status") == "completed" else None
        return snapshot, list_job_events(job_id, after_seq=after, limit=capped_limit)

    def _read() -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        with connect(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT j.job_id, j.job_type, j.status, j.error, j.progress_json,
                       j.cache_key, j.created_at, j.started_at,
                       jsonb_build_object('session_id', j.payload_json->'session_id',
                                          'actor', j.payload_json->'actor') AS payload_json,
                       CASE WHEN j.status = 'completed' THEN j.result_json END AS result_json,
                       e.seq, e.event_type, e.payload_json AS event_payload_json,
                       e.created_at AS event_created_at
                FROM async_jobs AS j
                LEFT JOIN LATERAL (
                    SELECT seq, event_type, payload_json, created_at
                    FROM async_job_events
                    WHERE job_id = j.job_id AND seq > %s
                    ORDER BY seq ASC
                    LIMIT %s
                ) AS e ON TRUE
                WHERE j.job_id = %s
                ORDER BY e.seq ASC
                """,
                (after, capped_limit, job_id),
            ).fetchall()
        if not rows:
            return None, []
        snapshot = {
            key: value
            for key, value in rows[0].items()
            if key not in {"seq", "event_type", "event_payload_json", "event_created_at"}
        }
        events = [
            _row_to_event(
                {
                    "seq": row["seq"],
                    "event_type": row["event_type"],
                    "payload_json": row["event_payload_json"],
                    "created_at": row["event_created_at"],
                }
            )
            for row in rows
            if row["seq"] is not None
        ]
        return snapshot, events

    return retry_read(_read)


def clear_memory_events() -> None:
    """Clear local fallback events. Used by tests and local cache invalidation."""
    with _memory_lock:
        _memory_events.clear()
    from api.job_event_notifications import clear_local_job_event_watches

    clear_local_job_event_watches()
