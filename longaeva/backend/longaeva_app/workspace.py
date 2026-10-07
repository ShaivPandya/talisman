"""Bundled origins and resolved, read-only evidence for the browser workspace."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from functools import lru_cache
from html import unescape
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ParameterEvidence, ParameterSetRead
from longaeva_app.api.workspace_schemas import (
    EvidenceExcerpt,
    ParameterEvidenceRead,
    ParameterSpecRead,
    WorkspaceOriginRead,
    WorkspaceStateRead,
)
from longaeva_app.collect.visa_filings import source_bytes
from longaeva_app.companies.visa.calibration import artifact_path, load_observation_rows, persist_calibrated
from longaeva_app.companies.visa.parameters import VISA_PARAMETERS
from longaeva_app.companies.visa.starting_state import StartingStateFixture, StateValue, SupportingLevel
from longaeva_app.db.models import DocumentText, Observation, ParameterSet, Source
from longaeva_app.evaluation.harness import load_calibration_artifact
from longaeva_app.hashing import utc_isoformat
from longaeva_app.runs.inputs import load_origin_fixtures, parse_aware_utc


def available_origins() -> list[WorkspaceOriginRead]:
    return [
        WorkspaceOriginRead(
            origin_date=f.origin_date.isoformat(),
            cutoff_ts=f.cutoff_utc,
            label=f"FY{f.fiscal_year}Q{f.fiscal_quarter}",
        )
        for f in load_origin_fixtures()
        if artifact_path(f.origin_date.isoformat()).is_file()
    ]


def origin_fixture(origin_date: str) -> StartingStateFixture:
    for fixture in load_origin_fixtures():
        if fixture.origin_date.isoformat() == origin_date and artifact_path(origin_date).is_file():
            return fixture
    raise HTTPException(404, "Bundled origin not found")


def _plain(raw: str) -> str:
    # Responses are plain text, never trusted HTML. Slice at original offsets first.
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", " ", raw))).strip()


def _fill_excerpt(
    excerpt: EvidenceExcerpt,
    raw: str,
    start: int | None,
    end: int | None,
    *,
    offset: int = 0,
    html: bool = False,
    expected_quote: str | None = None,
) -> EvidenceExcerpt:
    if start is None or end is None or not 0 <= start - offset < end - offset <= len(raw):
        excerpt.unavailable_reason = "Stored source span is unavailable or outside the retained passage."
        return excerpt
    a, b = start - offset, end - offset
    if expected_quote is not None and raw[a:b] != expected_quote:
        excerpt.unavailable_reason = "Stored quote does not match the retained original."
        return excerpt
    excerpt.char_start, excerpt.char_end = start, end
    before, quote, after = raw[max(0, a - 1600) : a], raw[a:b], raw[b : b + 1600]
    if html:
        # Discard partial tags at the outer context edges.
        before = re.sub(r"^[^<]*>", "", before)
        after = re.sub(r"<[^>]*$", "", after)
        before, quote, after = _plain(before), _plain(quote), _plain(after)
    excerpt.before, excerpt.quote, excerpt.after = before[-500:], quote, after[:500]
    if not excerpt.quote.strip():
        excerpt.unavailable_reason = "Stored span contains no readable quoted text."
    return excerpt


@lru_cache(maxsize=1)
def _observation_quotes() -> dict[str, str]:
    return {str(row.observation_id): row.quote for row in load_observation_rows()}


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@lru_cache(maxsize=32)
def _original(source_id: str) -> tuple[str, str]:
    # Only keys resolved from retained manifests reach this function, never user paths.
    accession, document = source_id.split("/", 1)
    raw = source_bytes(accession, document)
    return raw.decode("utf-8", errors="replace"), hashlib.sha256(raw).hexdigest()


def bundled_excerpt(
    source_id: str,
    start: int | None,
    end: int | None,
    *,
    publication_ts: str,
    cutoff: datetime,
    observation_id: str | None = None,
    expected_quote: str | None = None,
    expected_hash: str | None = None,
) -> EvidenceExcerpt:
    excerpt = EvidenceExcerpt(source_id=source_id, observation_id=observation_id, publication_ts=publication_ts)
    if parse_aware_utc(publication_ts) > cutoff:
        excerpt.unavailable_reason = "Source was published after this cutoff."
        return excerpt
    try:
        raw, digest = _original(source_id)
    except (FileNotFoundError, ValueError, OSError):
        excerpt.unavailable_reason = "Original document is not available in this bundle."
        return excerpt
    accession, document = source_id.split("/", 1)
    excerpt.url = f"https://www.sec.gov/Archives/edgar/data/1403161/{accession.replace('-', '')}/{document}"
    excerpt.content_hash = digest
    if expected_hash is not None and digest != expected_hash:
        excerpt.unavailable_reason = "Retained original does not match its recorded content hash."
        return excerpt
    return _fill_excerpt(excerpt, raw, start, end, html=True, expected_quote=expected_quote)


def workspace_state(origin_date: str) -> WorkspaceStateRead:
    fixture = origin_fixture(origin_date)
    cutoff = parse_aware_utc(fixture.cutoff_utc)
    evidence: dict[str, EvidenceExcerpt] = {}
    entries: dict[str, StateValue | SupportingLevel] = {**fixture.values, **fixture.supporting_levels}
    for name, value in entries.items():
        if value.source_id is None or value.span is None:
            continue
        ref = fixture.sources[value.source_id]
        evidence[name] = bundled_excerpt(
            value.source_id,
            value.span.char_start,
            value.span.char_end,
            publication_ts=ref.acceptance_utc,
            cutoff=cutoff,
            expected_quote=value.span.quote,
            expected_hash=ref.content_sha256,
        )
    return WorkspaceStateRead(
        origin_date=origin_date,
        cutoff_ts=fixture.cutoff_utc,
        label=f"FY{fixture.fiscal_year}Q{fixture.fiscal_quarter}",
        values=fixture.values,
        supporting_levels=fixture.supporting_levels,
        evidence=evidence,
        sources={k: v for k, v in fixture.sources.items() if v.role == "input"},
        post_cutoff_sources={k: v for k, v in fixture.sources.items() if v.role == "post_cutoff_check"},
        parameter_specs=[ParameterSpecRead(**asdict(spec)) for spec in VISA_PARAMETERS],
        notes=fixture.notes,
    )


def prepare_origin(session: Session, origin_date: str) -> ParameterSetRead:
    fixture = origin_fixture(origin_date)
    calibrated = load_calibration_artifact(artifact_path(origin_date))
    if (
        calibrated.origin_date != origin_date
        or calibrated.cutoff_ts != parse_aware_utc(fixture.cutoff_utc)
        or calibrated.pooled.cutoff_ts != calibrated.cutoff_ts
        or calibrated.pooled.company != "visa"
    ):
        raise HTTPException(409, "Bundled calibration does not match the origin cutoff")
    # Serialize concurrent browser preparations (including React StrictMode) without a migration.
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int(origin_date.replace("-", ""))})
    parameter_set, _scenario = persist_calibrated(calibrated, session)
    session.commit()
    return ParameterSetRead.model_validate(parameter_set)


def _database_excerpt(session: Session, obs: Observation, cutoff: datetime) -> EvidenceExcerpt:
    source = session.get(Source, obs.source_id) if obs.source_id else None
    passage = session.get(DocumentText, obs.document_text_id) if obs.document_text_id else None
    excerpt = EvidenceExcerpt(
        observation_id=str(obs.id),
        source_id=str(obs.source_id) if obs.source_id else None,
        document_text_id=str(obs.document_text_id) if obs.document_text_id else None,
        page=obs.span_page,
    )
    if source is None:
        excerpt.unavailable_reason = "Observation has no retained source."
        return excerpt
    excerpt.url = source.url
    excerpt.publication_ts = utc_isoformat(source.publication_ts)
    excerpt.content_hash = source.content_hash
    if _utc(source.publication_ts) > cutoff:
        excerpt.unavailable_reason = "Source was published after this cutoff."
    elif passage is None or passage.source_id != source.id:
        excerpt.unavailable_reason = "Observation has no retained passage."
    elif obs.span_page != passage.page:
        excerpt.unavailable_reason = "Stored source page does not match the retained passage."
    else:
        _fill_excerpt(excerpt, passage.text, obs.span_char_start, obs.span_char_end, offset=passage.char_start)
    return excerpt


def observation_evidence(session: Session, observation_id: uuid.UUID, cutoff: datetime) -> EvidenceExcerpt:
    observation = session.get(Observation, observation_id)
    if observation is None:
        raise HTTPException(404, "Observation not found")
    return _database_excerpt(session, observation, _utc(cutoff))


def parameter_evidence(session: Session, parameter_set_id: uuid.UUID, parameter: str) -> ParameterEvidenceRead:
    # Reuse the update contract so the UI and future review page share provenance.
    from longaeva_app.api.routers.parameters import list_parameter_updates

    row = session.get(ParameterSet, parameter_set_id)
    if row is None:
        raise HTTPException(404, "Parameter set not found")
    if parameter not in row.values or parameter not in row.evidence_links:
        raise HTTPException(404, "Parameter not found in this set")
    link = ParameterEvidence.model_validate(row.evidence_links[parameter])
    cutoff = _utc(row.cutoff_ts)
    index: dict[str, Any] = {}
    path = artifact_path(cutoff.date().isoformat())
    if row.company == "visa" and path.is_file():
        index = json.loads(path.read_text(encoding="utf-8")).get("evidence_index", {})
    excerpts: list[EvidenceExcerpt] = []
    for obs_id in link.observation_ids:
        obs = session.get(Observation, obs_id)
        if obs is not None:
            excerpts.append(_database_excerpt(session, obs, cutoff))
        elif (entry := index.get(str(obs_id))) is not None:
            excerpts.append(
                bundled_excerpt(
                    entry["source_id"],
                    entry.get("char_start"),
                    entry.get("char_end"),
                    publication_ts=entry["publication_ts"],
                    cutoff=cutoff,
                    observation_id=str(obs_id),
                    expected_quote=_observation_quotes().get(str(obs_id)),
                )
            )
        else:
            excerpts.append(
                EvidenceExcerpt(
                    observation_id=str(obs_id),
                    unavailable_reason="Evidence reference is not available in the database or bundle.",
                )
            )
    updates = [u for u in list_parameter_updates(parameter_set_id, session) if u.target_parameter == parameter]
    return ParameterEvidenceRead(parameter=parameter, evidence=link, excerpts=excerpts, updates=updates)
