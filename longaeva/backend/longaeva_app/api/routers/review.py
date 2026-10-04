"""Review decision endpoints (LON-16 / FR-05)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ReviewDecisionCreate, ReviewDecisionRead
from longaeva_app.db.models import ReviewDecision
from longaeva_app.db.session import get_db
from longaeva_app.review.service import ReviewError, record_decision

router = APIRouter(prefix="/review-decisions", tags=["review"])


@router.post("", response_model=ReviewDecisionRead, status_code=status.HTTP_201_CREATED)
def create_review_decision(body: ReviewDecisionCreate, session: Session = Depends(get_db)) -> ReviewDecision:
    try:
        row = record_decision(
            session,
            observation_id=body.observation_id,
            decision=body.decision,
            rationale=body.rationale,
            decided_by=body.decided_by,
            corrected_payload=body.corrected_payload,
            decided_at=body.decided_at,
        )
        session.commit()
        session.refresh(row)
        return row
    except ReviewError as exc:
        session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("", response_model=list[ReviewDecisionRead])
def list_review_decisions(
    observation_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[ReviewDecision]:
    stmt = select(ReviewDecision)
    if observation_id is not None:
        stmt = stmt.where(ReviewDecision.observation_id == observation_id).order_by(ReviewDecision.version)
    else:
        stmt = stmt.order_by(ReviewDecision.decided_at.desc())
    return list(session.scalars(stmt.limit(limit)).all())
