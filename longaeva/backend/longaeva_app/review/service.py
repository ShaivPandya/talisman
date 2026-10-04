"""Versioned accept / reject / correct decisions (LON-16 / FR-05).

The original observation row is never rewritten except for ``review_status``.
Corrections live on ``review_decision`` rows. Pending and rejected observations
cannot back a run.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ObservationCreate
from longaeva_app.db.models import Observation, ParameterSet, ReviewDecision

CORRECTION_FIELDS = frozenset(
    {
        "statement_type",
        "activity_type",
        "geography",
        "period_start",
        "period_end",
        "value",
        "range_low",
        "range_high",
        "unit",
        "basis",
    }
)
DECISION_STATUS = {"accept": "accepted", "reject": "rejected", "correct": "corrected"}
REVIEWED_STATUSES = frozenset({"accepted", "corrected"})
_DATE_FIELDS = frozenset({"period_start", "period_end"})


class ReviewError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def record_decision(
    session: Session,
    *,
    observation_id: UUID,
    decision: str,
    rationale: str,
    decided_by: str,
    corrected_payload: dict[str, Any] | None = None,
    decided_at: datetime | None = None,
) -> ReviewDecision:
    """Append the next decision version and set ``review_status`` from it."""
    observation = session.execute(
        select(Observation).where(Observation.id == observation_id).with_for_update()
    ).scalar_one_or_none()
    if observation is None:
        raise ReviewError("Observation not found", status_code=404)
    if decision not in DECISION_STATUS:
        raise ReviewError(f"Unknown decision {decision!r}", status_code=422)
    stored_payload: dict[str, Any] | None = None
    if decision == "correct":
        stored_payload = _validate_correction(observation, corrected_payload)
    elif corrected_payload is not None:
        raise ReviewError("corrected_payload is only allowed when decision is correct", status_code=422)

    current = session.scalar(
        select(func.max(ReviewDecision.version)).where(ReviewDecision.observation_id == observation.id)
    )
    version = int(current or 0) + 1
    row = ReviewDecision(
        observation_id=observation.id,
        decision=decision,
        version=version,
        corrected_payload=stored_payload,
        rationale=rationale,
        decided_at=decided_at or datetime.now(UTC),
        decided_by=decided_by,
    )
    observation.review_status = DECISION_STATUS[decision]
    session.add(row)
    session.flush()
    return row


def effective_observation(session: Session, observation: Observation) -> dict[str, Any] | None:
    """Original fields overlaid with the latest correction. None when pending or rejected."""
    if observation.review_status not in REVIEWED_STATUSES:
        return None
    values = _base_values(observation)
    latest = _latest_correction(session, observation.id)
    if latest is not None and isinstance(latest.corrected_payload, dict):
        values.update(_coerce_correction(latest.corrected_payload))
    values["review_status"] = observation.review_status
    return _jsonable(values)


def require_reviewed(session: Session, observation_ids: list[UUID]) -> list[Observation]:
    """Return the rows, or raise when any id is missing or not accepted/corrected."""
    if not observation_ids:
        return []
    rows = list(session.scalars(select(Observation).where(Observation.id.in_(observation_ids))).all())
    found = {row.id for row in rows}
    missing = [str(item) for item in observation_ids if item not in found]
    if missing:
        raise ReviewError(f"Observations not found: {missing}", status_code=404)
    blocked = [str(row.id) for row in rows if row.review_status not in REVIEWED_STATUSES]
    if blocked:
        raise ReviewError(f"Observations are not reviewed: {blocked}", status_code=422)
    return rows


def assert_evidence_reviewed(session: Session, parameter_set: ParameterSet) -> None:
    """Refuse a run whose evidence cites a pending or rejected observation row.

    Identifiers that are not observation rows (parser evidence that was never
    loaded) are left alone. Replay does not call this.
    """
    linked = _linked_observation_ids(parameter_set)
    if not linked:
        return
    rows = list(session.scalars(select(Observation).where(Observation.id.in_(linked))).all())
    by_id = {row.id: row for row in rows}
    blocked: list[str] = []
    for observation_id in linked:
        row = by_id.get(observation_id)
        if row is None:
            continue
        if row.review_status not in REVIEWED_STATUSES:
            blocked.append(f"{observation_id} ({row.review_status})")
    if blocked:
        raise ReviewError(
            "Parameter set cites observations that are not reviewed: " + ", ".join(blocked),
            status_code=422,
        )


def _validate_correction(observation: Observation, payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        raise ReviewError("corrected_payload is required when decision is correct", status_code=422)
    unknown = sorted(set(payload) - CORRECTION_FIELDS)
    if unknown:
        raise ReviewError(f"corrected_payload has unknown fields: {unknown}", status_code=422)
    if "confidence" in payload or "probability" in payload:
        raise ReviewError("confidence/probability fields are not allowed", status_code=422)
    merged = _base_values(observation)
    coerced = _coerce_correction(payload)
    merged.update(coerced)
    merged["review_status"] = "corrected"
    try:
        ObservationCreate.model_validate(merged)
    except ValueError as exc:
        raise ReviewError(str(exc), status_code=422) from exc
    return _jsonable(coerced)


def _base_values(observation: Observation) -> dict[str, Any]:
    return {
        "company": observation.company,
        "source_id": observation.source_id,
        "document_text_id": observation.document_text_id,
        "span_page": observation.span_page,
        "span_char_start": observation.span_char_start,
        "span_char_end": observation.span_char_end,
        "statement_type": observation.statement_type,
        "activity_type": observation.activity_type,
        "geography": observation.geography,
        "period_start": observation.period_start,
        "period_end": observation.period_end,
        "value": observation.value,
        "range_low": observation.range_low,
        "range_high": observation.range_high,
        "unit": observation.unit,
        "basis": observation.basis,
        "source_family": observation.source_family,
        "extractor_id": observation.extractor_id,
        "extractor_version": observation.extractor_version,
        "review_status": observation.review_status,
        "attributes": dict(observation.attributes or {}),
    }


def _coerce_correction(payload: dict[str, Any]) -> dict[str, Any]:
    coerced: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _DATE_FIELDS and isinstance(value, str):
            try:
                coerced[key] = date.fromisoformat(value)
            except ValueError as exc:
                raise ReviewError(f"{key} must be an ISO date", status_code=422) from exc
            continue
        coerced[key] = value
    return coerced


def _latest_correction(session: Session, observation_id: UUID) -> ReviewDecision | None:
    stmt = (
        select(ReviewDecision)
        .where(ReviewDecision.observation_id == observation_id)
        .where(ReviewDecision.decision == "correct")
        .order_by(ReviewDecision.version.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def _linked_observation_ids(parameter_set: ParameterSet) -> list[UUID]:
    found: list[UUID] = []
    links = parameter_set.evidence_links or {}
    if not isinstance(links, dict):
        return found
    for payload in links.values():
        if not isinstance(payload, dict):
            continue
        raw_ids = payload.get("observation_ids") or []
        if not isinstance(raw_ids, list):
            continue
        for raw in raw_ids:
            try:
                found.append(UUID(str(raw)))
            except ValueError:
                continue
    return found


def _jsonable(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, date):
            out[key] = value.isoformat()
        elif isinstance(value, UUID):
            out[key] = str(value)
        else:
            out[key] = value
    return out
