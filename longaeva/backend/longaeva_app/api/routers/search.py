"""Full-text passage search (LON-17 / FR-02)."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import PassageSearchHitRead, PassageSearchRead
from longaeva_app.db.session import get_db
from longaeva_app.search import PassageHit, PassageSearch, SearchQueryError, search_passages

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/passages", response_model=PassageSearchRead)
def search_document_passages(
    q: str = Query(min_length=1, description="Web-style full-text query (quotes, OR, -term)."),
    company: str | None = Query(default=None, description="Exact source.company match."),
    period_start: date | None = Query(
        default=None,
        description="Keep sources whose period overlaps this start (drops undated sources).",
    ),
    period_end: date | None = Query(
        default=None,
        description="Keep sources whose period overlaps this end (drops undated sources).",
    ),
    cutoff_ts: datetime | None = Query(
        default=None,
        description=(
            "Keep sources with publication_ts <= this instant. "
            "A value without a timezone is UTC. A date alone is midnight UTC."
        ),
    ),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
) -> PassageSearchRead:
    try:
        result = search_passages(
            session,
            q,
            company=company,
            period_start=period_start,
            period_end=period_end,
            cutoff_ts=cutoff_ts,
            limit=limit,
        )
    except SearchQueryError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _read(result)


def _read(result: PassageSearch) -> PassageSearchRead:
    return PassageSearchRead(
        query=result.query,
        company=result.company,
        period_start=result.period_start,
        period_end=result.period_end,
        cutoff_ts=result.cutoff_ts,
        hits=[_hit_read(hit) for hit in result.hits],
    )


def _hit_read(hit: PassageHit) -> PassageSearchHitRead:
    return PassageSearchHitRead(
        document_text_id=hit.document_text_id,
        source_id=hit.source_id,
        page=hit.page,
        char_start=hit.char_start,
        char_end=hit.char_end,
        text=hit.text,
        snippet=hit.snippet,
        rank=hit.rank,
        company=hit.company,
        doc_type=hit.doc_type,
        url=hit.url,
        publication_ts=hit.publication_ts,
        period_start=hit.period_start,
        period_end=hit.period_end,
    )


__all__ = ["router"]
