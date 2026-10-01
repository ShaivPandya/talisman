"""Read-only run endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import RunRead
from longaeva_app.db.models import Run
from longaeva_app.db.session import get_db

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunRead])
def list_runs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[Run]:
    stmt = select(Run).order_by(Run.created_at.desc()).limit(limit)
    if status_filter is not None:
        stmt = stmt.where(Run.status == status_filter)
    return list(session.scalars(stmt).all())


@router.get("/{run_id}", response_model=RunRead)
def get_run(run_id: uuid.UUID, session: Session = Depends(get_db)) -> Run:
    row = session.get(Run, run_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return row
