"""Read-only forecast archive endpoints (immutable; no write/update routes)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ForecastRead
from longaeva_app.db.models import Forecast
from longaeva_app.db.session import get_db

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


@router.get("", response_model=list[ForecastRead])
def list_forecasts(
    kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[Forecast]:
    stmt = select(Forecast).order_by(Forecast.created_at.desc()).limit(limit)
    if kind is not None:
        stmt = stmt.where(Forecast.kind == kind)
    return list(session.scalars(stmt).all())


@router.get("/{forecast_id}", response_model=ForecastRead)
def get_forecast(forecast_id: uuid.UUID, session: Session = Depends(get_db)) -> Forecast:
    row = session.get(Forecast, forecast_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Forecast not found")
    return row
