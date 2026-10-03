"""Run submit, status, results, replay, and forecast-archive endpoints (LON-23)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.deps import get_artifact_store
from longaeva_app.api.schemas import (
    ForecastArchiveRequest,
    ForecastRead,
    ReplayReport,
    RunCreate,
    RunRead,
    RunResultSummary,
)
from longaeva_app.db.models import Run
from longaeva_app.db.session import get_db
from longaeva_app.runs.errors import RunError
from longaeva_app.runs.forecasts import archive_forecasts
from longaeva_app.runs.service import replay_run, submit_run
from longaeva_app.storage.local import LocalArtifactStore

router = APIRouter(prefix="/runs", tags=["runs"])


def _raise(exc: RunError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
def create_run(body: RunCreate, session: Session = Depends(get_db)) -> Run:
    try:
        run = submit_run(
            session,
            scenario_id=body.scenario_id,
            cutoff_ts=body.cutoff_ts,
            seed=body.seed,
            n_paths=body.n_paths,
            n_quarters=body.n_quarters,
            switches=body.switches,
        )
        session.commit()
        session.refresh(run)
        return run
    except RunError as exc:
        session.rollback()
        _raise(exc)
        raise  # pragma: no cover


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


@router.get("/{run_id}/results", response_model=list[RunResultSummary])
def get_run_results(run_id: uuid.UUID, session: Session = Depends(get_db)) -> list[RunResultSummary]:
    row = session.get(Run, run_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if row.status != "succeeded":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run has not succeeded")
    if not isinstance(row.summary, list):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run is missing a summary")
    return [RunResultSummary.model_validate(item) for item in row.summary]


@router.post("/{run_id}/replay", response_model=ReplayReport)
def replay_saved_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_db),
    store: LocalArtifactStore = Depends(get_artifact_store),
) -> ReplayReport:
    try:
        payload = replay_run(session, run_id, artifact_store=store)
        return ReplayReport.model_validate(payload)
    except RunError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/{run_id}/forecasts", response_model=list[ForecastRead], status_code=status.HTTP_201_CREATED)
def archive_run_forecasts(
    run_id: uuid.UUID,
    body: ForecastArchiveRequest,
    session: Session = Depends(get_db),
) -> list[ForecastRead]:
    try:
        rows = archive_forecasts(session, run_id, kind=body.kind)
        session.commit()
        return [ForecastRead.model_validate(row, from_attributes=True) for row in rows]
    except RunError as exc:
        session.rollback()
        _raise(exc)
        raise  # pragma: no cover
