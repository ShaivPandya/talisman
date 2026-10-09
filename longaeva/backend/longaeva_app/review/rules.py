"""Code-defined mapping rules.

Rules live in this module and are synced into ``mapping_rule`` by
``(rule_key, version)``. A definition change without a version bump is refused.
Estimated rules fit a coefficient on history published at or before the cutoff
and fall back to an analyst range until at least 12 aligned quarters exist.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.definitions import VISA_FISCAL_CALENDAR
from longaeva_app.companies.visa.parameters import VISA_PARAMETERS
from longaeva_app.db.models import MappingRule
from longaeva_app.hashing import content_hash
from longaeva_app.runs.inputs import parse_aware_utc

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES = PACKAGE_ROOT / "data" / "fixtures"
_ORIGINS_CSV = _FIXTURES / "origins.csv"
_VISA_OBSERVATIONS_CSV = _FIXTURES / "visa_releases" / "observations.csv"
_BOOKING_OBSERVATIONS = _FIXTURES / "observations"
_CENSUS_DIR = _FIXTURES / "census"

MIN_ALIGNED_QUARTERS = 12
_Z_95 = 1.96
_BANNED_FIELDS = frozenset({"confidence", "probability"})
_PERCENT_UNITS = frozenset({"percent", "pct"})
_FY_LABEL = re.compile(r"^FY(\d{4})Q([1-4])$")

RuleKind = Literal["estimated", "analyst_range", "context"]

# Neutral room-nights growth. The two retained prints are 9% and 8%.
BOOKING_ANCHOR = 8.0 / 100.0
BOOKING_BETA_LOW = 0.2
BOOKING_BETA_HIGH = 0.4
BOOKING_MAX_SHIFT = 4.0 / 100.0
BOOKING_SCALE = 1.0

# Neutral SA retail growth, and an explicit assumption for the US share of Visa volume.
CENSUS_ANCHOR = 3.0 / 100.0
US_PAYMENTS_VOLUME_SHARE = 0.45
CENSUS_BETA_LOW = 0.25
CENSUS_BETA_HIGH = 0.75
CENSUS_MAX_SHIFT = 4.0 / 100.0

_PARAMETER_SPECS = {spec.name: spec for spec in VISA_PARAMETERS}


class RuleRegistryError(Exception):
    """A stored rule definition does not match the code registry."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def reject_probability_fields(payload: Any) -> None:
    """extractor confidence is never a probability or a transform input."""
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key) in _BANNED_FIELDS:
                raise ValueError(f"{key} is not allowed on a mapping rule (MR-12)")
            reject_probability_fields(value)
        return
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for item in payload:
            reject_probability_fields(item)


@dataclass(frozen=True, slots=True)
class AnalystRange:
    """Direction and range labeled as an assumption. ``signal = (observed - anchor) * scale``."""

    anchor: float
    scale: float
    beta_low: float
    beta_high: float
    max_abs_shift: float

    def __post_init__(self) -> None:
        if self.beta_low > self.beta_high:
            raise ValueError("beta_low must be <= beta_high")
        if self.max_abs_shift < 0.0:
            raise ValueError("max_abs_shift must be >= 0")
        reject_probability_fields(self.as_dict())

    def as_dict(self) -> dict[str, float | str]:
        return {
            "op": "analyst_range",
            "anchor": self.anchor,
            "scale": self.scale,
            "beta_low": self.beta_low,
            "beta_high": self.beta_high,
            "max_abs_shift": self.max_abs_shift,
        }


@dataclass(frozen=True, slots=True)
class Estimated:
    """OLS slope of a Visa driver on an external series, with an analyst-range fallback."""

    visa_field: str
    alignment: Literal["next_visa_quarter", "containing_visa_quarter"]
    fallback: AnalystRange
    min_quarters: int = MIN_ALIGNED_QUARTERS

    def __post_init__(self) -> None:
        if self.min_quarters < 3:
            raise ValueError("min_quarters must be >= 3 so the slope has a standard error")
        if not self.visa_field.strip():
            raise ValueError("visa_field is required")
        reject_probability_fields(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "op": "estimated",
            "visa_field": self.visa_field,
            "alignment": self.alignment,
            "min_quarters": self.min_quarters,
            "fallback": self.fallback.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class RuleSpec:
    rule_key: str
    version: int
    kind: RuleKind
    source_family: str
    input_type: str
    rationale: str
    value_test: str
    target_parameter: str | None = None
    priority: int = 0
    activity_type: str | None = None
    basis: str | None = None
    unit: str | None = None
    attribute_equals: tuple[tuple[str, str], ...] = ()
    requires_guidance_covers_target: bool = False
    analyst_range: AnalystRange | None = None
    estimated: Estimated | None = None

    def __post_init__(self) -> None:
        validate_rule(self)

    def transform_dict(self) -> dict[str, Any]:
        if self.kind == "context":
            return {"op": "context"}
        if self.kind == "analyst_range":
            assert self.analyst_range is not None
            return dict(self.analyst_range.as_dict())
        assert self.estimated is not None
        return self.estimated.as_dict()

    def definition_payload(self) -> dict[str, Any]:
        return {
            "activity_type": self.activity_type,
            "attribute_equals": [list(pair) for pair in self.attribute_equals],
            "basis": self.basis,
            "input_type": self.input_type,
            "kind": self.kind,
            "priority": self.priority,
            "rationale": self.rationale,
            "requires_guidance_covers_target": self.requires_guidance_covers_target,
            "rule_key": self.rule_key,
            "source_family": self.source_family,
            "target_parameter": self.target_parameter,
            "transform": self.transform_dict(),
            "unit": self.unit,
            "value_test": self.value_test,
            "version": self.version,
        }

    def definition_hash(self) -> str:
        return content_hash(self.definition_payload())


def validate_rule(spec: RuleSpec) -> None:
    if spec.version < 1:
        raise ValueError(f"{spec.rule_key}: version must be >= 1")
    if not spec.rule_key.strip() or not spec.rationale.strip() or not spec.value_test.strip():
        raise ValueError(f"{spec.rule_key}: rule_key, rationale and value_test are required")
    if not spec.source_family.strip():
        raise ValueError(f"{spec.rule_key}: source_family is required")
    if spec.kind == "context":
        if spec.target_parameter is not None:
            raise ValueError(f"{spec.rule_key}: context rules have no target parameter")
        if spec.analyst_range is not None or spec.estimated is not None:
            raise ValueError(f"{spec.rule_key}: context rules have no transform")
        if spec.input_type != "*":
            raise ValueError(f"{spec.rule_key}: context rules use input_type '*'")
    elif spec.target_parameter not in _PARAMETER_SPECS:
        raise ValueError(f"{spec.rule_key}: target {spec.target_parameter!r} is not a Visa parameter")
    elif spec.kind == "analyst_range":
        if spec.analyst_range is None or spec.estimated is not None:
            raise ValueError(f"{spec.rule_key}: analyst_range rules carry only an AnalystRange")
    elif spec.kind == "estimated":
        if spec.estimated is None or spec.analyst_range is not None:
            raise ValueError(f"{spec.rule_key}: estimated rules carry an Estimated transform")
        if spec.input_type == "qualitative":
            raise ValueError(f"{spec.rule_key}: qualitative input cannot be estimated (MR-12)")
    else:
        raise ValueError(f"{spec.rule_key}: unknown kind {spec.kind!r}")
    reject_probability_fields(spec.transform_dict())


@dataclass(frozen=True, slots=True)
class FitResult:
    slope: float
    intercept: float
    stderr: float
    n: int
    mean_x: float
    sufficient: bool


def fit_coefficient(
    pairs: Sequence[tuple[float, float]],
    *,
    min_quarters: int = MIN_ALIGNED_QUARTERS,
) -> FitResult:
    """OLS slope of ``y`` on ``x`` with an intercept. Insufficient below ``min_quarters``."""
    n = len(pairs)
    if n < min_quarters or min_quarters < 3:
        return FitResult(slope=0.0, intercept=0.0, stderr=0.0, n=n, mean_x=0.0, sufficient=False)
    xs = np.asarray([pair[0] for pair in pairs], dtype=np.float64)
    ys = np.asarray([pair[1] for pair in pairs], dtype=np.float64)
    mean_x = float(xs.mean())
    mean_y = float(ys.mean())
    centered = xs - mean_x
    sxx = float(np.dot(centered, centered))
    # Identical inputs can leave a few ulps of variance. That is not a slope.
    if sxx <= 1e-18:
        return FitResult(slope=0.0, intercept=0.0, stderr=0.0, n=n, mean_x=mean_x, sufficient=False)
    slope = float(np.dot(centered, ys - mean_y) / sxx)
    intercept = mean_y - slope * mean_x
    resid = ys - (intercept + slope * xs)
    dof = n - 2
    sse = float(np.dot(resid, resid))
    stderr = float(np.sqrt(sse / dof / sxx)) if dof > 0 else 0.0
    return FitResult(
        slope=slope,
        intercept=intercept,
        stderr=stderr,
        n=n,
        mean_x=mean_x,
        sufficient=True,
    )


@dataclass(frozen=True, slots=True)
class TransformResult:
    value: float
    stored_range: tuple[float, float]
    after_value: dict[str, Any]
    assumption: bool
    size: float


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def apply_analyst_range(
    transform: AnalystRange,
    *,
    before: float,
    range_low: float,
    range_high: float,
    observed: float,
    half_width: float,
    bounds: tuple[float, float],
    extra: Mapping[str, Any] | None = None,
) -> TransformResult:
    """Mean shift is ``mid(beta) * signal``, capped. The stored range widens to the beta ends."""
    signal = (observed - transform.anchor) * transform.scale
    beta_mid = (transform.beta_low + transform.beta_high) / 2.0
    raw_shift = beta_mid * signal
    shift = _clamp(raw_shift, -transform.max_abs_shift, transform.max_abs_shift)
    new_value = _clamp(before + shift, bounds[0], bounds[1])
    pad = half_width * transform.scale * max(abs(transform.beta_low), abs(transform.beta_high))
    beta_shifts = (transform.beta_low * signal, transform.beta_high * signal)
    end_low = before + min(beta_shifts) - pad
    end_high = before + max(beta_shifts) + pad
    rule_low = _clamp(min(end_low, new_value), bounds[0], bounds[1])
    rule_high = _clamp(max(end_high, new_value), bounds[0], bounds[1])
    stored_low = _clamp(min(range_low, rule_low), bounds[0], bounds[1])
    stored_high = _clamp(max(range_high, rule_high), bounds[0], bounds[1])
    after: dict[str, Any] = {
        "value": new_value,
        "range_low": rule_low,
        "range_high": rule_high,
        "kind": "analyst_range",
        "fallback": False,
        "observed": observed,
        "signal": signal,
    }
    if extra:
        after.update(dict(extra))
    return TransformResult(
        value=new_value,
        stored_range=(stored_low, stored_high),
        after_value=after,
        assumption=True,
        size=new_value - before,
    )


def apply_estimated(
    transform: Estimated,
    *,
    before: float,
    range_low: float,
    range_high: float,
    observed: float,
    half_width: float,
    bounds: tuple[float, float],
    pairs: Sequence[tuple[float, float]],
) -> TransformResult:
    """Fit when enough aligned quarters exist; otherwise the analyst-range fallback (assumption)."""
    fit = fit_coefficient(pairs, min_quarters=transform.min_quarters)
    if not fit.sufficient:
        fallback = apply_analyst_range(
            transform.fallback,
            before=before,
            range_low=range_low,
            range_high=range_high,
            observed=observed,
            half_width=half_width,
            bounds=bounds,
            extra={"fallback": True, "n_aligned": fit.n, "kind": "analyst_range"},
        )
        return fallback
    delta = observed - fit.mean_x
    raw_shift = fit.slope * delta
    shift = _clamp(raw_shift, -transform.fallback.max_abs_shift, transform.fallback.max_abs_shift)
    new_value = _clamp(before + shift, bounds[0], bounds[1])
    band = _Z_95 * fit.stderr
    end_shifts = ((fit.slope - band) * delta, (fit.slope + band) * delta)
    rule_low = _clamp(before + min(end_shifts), bounds[0], bounds[1])
    rule_high = _clamp(before + max(end_shifts), bounds[0], bounds[1])
    rule_low = min(rule_low, new_value)
    rule_high = max(rule_high, new_value)
    stored_low = _clamp(min(range_low, rule_low), bounds[0], bounds[1])
    stored_high = _clamp(max(range_high, rule_high), bounds[0], bounds[1])
    after: dict[str, Any] = {
        "value": new_value,
        "range_low": rule_low,
        "range_high": rule_high,
        "kind": "estimated",
        "fallback": False,
        "n_aligned": fit.n,
        "slope": fit.slope,
        "stderr": fit.stderr,
        "mean_x": fit.mean_x,
        "observed": observed,
    }
    return TransformResult(
        value=new_value,
        stored_range=(stored_low, stored_high),
        after_value=after,
        assumption=False,
        size=new_value - before,
    )


def apply_transform(
    spec: RuleSpec,
    *,
    before: float,
    range_low: float,
    range_high: float,
    observed: float,
    half_width: float,
    pairs: Sequence[tuple[float, float]] | None = None,
    cutoff: datetime | None = None,
) -> TransformResult:
    bounds_spec = _PARAMETER_SPECS[spec.target_parameter or ""]
    bounds = (bounds_spec.lower, bounds_spec.upper)
    if spec.kind == "analyst_range":
        assert spec.analyst_range is not None
        return apply_analyst_range(
            spec.analyst_range,
            before=before,
            range_low=range_low,
            range_high=range_high,
            observed=observed,
            half_width=half_width,
            bounds=bounds,
        )
    if spec.kind == "estimated":
        assert spec.estimated is not None
        history = list(pairs) if pairs is not None else aligned_pairs(spec, _require_cutoff(cutoff))
        return apply_estimated(
            spec.estimated,
            before=before,
            range_low=range_low,
            range_high=range_high,
            observed=observed,
            half_width=half_width,
            bounds=bounds,
            pairs=history,
        )
    raise ValueError(f"{spec.rule_key} is context and has no transform")


def _require_cutoff(cutoff: datetime | None) -> datetime:
    if cutoff is None:
        raise ValueError("cutoff is required to align estimated-rule history")
    return cutoff


def bounds_for(parameter: str) -> tuple[float, float]:
    spec = _PARAMETER_SPECS[parameter]
    return (spec.lower, spec.upper)


@dataclass(frozen=True, slots=True)
class _ExternalPoint:
    period_end: date
    value_ratio: float
    published: datetime


def _to_ratio(value: float, unit: str) -> float:
    if unit in _PERCENT_UNITS:
        return value / 100.0
    return value


@lru_cache(maxsize=1)
def _origin_rows() -> tuple[dict[str, str], ...]:
    with _ORIGINS_CSV.open(newline="", encoding="utf-8") as handle:
        return tuple(csv.DictReader(handle))


@lru_cache(maxsize=1)
def _visa_publication() -> dict[tuple[int, int], tuple[datetime, bool]]:
    """Earliest origin cutoff for each fiscal quarter, and whether that origin is pandemic-flagged."""
    found: dict[tuple[int, int], tuple[datetime, bool]] = {}
    for row in _origin_rows():
        key = (int(row["fiscal_year"]), int(row["fiscal_quarter"]))
        published = parse_aware_utc(row["cutoff_utc"])
        pandemic = row.get("pandemic_flag", "").strip().lower() == "true"
        current = found.get(key)
        if current is None or published < current[0]:
            found[key] = (published, pandemic)
    return found


@lru_cache(maxsize=1)
def _visa_growth() -> dict[tuple[str, date], float]:
    """Disclosed Visa growth by ``(field, quarter-end)``, skipping comparative columns."""
    found: dict[tuple[str, date], float] = {}
    with _VISA_OBSERVATIONS_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("statement_type") != "measured":
                continue
            if row.get("vintage_role") == "comparative":
                continue
            label = row.get("period_label") or ""
            match = _FY_LABEL.match(label)
            if match is None:
                continue
            period = FiscalPeriod(int(match.group(1)), int(match.group(2)))
            quarter_end = VISA_FISCAL_CALENDAR.period_end(period)
            raw = (row.get("value") or "").strip()
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            found[(row["field"], quarter_end)] = _to_ratio(value, row.get("unit") or "percent")
    return found


def _visa_driver(field: str, quarter_end: date, cutoff: datetime) -> float | None:
    """Return the driver when its announcing release is at or before ``cutoff`` and not pandemic-flagged."""
    period = VISA_FISCAL_CALENDAR.period_containing(quarter_end)
    meta = _visa_publication().get((period.year, period.quarter))
    if meta is None:
        return None
    published, pandemic = meta
    if pandemic or published > cutoff:
        return None
    return _visa_growth().get((field, quarter_end))


def _next_quarter_end_after(day: date) -> date:
    for year in (day.year, day.year + 1):
        for month in (3, 6, 9, 12):
            end = date(year, month, 30 if month in {6, 9} else 31)
            if end > day:
                return end
    raise ValueError(f"no visa quarter end after {day.isoformat()}")


def _booking_room_nights(cutoff: datetime) -> list[_ExternalPoint]:
    points: list[_ExternalPoint] = []
    for path in sorted(_BOOKING_OBSERVATIONS.glob("booking_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        source = payload.get("source") or {}
        acceptance = source.get("acceptance_utc")
        if not isinstance(acceptance, str):
            continue
        published = parse_aware_utc(acceptance)
        if published > cutoff:
            continue
        for obs in payload.get("observations") or []:
            if not isinstance(obs, dict):
                continue
            if obs.get("statement_type") != "measured" or obs.get("activity_type") != "room_nights":
                continue
            if obs.get("value") is None:
                continue
            points.append(
                _ExternalPoint(
                    period_end=date.fromisoformat(str(obs["period_end"])),
                    value_ratio=_to_ratio(float(obs["value"]), str(obs.get("unit") or "percent")),
                    published=published,
                )
            )
    return points


def _census_retail_yoy(cutoff: datetime) -> list[_ExternalPoint]:
    from longaeva_app.extract.census_quarters import quarter_prints

    return [
        _ExternalPoint(
            period_end=date.fromisoformat(row.period_end),
            value_ratio=_to_ratio(float(row.value), row.unit),
            published=parse_aware_utc(row.publication_ts),
        )
        for row in quarter_prints(cutoff)
    ]


def aligned_pairs(spec: RuleSpec, cutoff: datetime) -> list[tuple[float, float]]:
    """External growth (x) and the aligned Visa driver (y), both published by ``cutoff``."""
    if spec.estimated is None:
        return []
    as_of = parse_aware_utc(cutoff.isoformat())
    field = spec.estimated.visa_field
    alignment = spec.estimated.alignment
    external = _booking_room_nights(as_of) if alignment == "next_visa_quarter" else _census_retail_yoy(as_of)
    pairs: list[tuple[float, float]] = []
    for point in external:
        if alignment == "containing_visa_quarter":
            period = VISA_FISCAL_CALENDAR.period_containing(point.period_end)
            quarter_end = VISA_FISCAL_CALENDAR.period_end(period)
        else:
            quarter_end = _next_quarter_end_after(point.period_end)
        driver = _visa_driver(field, quarter_end, as_of)
        if driver is None:
            continue
        pairs.append((point.value_ratio, driver))
    return pairs


def booking_guidance_covers_target(cutoff: datetime) -> bool:
    """True when the origin at ``cutoff`` has Booking guidance covering Visa's target quarter."""
    target = parse_aware_utc(cutoff.isoformat())
    dated: bool | None = None
    for row in _origin_rows():
        row_cutoff = parse_aware_utc(row["cutoff_utc"])
        flag = row.get("booking_guidance_covers_target", "").strip().lower() == "true"
        if row_cutoff == target:
            return flag
        if dated is None and row_cutoff.date() == target.date():
            dated = flag
    return bool(dated)


def rule_matches(
    spec: RuleSpec,
    *,
    source_family: str | None,
    statement_type: str,
    activity_type: str | None,
    basis: str | None,
    unit: str | None,
    attributes: Mapping[str, Any],
    guidance_covers_target: bool,
) -> bool:
    if spec.source_family != (source_family or ""):
        return False
    if spec.input_type not in {statement_type, "*"}:
        return False
    if spec.activity_type is not None and spec.activity_type != activity_type:
        return False
    if spec.basis is not None and spec.basis != basis:
        return False
    if spec.unit is not None and spec.unit != unit:
        return False
    if spec.requires_guidance_covers_target and not guidance_covers_target:
        return False
    for key, expected in spec.attribute_equals:
        if str(attributes.get(key, "")) != expected:
            return False
    return True


_BOOKING_RANGE = AnalystRange(
    anchor=BOOKING_ANCHOR,
    scale=BOOKING_SCALE,
    beta_low=BOOKING_BETA_LOW,
    beta_high=BOOKING_BETA_HIGH,
    max_abs_shift=BOOKING_MAX_SHIFT,
)
_CENSUS_RANGE = AnalystRange(
    anchor=CENSUS_ANCHOR,
    scale=US_PAYMENTS_VOLUME_SHARE,
    beta_low=CENSUS_BETA_LOW,
    beta_high=CENSUS_BETA_HIGH,
    max_abs_shift=CENSUS_MAX_SHIFT,
)

REGISTRY: tuple[RuleSpec, ...] = (
    RuleSpec(
        rule_key="booking_guidance_to_cross_border_premium",
        version=1,
        kind="analyst_range",
        source_family="booking",
        input_type="guidance",
        activity_type="room_nights",
        basis="units",
        unit="percent",
        target_parameter="cross_border_growth_premium",
        priority=20,
        requires_guidance_covers_target=True,
        analyst_range=_BOOKING_RANGE,
        rationale=(
            "Booking next-quarter room-nights guidance shifts the cross-border ex-intra-Europe "
            "growth premium only when the guidance quarter covers Visa's target quarter. "
            "Analyst range: management outlook, not a fitted coefficient. Betas 0.2-0.4 discount "
            "Booking's global mix (domestic and intra-Europe are outside Visa's driver). "
            "Anchor is 8% room-nights growth. The range midpoint is the point update; the "
            "guidance half-width widens the range."
        ),
        value_test="ablation_a_cross_border_error",
    ),
    RuleSpec(
        rule_key="booking_room_nights_to_cross_border_premium",
        version=1,
        kind="estimated",
        source_family="booking",
        input_type="measured",
        activity_type="room_nights",
        basis="units",
        unit="percent",
        target_parameter="cross_border_growth_premium",
        priority=10,
        estimated=Estimated(
            visa_field="cross_border_ex_intra_europe_growth_constant",
            alignment="next_visa_quarter",
            fallback=_BOOKING_RANGE,
        ),
        rationale=(
            "Lagged Booking room-nights growth shifts the cross-border ex-intra-Europe growth "
            "premium. Estimated when at least 12 aligned quarters are published by the cutoff "
            "(Booking quarter paired with the following Visa quarter); otherwise the analyst "
            "range. Betas 0.2-0.4 discount Booking's global mix. Anchor is 8% room-nights growth. "
            "Room nights are not Visa payments volume."
        ),
        value_test="ablation_a_cross_border_error",
    ),
    RuleSpec(
        rule_key="census_retail_yoy_to_payments_volume_growth",
        version=2,
        kind="estimated",
        source_family="census",
        input_type="measured",
        activity_type="retail_food_services_total",
        basis="sa",
        unit="pct",
        attribute_equals=(("measure", "yoy_3m_pct"), ("estimate_status", "three_month")),
        target_parameter="payments_volume_growth",
        priority=10,
        estimated=Estimated(
            visa_field="payments_volume_growth_constant",
            alignment="containing_visa_quarter",
            fallback=_CENSUS_RANGE,
        ),
        rationale=(
            "Census MARTS seasonally adjusted retail and food-services 3-month year-over-year "
            "growth, computed inside one verified advance release ending March, June, September "
            "or December, shifts payments-volume growth. One print per Visa quarter; "
            "possibly replaced releases are excluded. "
            "Scale 0.45 is an explicit assumption for the US share of Visa volume because Census "
            "is US-only. Estimated when at least 12 vintages align to a Visa quarter published "
            "by the cutoff; otherwise an analyst range around a 3% retail anchor. The revised "
            "workbook is never an input."
        ),
        value_test="ablation_a_us_payments_volume_error",
    ),
    RuleSpec(
        rule_key="airline_context",
        version=1,
        kind="context",
        source_family="airline",
        input_type="*",
        rationale=(
            "United disclosures stay context (LON-8). Airline guidance becomes an analyst-ranged "
            "rule only with a documented rationale where it covers the Visa target quarter."
        ),
        value_test="context_until_a_reviewed_rule",
    ),
    RuleSpec(
        rule_key="retailer_context",
        version=1,
        kind="context",
        source_family="retailer",
        input_type="*",
        rationale=(
            "Costco comps, traffic and ticket stay context (LON-8). No next-quarter guidance "
            "was adopted as a mapping rule."
        ),
        value_test="context_until_a_reviewed_rule",
    ),
    RuleSpec(
        rule_key="processor_context",
        version=1,
        kind="context",
        source_family="processor",
        input_type="*",
        rationale=(
            "PayPal total payment volume stays context (LON-8) as a payments-volume cross-check. "
            "No coefficient is applied."
        ),
        value_test="context_until_a_reviewed_rule",
    ),
)


def registry_families() -> frozenset[str]:
    return frozenset(spec.source_family for spec in REGISTRY)


def registry_index(spec: RuleSpec) -> int:
    for index, item in enumerate(REGISTRY):
        if item.rule_key == spec.rule_key and item.version == spec.version:
            return index
    return len(REGISTRY)


def sync_registry(session: Session, specs: Sequence[RuleSpec] = REGISTRY) -> list[MappingRule]:
    """Insert missing rules. Refuse a stored row whose definition hash differs."""
    rows: list[MappingRule] = []
    for spec in specs:
        digest = spec.definition_hash()
        existing = session.execute(
            select(MappingRule).where(MappingRule.rule_key == spec.rule_key, MappingRule.version == spec.version)
        ).scalar_one_or_none()
        if existing is None:
            existing = MappingRule(
                rule_key=spec.rule_key,
                version=spec.version,
                input_type=spec.input_type,
                target_parameter=spec.target_parameter,
                transform=spec.transform_dict(),
                rationale=spec.rationale,
                kind=spec.kind,
                source_family=spec.source_family,
                value_test=spec.value_test,
                definition_hash=digest,
            )
            session.add(existing)
            session.flush()
        elif existing.definition_hash != digest:
            raise RuleRegistryError(
                f"mapping rule {spec.rule_key} v{spec.version} changed without a version bump "
                f"(stored {existing.definition_hash}, code {digest})"
            )
        rows.append(existing)
    return rows


def rule_id_index(session: Session) -> dict[tuple[str, int], UUID]:
    rows = session.scalars(select(MappingRule)).all()
    return {(row.rule_key, row.version): row.id for row in rows}


__all__ = [
    "BOOKING_ANCHOR",
    "BOOKING_BETA_HIGH",
    "BOOKING_BETA_LOW",
    "CENSUS_ANCHOR",
    "MIN_ALIGNED_QUARTERS",
    "REGISTRY",
    "US_PAYMENTS_VOLUME_SHARE",
    "AnalystRange",
    "Estimated",
    "FitResult",
    "RuleRegistryError",
    "RuleSpec",
    "TransformResult",
    "aligned_pairs",
    "apply_analyst_range",
    "apply_estimated",
    "apply_transform",
    "booking_guidance_covers_target",
    "bounds_for",
    "fit_coefficient",
    "registry_families",
    "registry_index",
    "reject_probability_fields",
    "rule_id_index",
    "rule_matches",
    "sync_registry",
    "validate_rule",
]
