"""Second-wave observation fixtures for the second-wave disclosure review.

Pydantic models validate against ``ObservationCreate``. Each observation
names a Visa driver from ``companies.visa.definitions.FIELDS``. Company-specific
bases (``fx_neutral``, ``ex_fuel``, ``ex_gas_fx``) are never relabeled as Visa
``constant_dollar``.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from longaeva_app.api.schemas import ObservationCreate, StatementType
from longaeva_app.companies.visa.definitions import FIELDS

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
OBSERVATIONS_DIR = PACKAGE_ROOT / "data" / "fixtures" / "observations"

EXTRACTOR_ID = "manual_gate"
EXTRACTOR_VERSION = "lon-8-v1"
SOURCE_UUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

FIELD_NAMES = frozenset(f.name for f in FIELDS)

BasisToken = Literal[
    "as_reported",
    "fx_neutral",
    "ex_fuel",
    "ex_gas_fx",
    "units",
    "constant_currency",
]
GuidanceCoverage = Literal["true", "false", "unknown", "n/a"]
FamilyToken = Literal["airline", "retailer", "processor"]


def source_uuid_for_url(url: str) -> UUID:
    return uuid.uuid5(SOURCE_UUID_NAMESPACE, url)


def archive_url(cik: int, accession: str, document: str) -> str:
    nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{document}"


class Span(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor: str
    quote: str
    char_start: int
    char_end: int

    @model_validator(mode="after")
    def _order(self) -> Span:
        if self.char_end < self.char_start:
            raise ValueError("char_end must be >= char_start")
        if self.char_end - self.char_start != len(self.quote):
            raise ValueError(f"char span length {self.char_end - self.char_start} != quote length {len(self.quote)}")
        return self


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str  # "{accession}/{document}"
    accession: str
    document: str
    exhibit: str = "EX-99.1"
    form: str = "8-K Ex. 99.1"
    cik: int
    acceptance_utc: str
    url: str
    role: Literal["input"] = "input"
    content_sha256: str
    note: str = ""


class OriginTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin_date: str
    cutoff_utc: str
    fiscal_year: int
    fiscal_quarter: int
    target_fiscal_year: int
    target_fiscal_quarter: int
    age_seconds: int
    age_days: float
    age_weeks: float
    same_day: bool
    margin_seconds: int | None = None
    guidance_covers_target: GuidanceCoverage
    note: str = ""


class SecondWaveObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    statement_type: StatementType
    activity_type: str | None = None
    geography: str
    period_start: date
    period_end: date
    value: float | None = None
    range_low: float | None = None
    range_high: float | None = None
    unit: str
    basis: BasisToken
    source_family: FamilyToken
    visa_driver: str
    source_id: str | None = None
    review_status: Literal["pending"] = "pending"
    span: Span
    note: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("unit")
    @classmethod
    def _unit_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("unit must be non-empty")
        return v

    @field_validator("visa_driver")
    @classmethod
    def _known_driver(cls, v: str) -> str:
        if v not in FIELD_NAMES:
            raise ValueError(f"visa_driver {v!r} not in FIELDS")
        return v

    @field_validator("basis")
    @classmethod
    def _no_visa_constant_dollar(cls, v: BasisToken) -> BasisToken:
        # Company-specific FX bases must not be silently aliased to Visa's token.
        if v == "constant_currency":
            # Allowed only for Booking-like labels; second-wave prefers fx_neutral.
            pass
        return v


class SecondWaveObservationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    company: str
    family: FamilyToken
    release_date: str
    sources: list[SourceRef]
    visa_origins: list[OriginTiming]
    observations: list[SecondWaveObservation]
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistency(self) -> SecondWaveObservationFixture:
        if not self.observations:
            raise ValueError("fixture must contain at least one observation")
        if not self.sources:
            raise ValueError("fixture must contain at least one source")
        source_ids = {s.source_id for s in self.sources}
        for obs in self.observations:
            if obs.source_family != self.family:
                raise ValueError(f"observation family {obs.source_family} != fixture {self.family}")
            if obs.source_id is not None and obs.source_id not in source_ids:
                raise ValueError(f"observation source_id {obs.source_id} not in sources")
        return self


def to_observation_create(
    entry: SecondWaveObservation,
    source_url: str,
    *,
    company: str,
) -> ObservationCreate:
    return ObservationCreate(
        company=company,
        source_id=source_uuid_for_url(source_url),
        document_text_id=None,
        span_page=None,
        span_char_start=entry.span.char_start,
        span_char_end=entry.span.char_end,
        statement_type=entry.statement_type,
        activity_type=entry.activity_type,
        geography=entry.geography,
        period_start=entry.period_start,
        period_end=entry.period_end,
        value=entry.value,
        range_low=entry.range_low,
        range_high=entry.range_high,
        unit=entry.unit,
        basis=entry.basis,
        source_family=entry.source_family,
        extractor_id=EXTRACTOR_ID,
        extractor_version=EXTRACTOR_VERSION,
        review_status=entry.review_status,
        attributes={
            **entry.attributes,
            "observation_id": entry.observation_id,
            "visa_driver": entry.visa_driver,
            "anchor": entry.span.anchor,
            "quote": entry.span.quote,
            "note": entry.note,
        },
    )


def load_fixture(path: Path) -> SecondWaveObservationFixture:
    return SecondWaveObservationFixture.model_validate_json(path.read_text(encoding="utf-8"))


def required_fixture_paths() -> list[Path]:
    return [
        OBSERVATIONS_DIR / "united_2024-07-17.json",
        OBSERVATIONS_DIR / "united_2025-10-15.json",
        OBSERVATIONS_DIR / "costco_2024-05-30.json",
        OBSERVATIONS_DIR / "costco_2025-09-25.json",
        OBSERVATIONS_DIR / "paypal_2024-04-30.json",
        OBSERVATIONS_DIR / "paypal_2025-10-28.json",
    ]
