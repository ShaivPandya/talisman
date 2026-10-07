"""Observation reads plus extraction enqueue (LON-16)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import (
    ExtractionCallRead,
    ExtractionRequest,
    ExtractionStatusRead,
    JobRead,
    ObservationRead,
    ObservationReviewRead,
    ReviewDecisionRead,
)
from longaeva_app.api.workspace_schemas import EvidenceExcerpt
from longaeva_app.config import get_settings
from longaeva_app.db.models import ExtractionCall, Job, Observation, ReviewDecision
from longaeva_app.db.session import get_db
from longaeva_app.extract.llm import ExtractionError, load_passages
from longaeva_app.extract.providers import describe_extraction
from longaeva_app.review.service import effective_observation
from longaeva_app.workspace import observation_evidence

router = APIRouter(prefix="/observations", tags=["observations"])


@router.get("", response_model=list[ObservationRead])
def list_observations(
    company: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    source_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[Observation]:
    stmt = select(Observation).order_by(Observation.created_at.desc(), Observation.id).offset(offset).limit(limit)
    if company is not None:
        stmt = stmt.where(Observation.company == company)
    if review_status is not None:
        stmt = stmt.where(Observation.review_status == review_status)
    if source_id is not None:
        stmt = stmt.where(Observation.source_id == source_id)
    return list(session.scalars(stmt).all())


@router.get("/extraction-status", response_model=ExtractionStatusRead)
def extraction_status() -> ExtractionStatusRead:
    described = describe_extraction(get_settings())
    return ExtractionStatusRead(
        enabled=described.enabled,
        provider=described.provider,
        model=described.model,
        configured_providers=described.configured_providers,
        disabled_reason=described.disabled_reason,
        max_passages=described.max_passages,
        max_passage_chars=described.max_passage_chars,
        prompt_version=described.prompt_version,
    )


@router.post("/extract", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def enqueue_extraction(body: ExtractionRequest, session: Session = Depends(get_db)) -> Job:
    settings = get_settings()
    described = describe_extraction(settings, provider=body.provider, model=body.model)
    if not described.enabled:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY if body.provider else status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=code, detail=described.disabled_reason)
    try:
        load_passages(session, list(body.document_text_ids), settings=settings)
    except ExtractionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    payload: dict[str, object] = {"document_text_ids": [str(item) for item in body.document_text_ids]}
    if body.provider:
        payload["provider"] = body.provider
    if body.model:
        payload["model"] = body.model
    job = Job(type="extract", payload=payload, status="queued")
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.get("/extraction-calls", response_model=list[ExtractionCallRead])
def list_extraction_calls(
    status_filter: str | None = Query(default=None, alias="status"),
    document_text_id: uuid.UUID | None = Query(default=None),
    job_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[ExtractionCall]:
    stmt = select(ExtractionCall).order_by(ExtractionCall.created_at.desc()).limit(limit)
    if status_filter is not None:
        stmt = stmt.where(ExtractionCall.status == status_filter)
    if document_text_id is not None:
        stmt = stmt.where(ExtractionCall.document_text_id == document_text_id)
    if job_id is not None:
        stmt = stmt.where(ExtractionCall.job_id == job_id)
    return list(session.scalars(stmt).all())


@router.get("/{observation_id}", response_model=ObservationRead)
def get_observation(observation_id: uuid.UUID, session: Session = Depends(get_db)) -> Observation:
    observation = session.get(Observation, observation_id)
    if observation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Observation not found")
    return observation


@router.get("/{observation_id}/evidence", response_model=EvidenceExcerpt)
def get_observation_evidence(
    observation_id: uuid.UUID,
    cutoff_ts: AwareDatetime = Query(),
    session: Session = Depends(get_db),
) -> EvidenceExcerpt:
    return observation_evidence(session, observation_id, cutoff_ts)


@router.get("/{observation_id}/review", response_model=ObservationReviewRead)
def get_observation_review(observation_id: uuid.UUID, session: Session = Depends(get_db)) -> ObservationReviewRead:
    observation = session.get(Observation, observation_id)
    if observation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Observation not found")
    decisions = list(
        session.scalars(
            select(ReviewDecision)
            .where(ReviewDecision.observation_id == observation_id)
            .order_by(ReviewDecision.version)
        ).all()
    )
    return ObservationReviewRead(
        observation=ObservationRead.model_validate(observation, from_attributes=True),
        decisions=[ReviewDecisionRead.model_validate(row, from_attributes=True) for row in decisions],
        effective=effective_observation(session, observation),
    )
