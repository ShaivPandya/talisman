"""Booking Holdings Ex. 99.1 helpers for the Booking disclosure review.

Provides guidance-table detection for the release calendar, quote parsers for
measured/guidance percentages, and Pydantic models for observation fixtures that
validate against ``ObservationCreate``.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from longaeva_app.api.schemas import ObservationCreate, StatementType

PACKAGE_ROOT = Path(__file__).resolve().parents[3]  # longaeva/
OBSERVATIONS_DIR = PACKAGE_ROOT / "data" / "fixtures" / "observations"

BOOKING_CIK = 1075531
EXTRACTOR_ID = "manual_gate"
EXTRACTOR_VERSION = "lon-4-v1"

# Stable namespace for fixture source UUIDs.
SOURCE_UUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

BasisToken = Literal["units", "as_reported", "constant_currency"]
GuidanceCoverage = Literal["true", "false", "unknown", "n/a"]

_GUIDANCE_TABLE_RE = re.compile(
    r"guidance for the (first|second|third|fourth) quarter(?: and full year)? of (\d{4})",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*%$")
_PERCENT_RANGE_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*%?\s*[-–—]\s*(-?\d+(?:\.\d+)?)\s*%$")
_QUARTER_WORD = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
}


def source_uuid_for_url(url: str) -> UUID:
    """Deterministic UUIDv5 for a fixture source URL."""
    return uuid.uuid5(SOURCE_UUID_NAMESPACE, url)


def archive_url(accession: str, document: str) -> str:
    nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{BOOKING_CIK}/{nodash}/{document}"


def parse_percent_quote(quote: str) -> float:
    """Parse a measured percent quote like ``8%`` or ``9`` into a float."""
    cleaned = quote.strip().replace(",", "")
    match = _PERCENT_RE.match(cleaned)
    if match:
        return float(match.group(1))
    try:
        return float(cleaned)
    except ValueError as exc:
        raise ValueError(f"not a percent quote: {quote!r}") from exc


def parse_percent_range_quote(quote: str) -> tuple[float, float]:
    """Parse a guidance range like ``4% - 6%`` or ``4-6%`` into (low, high)."""
    cleaned = quote.strip().replace(",", "")
    match = _PERCENT_RANGE_RE.match(cleaned)
    if not match:
        raise ValueError(f"not a percent range quote: {quote!r}")
    low = float(match.group(1))
    high = float(match.group(2))
    if low > high:
        raise ValueError(f"range low > high: {quote!r}")
    return low, high


def detect_guidance(text: str) -> dict[str, str]:
    """Detect an Ex. 99.1 outlook table and return calendar metadata fields.

    Returns keys: ``guidance_table`` (``true``/``false``), ``guidance_quarter``
    (e.g. ``2025Q4`` or empty), ``guidance_full_year`` (``true``/``false``/empty).
    """
    match = _GUIDANCE_TABLE_RE.search(text)
    if not match:
        return {
            "guidance_table": "false",
            "guidance_quarter": "",
            "guidance_full_year": "",
        }
    quarter = _QUARTER_WORD[match.group(1).lower()]
    year = int(match.group(2))
    full_year = "and full year" in match.group(0).lower()
    return {
        "guidance_table": "true",
        "guidance_quarter": f"{year}Q{quarter}",
        "guidance_full_year": "true" if full_year else "false",
    }


def reported_quarter_from_period_end(period_of_report: str, filed_date: str) -> str:
    """Map a Booking period-of-report / filing date to a calendar quarter label.

    Booking's ``reportDate`` on earnings 8-Ks is usually the event/filing date,
    not the fiscal period end. Infer the most recent calendar quarter-end
    strictly before the filed date.
    """
    filed = date.fromisoformat(filed_date)
    candidates = [
        date(filed.year, 12, 31),
        date(filed.year, 9, 30),
        date(filed.year, 6, 30),
        date(filed.year, 3, 31),
        date(filed.year - 1, 12, 31),
        date(filed.year - 1, 9, 30),
    ]
    prior = [c for c in candidates if c < filed]
    if not prior:
        raise ValueError(f"no prior quarter-end for filed date {filed_date}")
    period = max(prior)
    # Prefer an explicit quarter-end period_of_report when present.
    if period_of_report:
        try:
            por: date | None = date.fromisoformat(period_of_report)
        except ValueError:
            por = None
        if por is not None and (por.month, por.day) in {(3, 31), (6, 30), (9, 30), (12, 31)} and por < filed:
            period = por
    if period.month == 3:
        return f"{period.year}Q1"
    if period.month == 6:
        return f"{period.year}Q2"
    if period.month == 9:
        return f"{period.year}Q3"
    return f"{period.year}Q4"


def visa_target_to_calendar_quarter(fiscal_year: int, fiscal_quarter: int) -> str:
    """Map a Visa fiscal quarter (FY ends 30 Sep) to a calendar quarter label.

    Visa FY{Y}Q1 = Oct–Dec of Y−1 → calendar {(Y−1)}Q4
    Visa FY{Y}Q2 = Jan–Mar of Y   → calendar {Y}Q1
    Visa FY{Y}Q3 = Apr–Jun of Y   → calendar {Y}Q2
    Visa FY{Y}Q4 = Jul–Sep of Y   → calendar {Y}Q3
    """
    if fiscal_quarter == 1:
        return f"{fiscal_year - 1}Q4"
    if fiscal_quarter == 2:
        return f"{fiscal_year}Q1"
    if fiscal_quarter == 3:
        return f"{fiscal_year}Q2"
    if fiscal_quarter == 4:
        return f"{fiscal_year}Q3"
    raise ValueError(f"invalid fiscal quarter: {fiscal_quarter}")


def guidance_covers_target(
    guidance_quarter: str,
    target_fiscal_year: int,
    target_fiscal_quarter: int,
) -> str:
    """Return ``true``/``false``/``unknown`` for whether guidance covers Visa's target."""
    if not guidance_quarter:
        return "false"
    target = visa_target_to_calendar_quarter(target_fiscal_year, target_fiscal_quarter)
    return "true" if guidance_quarter == target else "false"


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
    form: str = "8-K Ex. 99.1"
    acceptance_utc: str
    url: str
    role: Literal["input", "post_cutoff_check"]
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


class BookingObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    statement_type: StatementType
    activity_type: str | None = None
    geography: str = "global"
    period_start: date
    period_end: date
    value: float | None = None
    range_low: float | None = None
    range_high: float | None = None
    unit: str
    basis: BasisToken
    source_family: str = "booking"
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


class BookingObservationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    company: str = "booking"
    release_date: str
    source: SourceRef
    visa_origins: list[OriginTiming]
    observations: list[BookingObservation]
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _at_least_one_observation(self) -> BookingObservationFixture:
        if not self.observations:
            raise ValueError("fixture must contain at least one observation")
        return self


def to_observation_create(entry: BookingObservation, source_url: str) -> ObservationCreate:
    """Validate a fixture observation against the API contract."""
    return ObservationCreate(
        company="booking",
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
            "anchor": entry.span.anchor,
            "quote": entry.span.quote,
            "note": entry.note,
        },
    )


def load_fixture(path: Path) -> BookingObservationFixture:
    return BookingObservationFixture.model_validate_json(path.read_text(encoding="utf-8"))


def required_fixture_paths() -> list[Path]:
    return [
        OBSERVATIONS_DIR / "booking_2024-05-02.json",
        OBSERVATIONS_DIR / "booking_2025-10-28.json",
    ]
