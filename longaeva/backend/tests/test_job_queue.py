"""Job queue claim/execute and orphan recovery."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.db.models import Job
from longaeva_app.worker.queue import claim_next_job, execute_job, fail_orphaned_running_jobs


@pytest.mark.db
def test_claim_and_execute_ping(db_session: Session, test_engine: Engine) -> None:
    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    job = Job(type="ping", payload={"message": "hello"}, status="queued")
    db_session.add(job)
    db_session.commit()
    job_id = job.id

    claimed = claim_next_job(factory, "test-worker")
    assert claimed == job_id

    execute_job(factory, job_id, "test-worker")

    db_session.expire_all()
    done = db_session.get(Job, job_id)
    assert done is not None
    assert done.status == "succeeded"
    assert done.result == {"message": "hello", "job_id": str(job_id)}
    assert done.worker_id == "test-worker"
    assert done.finished_at is not None


@pytest.mark.db
def test_unknown_handler_fails(db_session: Session, test_engine: Engine) -> None:
    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    job = Job(type="no_such_handler", payload={}, status="queued")
    db_session.add(job)
    db_session.commit()
    job_id = job.id

    claimed = claim_next_job(factory, "test-worker")
    assert claimed == job_id
    execute_job(factory, job_id, "test-worker")

    db_session.expire_all()
    done = db_session.get(Job, job_id)
    assert done is not None
    assert done.status == "failed"
    assert done.error is not None
    assert "No handler" in done.error


@pytest.mark.db
def test_fail_orphaned_running_jobs(db_session: Session, test_engine: Engine) -> None:
    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    orphan = Job(
        type="ping",
        payload={},
        status="running",
        started_at=datetime.now(UTC),
        worker_id="old-worker",
    )
    db_session.add(orphan)
    db_session.commit()
    orphan_id = orphan.id

    count = fail_orphaned_running_jobs(factory, "new-worker")
    assert count == 1

    db_session.expire_all()
    row = db_session.get(Job, orphan_id)
    assert row is not None
    assert row.status == "failed"
    assert row.error == "worker restarted"
