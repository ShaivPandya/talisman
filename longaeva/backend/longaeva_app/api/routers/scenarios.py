"""Read-only scenario endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ScenarioRead
from longaeva_app.db.models import Scenario
from longaeva_app.db.session import get_db

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


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


@router.get("/{scenario_id}", response_model=ScenarioRead)
def get_scenario(scenario_id: uuid.UUID, session: Session = Depends(get_db)) -> Scenario:
    row = session.get(Scenario, scenario_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    return row
