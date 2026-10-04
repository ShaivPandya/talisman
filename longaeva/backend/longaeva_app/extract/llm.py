"""Passage-only extraction: cache, validate, locate quotes, persist pending observations.

LON-16. A pending observation is the only write. Parameter sets are not touched.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ObservationCreate
from longaeva_app.config import Settings
from longaeva_app.db.models import DocumentText, ExtractionCall, Observation, Source
from longaeva_app.extract.cache import find_cached_call, prompt_hash, record_call
from longaeva_app.extract.prompts import PROMPT_VERSION, SYSTEM_PROMPT, user_message
from longaeva_app.extract.providers import LLMProvider, ProviderError
from longaeva_app.extract.schemas import ExtractedObservation, ExtractionResponse, extraction_json_schema
from longaeva_app.storage.local import LocalArtifactStore

logger = logging.getLogger(__name__)

EXTRACTOR_ID = "llm_extract"
EXTRACTOR_VERSION = "lon-16-v1"
_SCHEMA = extraction_json_schema()


class ExtractionError(Exception):
    """Selection or limit failure before a provider call."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class ExtractionReport:
    provider: str
    model: str
    prompt_version: str
    passages: int
    calls_made: int = 0
    cache_hits: int = 0
    failures: dict[str, int] = field(
        default_factory=lambda: {"invalid_response": 0, "provider_error": 0, "quote_not_found": 0}
    )
    observations_created: int = 0
    observation_ids: list[str] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    report_path: str | None = None

    @property
    def cache_hit_rate(self) -> float:
        denom = self.calls_made + self.cache_hits
        if denom == 0:
            return 0.0
        return self.cache_hits / denom

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "passages": self.passages,
            "calls_made": self.calls_made,
            "cache_hits": self.cache_hits,
            "cache_hit_rate": self.cache_hit_rate,
            "failures": self.failures,
            "observations_created": self.observations_created,
            "observation_ids": self.observation_ids,
            "observations": self.observations,
            "report_path": self.report_path,
        }


def load_passages(session: Session, passage_ids: list[UUID], *, settings: Settings) -> list[DocumentText]:
    """Load the selected passages or raise ``ExtractionError`` before any provider call."""
    if len(passage_ids) > settings.extraction_max_passages:
        raise ExtractionError(
            f"At most {settings.extraction_max_passages} passages per extraction; got {len(passage_ids)}.",
            status_code=422,
        )
    if not passage_ids:
        raise ExtractionError("At least one passage is required.", status_code=422)
    rows = list(session.scalars(select(DocumentText).where(DocumentText.id.in_(passage_ids))).all())
    by_id = {row.id: row for row in rows}
    missing = [str(passage_id) for passage_id in passage_ids if passage_id not in by_id]
    if missing:
        raise ExtractionError(f"Unknown passages: {missing}", status_code=404)
    ordered = [by_id[passage_id] for passage_id in passage_ids]
    limit = settings.extraction_max_passage_chars
    for row in ordered:
        if len(row.text) > limit:
            raise ExtractionError(
                f"Passage {row.id} is {len(row.text)} characters; the limit is {limit}.",
                status_code=422,
            )
    return ordered


def locate_quote(passage: str, quote: str) -> tuple[int, int] | None:
    """Return ``[start, end)`` of ``quote`` in ``passage``, tolerating whitespace differences."""
    if not quote or not passage:
        return None
    exact = passage.find(quote)
    if exact >= 0:
        return exact, exact + len(quote)
    collapsed, mapping = _collapse(passage)
    quote_collapsed, _quote_mapping = _collapse(quote.strip())
    if not quote_collapsed:
        return None
    idx = collapsed.find(quote_collapsed)
    if idx < 0:
        return None
    start = mapping[idx]
    end = mapping[idx + len(quote_collapsed) - 1] + 1
    return start, end


def run_extraction(
    session: Session,
    passages: list[DocumentText],
    *,
    provider: LLMProvider,
    settings: Settings,
    store: LocalArtifactStore | None = None,
    job_id: UUID | None = None,
) -> ExtractionReport:
    """Extract observations from ``passages``. Cache hits do not call the provider."""
    report = ExtractionReport(
        provider=provider.name,
        model=provider.model,
        prompt_version=PROMPT_VERSION,
        passages=len(passages),
    )
    for passage in passages:
        _extract_one(
            session,
            passage,
            provider=provider,
            report=report,
            job_id=job_id,
        )
    report.report_path = _write_report(store, report)
    logger.info(
        "extraction provider=%s model=%s passages=%s calls=%s cache_hits=%s hit_rate=%.3f failures=%s observations=%s",
        report.provider,
        report.model,
        report.passages,
        report.calls_made,
        report.cache_hits,
        report.cache_hit_rate,
        report.failures,
        report.observations_created,
    )
    return report


def _extract_one(
    session: Session,
    passage: DocumentText,
    *,
    provider: LLMProvider,
    report: ExtractionReport,
    job_id: UUID | None,
) -> None:
    source = session.get(Source, passage.source_id)
    if source is None:
        report.failures["provider_error"] = report.failures.get("provider_error", 0) + 1
        record_call(
            session,
            provider=provider.name,
            model=provider.model,
            prompt_version=PROMPT_VERSION,
            prompt_hash="missing-source",
            document_text_id=passage.id,
            job_id=job_id,
            status="provider_error",
            response_text=None,
            parsed=None,
            item_errors=[],
            error=f"Passage {passage.id} has no source",
            attempts=0,
            latency_ms=None,
            input_tokens=None,
            output_tokens=None,
        )
        return

    period_label = None
    if source.period_start is not None and source.period_end is not None:
        period_label = f"{source.period_start.isoformat()} to {source.period_end.isoformat()}"
    user = user_message(
        company=source.company,
        doc_type=source.doc_type,
        passage=passage.text,
        period_label=period_label,
    )
    digest = prompt_hash(prompt_version=PROMPT_VERSION, system=SYSTEM_PROMPT, user=user, schema=_SCHEMA)
    cached = find_cached_call(session, provider=provider.name, model=provider.model, prompt_hash=digest)
    if cached is not None:
        report.cache_hits += 1
        _apply_payload(
            session,
            passage,
            source,
            payload=cached.parsed,
            call_id=cached.id,
            digest=digest,
            report=report,
            response_text=cached.response_text or "",
            persist_errors=False,
        )
        return

    started = time.perf_counter()
    try:
        result = provider.complete(system=SYSTEM_PROMPT, user=user)
    except ProviderError as exc:
        report.calls_made += 1
        report.failures["provider_error"] += 1
        record_call(
            session,
            provider=provider.name,
            model=provider.model,
            prompt_version=PROMPT_VERSION,
            prompt_hash=digest,
            document_text_id=passage.id,
            job_id=job_id,
            status="provider_error",
            response_text=None,
            parsed=None,
            item_errors=[],
            error=exc.message,
            attempts=exc.attempts,
            latency_ms=_elapsed_ms(started),
            input_tokens=None,
            output_tokens=None,
        )
        return

    report.calls_made += 1
    latency_ms = _elapsed_ms(started)
    parsed_model, item_errors = _validate_payload(result.parsed)
    if parsed_model is None:
        report.failures["invalid_response"] += 1
        record_call(
            session,
            provider=provider.name,
            model=provider.model,
            prompt_version=PROMPT_VERSION,
            prompt_hash=digest,
            document_text_id=passage.id,
            job_id=job_id,
            status="invalid_response",
            response_text=result.text,
            parsed=None,
            item_errors=item_errors,
            error="Response did not match the extraction schema",
            attempts=result.attempts,
            latency_ms=latency_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return

    stored = parsed_model.model_dump(mode="json")
    call = record_call(
        session,
        provider=provider.name,
        model=provider.model,
        prompt_version=PROMPT_VERSION,
        prompt_hash=digest,
        document_text_id=passage.id,
        job_id=job_id,
        status="succeeded",
        response_text=result.text,
        parsed=stored,
        item_errors=[],
        error=None,
        attempts=result.attempts,
        latency_ms=latency_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    _apply_items(
        session,
        passage,
        source,
        items=parsed_model.observations,
        call=call,
        digest=digest,
        report=report,
        persist_errors=True,
    )


def _apply_payload(
    session: Session,
    passage: DocumentText,
    source: Source,
    *,
    payload: dict[str, Any] | None,
    call_id: UUID,
    digest: str,
    report: ExtractionReport,
    response_text: str,
    persist_errors: bool,
) -> None:
    parsed_model, item_errors = _validate_payload(payload)
    if parsed_model is None:
        report.failures["invalid_response"] += 1
        logger.info(
            "cached extraction payload failed validation passage=%s errors=%s text_len=%s",
            passage.id,
            item_errors,
            len(response_text),
        )
        return
    call = session.get(ExtractionCall, call_id)
    if call is None:
        report.failures["invalid_response"] += 1
        return
    _apply_items(
        session,
        passage,
        source,
        items=parsed_model.observations,
        call=call,
        digest=digest,
        report=report,
        persist_errors=persist_errors,
    )


def _apply_items(
    session: Session,
    passage: DocumentText,
    source: Source,
    *,
    items: list[ExtractedObservation],
    call: ExtractionCall,
    digest: str,
    report: ExtractionReport,
    persist_errors: bool,
) -> None:
    quote_errors: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        located = locate_quote(passage.text, item.quote)
        if located is None:
            report.failures["quote_not_found"] += 1
            quote_errors.append({"index": index, "code": "quote_not_found", "quote": item.quote})
            continue
        local_start, local_end = located
        if _already_extracted(session, passage_id=passage.id, item=item, digest=digest):
            continue
        number_flag = not _numbers_in_quote(item)
        observation = _persist_observation(
            session,
            passage,
            source,
            item=item,
            call=call,
            digest=digest,
            local_start=local_start,
            local_end=local_end,
            number_not_in_quote=number_flag,
        )
        report.observations_created += 1
        report.observation_ids.append(str(observation.id))
        report.observations.append(_observation_summary(observation, item.quote))
    if persist_errors and quote_errors:
        call.item_errors = list(call.item_errors or []) + quote_errors
        session.flush()


def _persist_observation(
    session: Session,
    passage: DocumentText,
    source: Source,
    *,
    item: ExtractedObservation,
    call: ExtractionCall,
    digest: str,
    local_start: int,
    local_end: int,
    number_not_in_quote: bool,
) -> Observation:
    attributes: dict[str, Any] = {
        "extraction_call_id": str(call.id),
        "provider": call.provider,
        "model": call.model,
        "prompt_hash": digest,
        "prompt_version": PROMPT_VERSION,
        "quote": item.quote,
        "number_not_in_quote": number_not_in_quote,
    }
    create = ObservationCreate(
        company=source.company,
        source_id=source.id,
        document_text_id=passage.id,
        span_page=passage.page,
        span_char_start=passage.char_start + local_start,
        span_char_end=passage.char_start + local_end,
        statement_type=item.statement_type,
        activity_type=item.activity_type,
        geography=item.geography,
        period_start=item.period_start,
        period_end=item.period_end,
        value=item.value,
        range_low=item.range_low,
        range_high=item.range_high,
        unit=item.unit,
        basis=item.basis,
        source_family=source.company,
        extractor_id=EXTRACTOR_ID,
        extractor_version=EXTRACTOR_VERSION,
        review_status="pending",
        attributes=attributes,
    )
    row = Observation(
        company=create.company,
        source_id=create.source_id,
        document_text_id=create.document_text_id,
        span_page=create.span_page,
        span_char_start=create.span_char_start,
        span_char_end=create.span_char_end,
        statement_type=create.statement_type,
        activity_type=create.activity_type,
        geography=create.geography,
        period_start=create.period_start,
        period_end=create.period_end,
        value=create.value,
        range_low=create.range_low,
        range_high=create.range_high,
        unit=create.unit,
        basis=create.basis,
        source_family=create.source_family,
        extractor_id=create.extractor_id,
        extractor_version=create.extractor_version,
        review_status="pending",
        attributes=create.attributes,
    )
    session.add(row)
    session.flush()
    return row


def _already_extracted(
    session: Session,
    *,
    passage_id: UUID,
    item: ExtractedObservation,
    digest: str,
) -> bool:
    stmt = (
        select(Observation.id)
        .where(Observation.document_text_id == passage_id)
        .where(Observation.extractor_id == EXTRACTOR_ID)
        .where(Observation.statement_type == item.statement_type)
        .where(Observation.attributes["quote"].astext == item.quote)
        .where(Observation.attributes["prompt_hash"].astext == digest)
        .limit(1)
    )
    if item.value is None:
        stmt = stmt.where(Observation.value.is_(None))
    else:
        stmt = stmt.where(Observation.value == item.value)
    return session.execute(stmt).first() is not None


def _validate_payload(
    payload: dict[str, Any] | None,
) -> tuple[ExtractionResponse | None, list[dict[str, Any]]]:
    if payload is None:
        return None, [{"code": "invalid_json", "msg": "response was not a JSON object"}]
    try:
        return ExtractionResponse.model_validate(payload), []
    except ValidationError as exc:
        errors: list[dict[str, Any]] = []
        for err in exc.errors()[:20]:
            errors.append(
                {
                    "loc": [str(part) for part in err.get("loc", ())],
                    "type": str(err.get("type") or ""),
                    "msg": str(err.get("msg") or ""),
                }
            )
        return None, errors


def _numbers_in_quote(item: ExtractedObservation) -> bool:
    numbers = [number for number in (item.value, item.range_low, item.range_high) if number is not None]
    if not numbers:
        return True
    folded = item.quote.replace(",", "")
    return all(any(token in folded for token in _number_tokens(number)) for number in numbers)


def _number_tokens(number: float) -> list[str]:
    tokens = [str(number)]
    if float(number).is_integer():
        tokens.append(str(int(number)))
    tokens.append(f"{number:.1f}")
    return tokens


def _collapse(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    mapping: list[int] = []
    previous_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if previous_space:
                continue
            chars.append(" ")
            mapping.append(index)
            previous_space = True
            continue
        chars.append(char)
        mapping.append(index)
        previous_space = False
    return "".join(chars), mapping


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _observation_summary(row: Observation, quote: str) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "statement_type": row.statement_type,
        "activity_type": row.activity_type,
        "geography": row.geography,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "value": row.value,
        "range_low": row.range_low,
        "range_high": row.range_high,
        "unit": row.unit,
        "basis": row.basis,
        "quote": quote,
        "span_page": row.span_page,
        "span_char_start": row.span_char_start,
        "span_char_end": row.span_char_end,
        "review_status": row.review_status,
    }


def _write_report(store: LocalArtifactStore | None, report: ExtractionReport) -> str | None:
    if store is None:
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    key = f"reports/extraction/{stamp}.json"
    try:
        return store.write_once(key, payload.encode("utf-8"))
    except Exception:  # noqa: BLE001 — a report collision must not fail extraction
        key = f"reports/extraction/{stamp}-{report.passages}-{report.calls_made}.json"
        try:
            return store.write_once(key, payload.encode("utf-8"))
        except Exception:  # noqa: BLE001
            logger.warning("extraction report was not written")
            return None
