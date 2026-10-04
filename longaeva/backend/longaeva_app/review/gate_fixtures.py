"""Load LON-4, LON-5 and LON-8 gate fixtures as source and observation rows.

Idempotent by source content hash and ``attributes.fixture_observation_id``.
Accept decisions are recorded only when requested, and only while the row is pending.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ObservationCreate
from longaeva_app.db.models import Observation, Source
from longaeva_app.extract.booking_release import EXTRACTOR_ID as BOOKING_EXTRACTOR_ID
from longaeva_app.extract.booking_release import EXTRACTOR_VERSION as BOOKING_EXTRACTOR_VERSION
from longaeva_app.extract.booking_release import load_fixture as load_booking_fixture
from longaeva_app.extract.booking_release import required_fixture_paths as booking_paths
from longaeva_app.extract.booking_release import to_observation_create as booking_observation
from longaeva_app.extract.second_wave_release import EXTRACTOR_ID as WAVE_EXTRACTOR_ID
from longaeva_app.extract.second_wave_release import EXTRACTOR_VERSION as WAVE_EXTRACTOR_VERSION
from longaeva_app.extract.second_wave_release import load_fixture as load_wave_fixture
from longaeva_app.extract.second_wave_release import required_fixture_paths as wave_paths
from longaeva_app.extract.second_wave_release import to_observation_create as wave_observation
from longaeva_app.hashing import sha256_hex
from longaeva_app.review.rules import PACKAGE_ROOT
from longaeva_app.review.service import record_decision
from longaeva_app.runs.inputs import parse_aware_utc

CENSUS_DIR = PACKAGE_ROOT / "data" / "fixtures" / "census"
GATE_RATIONALE = "Accepted from the LON-4/LON-5/LON-8 gate reviewer checklist."
GATE_DECIDED_BY = "lon-21-gate-fixtures"
CENSUS_EXTRACTOR_ID = "census_marts"
CENSUS_EXTRACTOR_VERSION = "lon-5-v1"

_FAMILY_OF = {
    "booking": "booking",
    "census": "census",
    "airline": "airline",
    "retailer": "retailer",
    "processor": "processor",
}


def load_gate_fixtures(
    session: Session,
    *,
    accept: bool = False,
    families: set[str] | None = None,
) -> dict[str, Observation]:
    """Insert gate sources and observations. Return rows keyed by fixture observation id."""
    wanted = set(_FAMILY_OF) if families is None else {item.strip().lower() for item in families}
    found: dict[str, Observation] = {}
    if "booking" in wanted:
        for path in booking_paths():
            found.update(_load_booking(session, path, accept=accept))
    if "census" in wanted:
        for path in sorted(CENSUS_DIR.glob("adv*.csv")):
            row = _load_census(session, path, accept=accept)
            if row is not None:
                found[str(row.attributes["fixture_observation_id"])] = row
    if wanted.intersection({"airline", "retailer", "processor"}):
        for path in wave_paths():
            fixture = load_wave_fixture(path)
            if fixture.family not in wanted:
                continue
            found.update(_load_wave(session, path, accept=accept))
    return found


def _load_booking(session: Session, path: Path, *, accept: bool) -> dict[str, Observation]:
    fixture = load_booking_fixture(path)
    published = parse_aware_utc(fixture.source.acceptance_utc)
    source = _upsert_source(
        session,
        provider="sec",
        company=fixture.company,
        doc_type=fixture.source.form,
        url=fixture.source.url,
        publication_ts=published,
        content_hash=fixture.source.content_sha256,
        original_path=str(path.relative_to(PACKAGE_ROOT)),
        license_note="SEC EDGAR exhibit retained for the Booking gate (LON-4).",
        attributes={
            "accession": fixture.source.accession,
            "document": fixture.source.document,
            "fixture_source_id": fixture.source.source_id,
            "role": fixture.source.role,
        },
    )
    found: dict[str, Observation] = {}
    for entry in fixture.observations:
        create = booking_observation(entry, fixture.source.url)
        row = _upsert_observation(
            session,
            source,
            create,
            fixture_observation_id=entry.observation_id,
            extractor_id=BOOKING_EXTRACTOR_ID,
            extractor_version=BOOKING_EXTRACTOR_VERSION,
            accept=accept,
        )
        found[entry.observation_id] = row
    return found


def _load_wave(session: Session, path: Path, *, accept: bool) -> dict[str, Observation]:
    fixture = load_wave_fixture(path)
    sources = {
        ref.source_id: _upsert_source(
            session,
            provider="sec",
            company=fixture.company,
            doc_type=ref.form,
            url=ref.url,
            publication_ts=parse_aware_utc(ref.acceptance_utc),
            content_hash=ref.content_sha256,
            original_path=str(path.relative_to(PACKAGE_ROOT)),
            license_note="SEC EDGAR exhibit retained for the second-wave gate (LON-8).",
            attributes={
                "accession": ref.accession,
                "document": ref.document,
                "fixture_source_id": ref.source_id,
                "role": ref.role,
            },
        )
        for ref in fixture.sources
    }
    default_source = next(iter(sources.values()))
    found: dict[str, Observation] = {}
    for entry in fixture.observations:
        create = wave_observation(entry, _source_url(fixture, entry.source_id), company=fixture.company)
        source = sources.get(entry.source_id or "") or default_source
        row = _upsert_observation(
            session,
            source,
            create,
            fixture_observation_id=entry.observation_id,
            extractor_id=WAVE_EXTRACTOR_ID,
            extractor_version=WAVE_EXTRACTOR_VERSION,
            accept=accept,
        )
        found[entry.observation_id] = row
    return found


def _source_url(fixture: Any, source_id: str | None) -> str:
    for ref in fixture.sources:
        if source_id is None or ref.source_id == source_id:
            return str(ref.url)
    return str(fixture.sources[0].url)


def _load_census(session: Session, path: Path, *, accept: bool) -> Observation | None:
    target = _census_row(path)
    if target is None:
        return None
    published = parse_aware_utc(target["publication_ts"])
    release_id = target["release_id"]
    fixture_id = f"census:{release_id}:retail_food_services_total:yoy_3m_pct"
    source = _upsert_source(
        session,
        provider="census_bureau",
        company="census",
        doc_type="MARTS advance release",
        url=f"https://www.census.gov/retail/marts/historic_releases/{release_id}.pdf",
        publication_ts=published,
        content_hash=sha256_hex(path.read_bytes()),
        original_path=str(path.relative_to(PACKAGE_ROOT)),
        license_note="Census Bureau advance MARTS CSV fixture (public domain). Not the revised workbook.",
        attributes={"release_id": release_id, "release_number": target.get("release_number", "")},
        period_start=date.fromisoformat(target["period_start"]),
        period_end=date.fromisoformat(target["period_end"]),
    )
    create = ObservationCreate(
        company="census",
        source_id=source.id,
        statement_type="measured",
        activity_type="retail_food_services_total",
        geography=target.get("geography") or "US",
        period_start=date.fromisoformat(target["period_start"]),
        period_end=date.fromisoformat(target["period_end"]),
        value=float(target["value"]),
        unit=target.get("unit") or "pct",
        basis="sa",
        source_family="census",
        extractor_id=CENSUS_EXTRACTOR_ID,
        extractor_version=CENSUS_EXTRACTOR_VERSION,
        review_status="pending",
        attributes={
            "fixture_observation_id": fixture_id,
            "measure": "yoy_3m_pct",
            "estimate_status": "three_month",
            "series_key": "retail_food_services_total",
            "release_id": release_id,
        },
    )
    return _upsert_observation(
        session,
        source,
        create,
        fixture_observation_id=fixture_id,
        extractor_id=CENSUS_EXTRACTOR_ID,
        extractor_version=CENSUS_EXTRACTOR_VERSION,
        accept=accept,
    )


def _census_row(path: Path) -> dict[str, str] | None:
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("series_key") != "retail_food_services_total":
                continue
            if row.get("measure") != "yoy_3m_pct" or row.get("basis") != "sa":
                continue
            if row.get("estimate_status") != "three_month":
                continue
            if (row.get("value_flag") or "").strip() or not (row.get("value") or "").strip():
                continue
            return row
    return None


def _upsert_source(
    session: Session,
    *,
    provider: str,
    company: str,
    doc_type: str,
    url: str,
    publication_ts: Any,
    content_hash: str,
    original_path: str,
    license_note: str,
    attributes: dict[str, Any],
    period_start: date | None = None,
    period_end: date | None = None,
) -> Source:
    existing = session.execute(select(Source).where(Source.content_hash == content_hash)).scalar_one_or_none()
    if existing is not None:
        return existing
    row = Source(
        provider=provider,
        company=company,
        doc_type=doc_type,
        url=url,
        publication_ts=publication_ts,
        retrieval_ts=publication_ts + timedelta(seconds=1),
        period_start=period_start,
        period_end=period_end,
        content_hash=content_hash,
        original_path=original_path,
        license_note=license_note,
        attributes=attributes,
    )
    session.add(row)
    session.flush()
    return row


def _upsert_observation(
    session: Session,
    source: Source,
    create: ObservationCreate,
    *,
    fixture_observation_id: str,
    extractor_id: str,
    extractor_version: str,
    accept: bool,
) -> Observation:
    existing = session.scalars(
        select(Observation).where(
            Observation.source_id == source.id,
            Observation.attributes["fixture_observation_id"].astext == fixture_observation_id,
        )
    ).first()
    if existing is None:
        attributes = dict(create.attributes)
        attributes["fixture_observation_id"] = fixture_observation_id
        existing = Observation(
            company=create.company,
            source_id=source.id,
            document_text_id=None,
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
            extractor_id=extractor_id,
            extractor_version=extractor_version,
            review_status="pending",
            attributes=attributes,
        )
        session.add(existing)
        session.flush()
    if accept and existing.review_status == "pending":
        record_decision(
            session,
            observation_id=existing.id,
            decision="accept",
            rationale=GATE_RATIONALE,
            decided_by=GATE_DECIDED_BY,
        )
    return existing


__all__ = [
    "GATE_DECIDED_BY",
    "GATE_RATIONALE",
    "load_gate_fixtures",
]
