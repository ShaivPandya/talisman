"""Read-only observation endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ObservationRead
from longaeva_app.db.models import Observation
from longaeva_app.db.session import get_db

router = APIRouter(prefix="/observations", tags=["observations"])


@router.get("", response_model=list[ObservationRead])
def list_observations(
    company: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[Observation]:
    stmt = select(Observation).order_by(Observation.created_at.desc()).limit(limit)
    if company is not None:
        stmt = stmt.where(Observation.company == company)
    if review_status is not None:
        stmt = stmt.where(Observation.review_status == review_status)
    return list(session.scalars(stmt).all())


@router.get("/{observation_id}", response_model=ObservationRead)
def get_observation(observation_id: uuid.UUID, session: Session = Depends(get_db)) -> Observation:
    observation = session.get(Observation, observation_id)
    if observation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Observation not found")
    return observation
