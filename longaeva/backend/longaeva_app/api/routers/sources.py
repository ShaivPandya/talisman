"""Read-only source and passage endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import DocumentTextRead, SourceRead
from longaeva_app.db.models import DocumentText, Source
from longaeva_app.db.session import get_db

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceRead])
def list_sources(
    company: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[Source]:
    stmt = select(Source).order_by(Source.publication_ts.desc()).limit(limit)
    if company is not None:
        stmt = stmt.where(Source.company == company)
    return list(session.scalars(stmt).all())


@router.get("/{source_id}", response_model=SourceRead)
def get_source(source_id: uuid.UUID, session: Session = Depends(get_db)) -> Source:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return source


@router.get("/{source_id}/passages", response_model=list[DocumentTextRead])
def list_passages(source_id: uuid.UUID, session: Session = Depends(get_db)) -> list[DocumentText]:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    stmt = (
        select(DocumentText)
        .where(DocumentText.source_id == source_id)
        .order_by(DocumentText.page, DocumentText.char_start)
    )
    return list(session.scalars(stmt).all())
