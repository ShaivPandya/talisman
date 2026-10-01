"""Read-only parameter-set endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ParameterSetRead
from longaeva_app.db.models import ParameterSet
from longaeva_app.db.session import get_db

router = APIRouter(prefix="/parameter-sets", tags=["parameter-sets"])


@router.get("", response_model=list[ParameterSetRead])
def list_parameter_sets(
    company: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[ParameterSet]:
    stmt = select(ParameterSet).order_by(ParameterSet.created_at.desc()).limit(limit)
    if company is not None:
        stmt = stmt.where(ParameterSet.company == company)
    return list(session.scalars(stmt).all())


@router.get("/{parameter_set_id}", response_model=ParameterSetRead)
def get_parameter_set(parameter_set_id: uuid.UUID, session: Session = Depends(get_db)) -> ParameterSet:
    row = session.get(ParameterSet, parameter_set_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parameter set not found")
    return row
