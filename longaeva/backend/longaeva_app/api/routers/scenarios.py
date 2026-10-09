"""Scenario definitions, paired runs, comparison, and attribution."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.deps import get_artifact_store
from longaeva_app.api.schemas import (
    AttributionRead,
    ComparisonRead,
    PairRunsCreate,
    RunRead,
    ScenarioCreate,
    ScenarioRead,
)
from longaeva_app.db.models import Run, Scenario
from longaeva_app.db.session import get_db
from longaeva_app.runs.errors import RunError
from longaeva_app.scenarios.errors import ScenarioError
from longaeva_app.scenarios.service import (
    attribute_saved_runs,
    compare_saved_runs,
    create_scenario,
    submit_pair_runs,
)
from longaeva_app.storage.local import LocalArtifactStore

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def _raise(exc: ScenarioError | RunError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("", response_model=list[ScenarioRead])
def list_scenarios(
    company: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[Scenario]:
    stmt = select(Scenario).order_by(Scenario.created_at.desc()).limit(limit)
    if company is not None:
        stmt = stmt.where(Scenario.company == company)
    return list(session.scalars(stmt).all())


@router.post("", response_model=ScenarioRead, status_code=status.HTTP_201_CREATED)
def post_scenario(body: ScenarioCreate, session: Session = Depends(get_db)) -> Scenario:
    try:
        scenario = create_scenario(
            session,
            company=body.company,
            name=body.name,
            parameter_set_id=body.parameter_set_id,
            interventions=[item.model_dump(mode="json") for item in body.interventions],
            pair_group_id=body.pair_group_id,
            parameter_overrides=body.parameter_overrides,
        )
        session.commit()
        session.refresh(scenario)
        return scenario
    except ScenarioError as exc:
        session.rollback()
        _raise(exc)
        raise  # pragma: no cover


@router.post("/pair-runs", response_model=list[RunRead], status_code=status.HTTP_202_ACCEPTED)
def post_pair_runs(body: PairRunsCreate, session: Session = Depends(get_db)) -> list[Run]:
    try:
        runs = submit_pair_runs(
            session,
            scenario_ids=body.scenario_ids,
            baseline_scenario_id=body.baseline_scenario_id,
            cutoff_ts=body.cutoff_ts,
            seed=body.seed,
            n_paths=body.n_paths,
            n_quarters=body.n_quarters,
            switches=body.switches,
        )
        session.commit()
        for run in runs:
            session.refresh(run)
        return runs
    except ScenarioError as exc:
        session.rollback()
        _raise(exc)
        raise  # pragma: no cover


@router.get("/comparison", response_model=ComparisonRead)
def get_comparison(
    run_id: uuid.UUID = Query(),
    baseline_run_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(get_db),
    store: LocalArtifactStore = Depends(get_artifact_store),
) -> ComparisonRead:
    try:
        payload = compare_saved_runs(session, store, run_id=run_id, baseline_run_id=baseline_run_id)
        return ComparisonRead.model_validate(payload)
    except ScenarioError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/attribution", response_model=AttributionRead)
def get_attribution(
    run_id: uuid.UUID = Query(),
    baseline_run_id: uuid.UUID | None = Query(default=None),
    metric: str | None = Query(default=None),
    session: Session = Depends(get_db),
    store: LocalArtifactStore = Depends(get_artifact_store),
) -> AttributionRead:
    try:
        payload = attribute_saved_runs(
            session,
            store,
            run_id=run_id,
            baseline_run_id=baseline_run_id,
            metric=metric,
        )
        return AttributionRead.model_validate(payload)
    except ScenarioError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{scenario_id}", response_model=ScenarioRead)
def get_scenario(scenario_id: uuid.UUID, session: Session = Depends(get_db)) -> Scenario:
    row = session.get(Scenario, scenario_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    return row
