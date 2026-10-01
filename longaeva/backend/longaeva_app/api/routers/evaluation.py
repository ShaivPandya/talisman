"""Read-only evaluation-result endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import EvaluationResultRead
from longaeva_app.db.models import EvaluationResult
from longaeva_app.db.session import get_db

router = APIRouter(prefix="/evaluation-results", tags=["evaluation"])


@router.get("", response_model=list[EvaluationResultRead])
def list_evaluation_results(
    suite_version: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[EvaluationResult]:
    stmt = select(EvaluationResult).order_by(EvaluationResult.created_at.desc()).limit(limit)
    if suite_version is not None:
        stmt = stmt.where(EvaluationResult.suite_version == suite_version)
    return list(session.scalars(stmt).all())
