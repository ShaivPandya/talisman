"""Postgres full-text search over stored document passages.

Matches use the stored ``document_text.tsv`` column (``to_tsvector('english', text)``)
and the GIN index ``ix_document_text_tsv`` created with the core schema. Callers
pass a web-style query; filters are company (exact), source-period overlap, and
an optional publication cutoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from longaeva_app.db.models import DocumentText, Source

TS_CONFIG = "english"
HEADLINE_OPTIONS = "StartSel=<b>, StopSel=</b>, MaxWords=24, MinWords=8, ShortWord=3, MaxFragments=1"
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

_TS_CONFIG: ColumnElement[str] = literal_column("'english'")


class SearchQueryError(ValueError):
    """The search text or a filter is not usable."""


@dataclass(frozen=True)
class PassageHit:
    """One matching passage plus the source fields a reviewer needs."""

    document_text_id: UUID
    source_id: UUID
    page: int
    char_start: int
    char_end: int
    text: str
    snippet: str
    rank: float
    company: str
    doc_type: str
    url: str
    publication_ts: datetime
    period_start: date | None
    period_end: date | None


@dataclass(frozen=True)
class PassageSearch:
    """Applied filters and the ranked hits they produced."""

    query: str
    company: str | None
    period_start: date | None
    period_end: date | None
    cutoff_ts: datetime | None
    hits: list[PassageHit]


def normalize_cutoff(value: datetime) -> datetime:
    """Treat a naive cutoff as UTC and convert aware values to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def search_passages(
    session: Session,
    q: str,
    *,
    company: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    cutoff_ts: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
) -> PassageSearch:
    """Return passages whose stored ``tsvector`` matches ``q``.

    A period filter keeps a source only when ``period_start``/``period_end`` are
    both set and the source period overlaps the requested range. Sources with a
    null period stay searchable when no period filter is passed. ``cutoff_ts``
    keeps ``publication_ts <= cutoff``; a value equal to the cutoff is included.
    Stopword-only queries match nothing and return an empty hit list.
    """
    query = q.strip()
    if not query:
        raise SearchQueryError("q must not be blank")
    if limit < 1 or limit > MAX_LIMIT:
        raise SearchQueryError(f"limit must be between 1 and {MAX_LIMIT}")
    if period_start is not None and period_end is not None and period_start > period_end:
        raise SearchQueryError("period_start must be on or before period_end")

    applied_company = _clean_company(company)
    applied_cutoff = normalize_cutoff(cutoff_ts) if cutoff_ts is not None else None
    tsquery = func.websearch_to_tsquery(_TS_CONFIG, query)
    rank = func.ts_rank_cd(DocumentText.tsv, tsquery)
    snippet = func.ts_headline(_TS_CONFIG, DocumentText.text, tsquery, HEADLINE_OPTIONS)

    stmt = (
        select(
            DocumentText.id.label("document_text_id"),
            DocumentText.source_id.label("source_id"),
            DocumentText.page.label("page"),
            DocumentText.char_start.label("char_start"),
            DocumentText.char_end.label("char_end"),
            DocumentText.text.label("text"),
            snippet.label("snippet"),
            rank.label("rank"),
            Source.company.label("company"),
            Source.doc_type.label("doc_type"),
            Source.url.label("url"),
            Source.publication_ts.label("publication_ts"),
            Source.period_start.label("period_start"),
            Source.period_end.label("period_end"),
        )
        .join(Source, DocumentText.source_id == Source.id)
        .where(DocumentText.tsv.op("@@")(tsquery))
    )
    if applied_company is not None:
        stmt = stmt.where(Source.company == applied_company)
    if period_start is not None or period_end is not None:
        # Undated sources have no observation period to overlap.
        stmt = stmt.where(Source.period_start.is_not(None), Source.period_end.is_not(None))
        if period_start is not None:
            stmt = stmt.where(Source.period_end >= period_start)
        if period_end is not None:
            stmt = stmt.where(Source.period_start <= period_end)
    if applied_cutoff is not None:
        stmt = stmt.where(Source.publication_ts <= applied_cutoff)

    stmt = stmt.order_by(rank.desc(), Source.publication_ts.desc(), DocumentText.id.asc()).limit(limit)
    hits = [_hit_from_row(dict(row)) for row in session.execute(stmt).mappings()]
    return PassageSearch(
        query=query,
        company=applied_company,
        period_start=period_start,
        period_end=period_end,
        cutoff_ts=applied_cutoff,
        hits=hits,
    )


def _clean_company(company: str | None) -> str | None:
    if company is None:
        return None
    cleaned = company.strip()
    if not cleaned:
        raise SearchQueryError("company must not be blank")
    return cleaned


def _hit_from_row(row: dict[str, Any]) -> PassageHit:
    snippet = row["snippet"]
    return PassageHit(
        document_text_id=_as_uuid(row["document_text_id"]),
        source_id=_as_uuid(row["source_id"]),
        page=_as_int(row["page"]),
        char_start=_as_int(row["char_start"]),
        char_end=_as_int(row["char_end"]),
        text=_as_str(row["text"]),
        snippet="" if snippet is None else _as_str(snippet),
        rank=_as_float(row["rank"]),
        company=_as_str(row["company"]),
        doc_type=_as_str(row["doc_type"]),
        url=_as_str(row["url"]),
        publication_ts=_as_datetime(row["publication_ts"]),
        period_start=_as_date(row["period_start"]),
        period_end=_as_date(row["period_end"]),
    )


def _as_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise TypeError(f"expected UUID, got {type(value).__name__}")


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"expected int, got {type(value).__name__}")
    return value


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise TypeError(f"expected float, got {type(value).__name__}")
    return float(value)


def _as_str(value: object) -> str:
    if isinstance(value, str):
        return value
    raise TypeError(f"expected str, got {type(value).__name__}")


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    raise TypeError(f"expected datetime, got {type(value).__name__}")


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"expected date, got {type(value).__name__}")
