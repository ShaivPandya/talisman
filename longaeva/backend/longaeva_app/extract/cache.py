"""Extraction-call cache and failure rows.

Succeeded rows are the cache, keyed by provider, model, and prompt hash.
Failed rows stay in the table and are never reused as a hit.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from longaeva_app.db.models import ExtractionCall
from longaeva_app.hashing import content_hash


def prompt_hash(*, prompt_version: str, system: str, user: str, schema: dict[str, Any]) -> str:
    """SHA-256 of the canonical prompt. Key order does not change the digest."""
    return content_hash(
        {
            "prompt_version": prompt_version,
            "schema": schema,
            "system": system,
            "user": user,
        }
    )


def find_cached_call(
    session: Session,
    *,
    provider: str,
    model: str,
    prompt_hash: str,
) -> ExtractionCall | None:
    stmt = (
        select(ExtractionCall)
        .where(ExtractionCall.provider == provider)
        .where(ExtractionCall.model == model)
        .where(ExtractionCall.prompt_hash == prompt_hash)
        .where(ExtractionCall.status == "succeeded")
        .limit(1)
    )
    return session.scalars(stmt).first()


def record_call(
    session: Session,
    *,
    provider: str,
    model: str,
    prompt_version: str,
    prompt_hash: str,
    document_text_id: UUID | None,
    job_id: UUID | None,
    status: str,
    response_text: str | None,
    parsed: dict[str, Any] | None,
    item_errors: list[dict[str, Any]],
    error: str | None,
    attempts: int,
    latency_ms: int | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> ExtractionCall:
    """Insert a call row. A lost race on the succeeded-row unique index returns the winner."""
    row = ExtractionCall(
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        prompt_hash=prompt_hash,
        document_text_id=document_text_id,
        job_id=job_id,
        status=status,
        response_text=response_text,
        parsed=parsed,
        item_errors=item_errors,
        error=error,
        attempts=attempts,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        if status != "succeeded":
            raise
        existing = find_cached_call(session, provider=provider, model=model, prompt_hash=prompt_hash)
        if existing is None:
            raise
        return existing
    return row
