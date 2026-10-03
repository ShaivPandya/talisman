"""Job submission and status endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import JobCreate, JobRead
from longaeva_app.db.models import Job
from longaeva_app.db.session import get_db
from longaeva_app.worker.handlers import public_job_types

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(body: JobCreate, session: Session = Depends(get_db)) -> Job:
    if body.type not in public_job_types():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown job type {body.type!r}. Known: {sorted(public_job_types())}",
        )
    job = Job(type=body.type, payload=body.payload, status="queued")
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: uuid.UUID, session: Session = Depends(get_db)) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("", response_model=list[JobRead])
def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[Job]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if status_filter is not None:
        stmt = stmt.where(Job.status == status_filter)
    return list(session.scalars(stmt).all())
