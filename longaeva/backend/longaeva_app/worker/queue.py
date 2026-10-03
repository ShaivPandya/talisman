"""Postgres-backed job queue operations."""

from __future__ import annotations

import logging
import traceback
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.config import get_settings
from longaeva_app.db.models import Job
from longaeva_app.runs.service import fail_orphaned_running_runs
from longaeva_app.storage.local import LocalArtifactStore
from longaeva_app.worker.handlers import HandlerContext, get_handler

logger = logging.getLogger(__name__)


def fail_orphaned_running_jobs(session_factory: sessionmaker[Session], worker_id: str) -> int:
    """Mark any jobs left in 'running' as failed (single-worker restart recovery)."""
    now = datetime.now(UTC)
    with session_factory() as session:
        result = session.execute(
            update(Job)
            .where(Job.status == "running")
            .values(
                status="failed",
                error="worker restarted",
                finished_at=now,
                worker_id=worker_id,
            )
        )
        session.commit()
        count = int(getattr(result, "rowcount", 0) or 0)
        if count:
            logger.warning("Marked %s orphaned running job(s) as failed", count)
    run_count = fail_orphaned_running_runs(session_factory)
    if run_count:
        logger.warning("Marked %s orphaned running run(s) as failed", run_count)
    return count


def claim_next_job(session_factory: sessionmaker[Session], worker_id: str) -> uuid.UUID | None:
    """Claim one queued job with SKIP LOCKED; returns its id or None."""
    now = datetime.now(UTC)
    with session_factory() as session:
        stmt = (
            select(Job)
            .where(Job.status == "queued")
            .order_by(Job.created_at, Job.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = session.scalars(stmt).first()
        if job is None:
            return None
        job.status = "running"
        job.started_at = now
        job.worker_id = worker_id
        job.attempts = (job.attempts or 0) + 1
        session.commit()
        return job.id


def execute_job(
    session_factory: sessionmaker[Session],
    job_id: uuid.UUID,
    worker_id: str,
    *,
    artifact_store: LocalArtifactStore | None = None,
) -> None:
    """Run the handler for a claimed job outside the claim transaction and persist the outcome."""
    started = datetime.now(UTC)
    store = artifact_store or LocalArtifactStore(get_settings().artifact_dir)

    with session_factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            logger.error("Claimed job %s missing", job_id)
            return
        job_type = job.type
        payload = dict(job.payload or {})
        handler = get_handler(job_type)

    if handler is None:
        finished = datetime.now(UTC)
        with session_factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error = f"No handler registered for job type {job_type!r}"
                job.finished_at = finished
                job.worker_id = worker_id
                session.commit()
        logger.error("Job %s failed: unknown type %s", job_id, job_type)
        return

    detached = Job(id=job_id, type=job_type, payload=payload, status="running")
    ctx = HandlerContext(
        job=detached,
        session_factory=session_factory,
        artifact_store=store,
        worker_id=worker_id,
    )

    try:
        result: dict[str, Any] = handler(ctx)
    except Exception as exc:  # noqa: BLE001 — job failures must be persisted
        finished = datetime.now(UTC)
        duration_sec = (finished - started).total_seconds()
        with session_factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.finished_at = finished
                job.worker_id = worker_id
                session.commit()
        logger.exception(
            "Job %s type=%s failed after %.3fs: %s\n%s",
            job_id,
            job_type,
            duration_sec,
            exc,
            traceback.format_exc(),
        )
        return

    finished = datetime.now(UTC)
    duration_sec = (finished - started).total_seconds()
    with session_factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "succeeded"
        job.result = result
        job.error = None
        job.finished_at = finished
        job.worker_id = worker_id
        session.commit()
    logger.info("Job %s type=%s succeeded in %.3fs", job_id, job_type, duration_sec)
