"""Shared seasonal/trend math for the comparison baselines.

Levels use a seasonal naive with drift: the year-ago level times one plus the mean
year-over-year change of the last four eligible quarters. Drivers persist the last
reported year-over-year rate. Residual draws are normal, seeded per series.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import numpy.typing as npt
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.calibration import (
    ObsRow,
    as_of,
    parse_period,
    period_ord,
    prev_period,
    yoy_estimation_weight,
)
from longaeva_app.companies.visa.calibration import (
    next_period as next_fiscal,
)
from longaeva_app.evaluation.harness import (
    EvaluationConfig,
    EvaluationReport,
    OriginEvaluation,
    collect_aggregates,
    collect_four_quarter,
    config_hash,
    origin_seed,
    persist_rows,
)
from longaeva_app.evaluation.leakage import assert_inputs_before_cutoff
from longaeva_app.evaluation.origins import EvaluationOrigin, load_evaluation_origins
from longaeva_app.hashing import utc_isoformat

FloatArray = npt.NDArray[np.floating[Any]]

MIN_RESIDUALS = 6
MIN_GUIDANCE_ERRORS = 4
TREND_QUARTERS = 4
RESIDUAL_START = FiscalPeriod(2018, 2)
# Same quality gate as calibration: image-era net revenue and opex are misparsed,
# and FY2017 / FY2018Q1 failed to parse. See apply_quality_gates.
_LEVEL_FIELDS = frozenset(
    {
        "net_revenue",
        "operating_expenses_ex_special_items",
        "operating_profit_ex_special_items",
    }
)
# Operating profit ex special items is stored as a derived series, not measured.
_DERIVED_LEVEL_FIELDS = frozenset({"operating_profit_ex_special_items"})
_EXCLUDED_LEVEL_ERAS = frozenset({"image_text_layer", "table_2017"})
_WALK_LIMIT = 40

SUITE_VERSION = "lon29-v1"


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    period: FiscalPeriod
    value: float
    publication_ts: datetime
    source_id: str


def series_seed(base_seed: int, origin_date: str, horizon: str, target: str) -> int:
    """Per-series seed so one target's draws do not depend on which other targets are scored."""
    return origin_seed(base_seed, f"{origin_date}:{horizon}:{target}")


def assert_history_before_cutoff(points: Sequence[SeriesPoint], cutoff: datetime) -> None:
    """Raise ``LeakageError`` if a history point used as an input is after ``cutoff``."""
    entries = [
        {
            "label": f"{point.period.label()}:{point.source_id or 'value'}",
            "publication_ts": utc_isoformat(point.publication_ts),
        }
        for point in points
    ]
    assert_inputs_before_cutoff(cutoff, driver_history=entries)


def _series_row_included(row: ObsRow) -> bool:
    if (row.geography or "global") not in {"", "global"}:
        return False
    if not _level_row_usable(row):
        return False
    if row.field in _DERIVED_LEVEL_FIELDS:
        return row.statement_type in {"derived", "measured"} and row.value > 0.0
    return row.measured


def _level_row_usable(row: ObsRow) -> bool:
    """Drop level rows the calibration quality gate also refuses."""
    if row.field not in _LEVEL_FIELDS:
        return True
    if row.era in _EXCLUDED_LEVEL_ERAS:
        return False
    if row.period_label == "FY2018Q1" or row.period_label.startswith("FY2017"):
        return False
    return True


def index_series(
    rows: Sequence[ObsRow],
    cutoff: datetime,
    field: str,
) -> dict[FiscalPeriod, SeriesPoint]:
    """Latest global value of ``field`` published at or before ``cutoff``.

    Measured rows are used, except operating profit ex special items, which is
    kept from the derived series. Image-era and FY2017 level rows are dropped.
    """
    measured = [row for row in rows if row.field == field and _series_row_included(row)]
    chosen = as_of(measured, cutoff)
    out: dict[FiscalPeriod, SeriesPoint] = {}
    for row in chosen:
        period = parse_period(row.period_label)
        if period is None:
            continue
        value = float(row.value)
        if row.unit == "percent":
            value = value / 100.0
        out[period] = SeriesPoint(
            period=period,
            value=value,
            publication_ts=row.publication_ts,
            source_id=row.source_id,
        )
    assert_history_before_cutoff(list(out.values()), cutoff)
    return out


def yoy_change(levels: Mapping[FiscalPeriod, SeriesPoint], period: FiscalPeriod) -> float | None:
    """Eligible level YoY. Pandemic-weighted quarters and missing bases return None."""
    if yoy_estimation_weight(period, include_pandemic=False) <= 0.0:
        return None
    current = levels.get(period)
    previous = levels.get(prev_period(period, 4))
    if current is None or previous is None or previous.value <= 0.0:
        return None
    return current.value / previous.value - 1.0


def _trend_quarters(levels: Mapping[FiscalPeriod, SeriesPoint], end: FiscalPeriod) -> list[FiscalPeriod]:
    found: list[FiscalPeriod] = []
    cursor = end
    steps = 0
    while len(found) < TREND_QUARTERS and steps < _WALK_LIMIT:
        if yoy_change(levels, cursor) is not None:
            found.append(cursor)
        cursor = prev_period(cursor, 1)
        steps += 1
    return found


def mean_recent_yoy(levels: Mapping[FiscalPeriod, SeriesPoint], end: FiscalPeriod) -> float | None:
    """Mean YoY of up to the last four eligible quarters ending at ``end`` (inclusive)."""
    quarters = _trend_quarters(levels, end)
    if not quarters:
        return None
    values = [yoy_change(levels, quarter) for quarter in quarters]
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return float(sum(usable) / len(usable))


def points_used_for_level_forecast(
    levels: Mapping[FiscalPeriod, SeriesPoint],
    target: FiscalPeriod,
) -> list[SeriesPoint]:
    """History points the seasonal level rule reads for ``target`` (not the target itself)."""
    used: list[SeriesPoint] = []
    year_ago = levels.get(prev_period(target, 4))
    if year_ago is not None:
        used.append(year_ago)
    for quarter in _trend_quarters(levels, prev_period(target, 1)):
        current = levels.get(quarter)
        previous = levels.get(prev_period(quarter, 4))
        if current is not None:
            used.append(current)
        if previous is not None:
            used.append(previous)
    return used


def seasonal_level_point(
    levels: Mapping[FiscalPeriod, SeriesPoint],
    target: FiscalPeriod,
    *,
    cutoff: datetime | None = None,
) -> float | None:
    """Year-ago level times one plus the recent eligible YoY mean. Does not read ``target``."""
    if cutoff is not None:
        assert_history_before_cutoff(points_used_for_level_forecast(levels, target), cutoff)
    year_ago = levels.get(prev_period(target, 4))
    if year_ago is None or year_ago.value <= 0.0:
        return None
    trend = mean_recent_yoy(levels, prev_period(target, 1))
    if trend is None:
        return None
    return year_ago.value * (1.0 + trend)


def level_log_residual(levels: Mapping[FiscalPeriod, SeriesPoint], period: FiscalPeriod) -> float | None:
    """log(actual / seasonal forecast) for ``period``, or None when the quarter is ineligible."""
    if yoy_estimation_weight(period, include_pandemic=False) <= 0.0:
        return None
    actual = levels.get(period)
    point = seasonal_level_point(levels, period)
    if actual is None or point is None or point <= 0.0 or actual.value <= 0.0:
        return None
    return math.log(actual.value / point)


def level_log_residuals(
    levels: Mapping[FiscalPeriod, SeriesPoint],
    *,
    through: FiscalPeriod,
) -> list[float]:
    """Rolling-origin log residuals from FY2018Q2 through ``through`` (inclusive)."""
    out: list[float] = []
    cursor = RESIDUAL_START
    while period_ord(cursor) <= period_ord(through):
        residual = level_log_residual(levels, cursor)
        if residual is not None:
            out.append(residual)
        cursor = next_fiscal(cursor, 1)
    return out


def four_quarter_level_point(levels: Mapping[FiscalPeriod, SeriesPoint], origin: FiscalPeriod) -> float | None:
    """Sum of seasonal points for the four quarters after ``origin``. Trend stays as of ``origin``."""
    total = 0.0
    trend = mean_recent_yoy(levels, origin)
    if trend is None:
        return None
    for step in range(1, 5):
        target = next_fiscal(origin, step)
        year_ago = levels.get(prev_period(target, 4))
        if year_ago is None or year_ago.value <= 0.0:
            return None
        total += year_ago.value * (1.0 + trend)
    return total


def four_quarter_log_residual(levels: Mapping[FiscalPeriod, SeriesPoint], window_end: FiscalPeriod) -> float | None:
    """Log residual of a completed four-quarter sum ending at ``window_end``."""
    origin = prev_period(window_end, 4)
    quarters = [next_fiscal(origin, step) for step in range(1, 5)]
    if any(yoy_estimation_weight(quarter, include_pandemic=False) <= 0.0 for quarter in quarters):
        return None
    point = four_quarter_level_point(levels, origin)
    if point is None or point <= 0.0:
        return None
    actual = 0.0
    for quarter in quarters:
        row = levels.get(quarter)
        if row is None or row.value <= 0.0:
            return None
        actual += row.value
    return math.log(actual / point)


def four_quarter_log_residuals(
    levels: Mapping[FiscalPeriod, SeriesPoint],
    *,
    through: FiscalPeriod,
) -> list[float]:
    out: list[float] = []
    cursor = next_fiscal(RESIDUAL_START, 3)
    while period_ord(cursor) <= period_ord(through):
        residual = four_quarter_log_residual(levels, cursor)
        if residual is not None:
            out.append(residual)
        cursor = next_fiscal(cursor, 1)
    return out


def persistence_point(growth: Mapping[FiscalPeriod, SeriesPoint], origin: FiscalPeriod) -> float | None:
    """Last reported YoY at or before ``origin``. Pandemic prints are kept: they were reported."""
    cursor = origin
    for _ in range(_WALK_LIMIT):
        row = growth.get(cursor)
        if row is not None:
            return row.value
        cursor = prev_period(cursor, 1)
    return None


def persistence_residual(growth: Mapping[FiscalPeriod, SeriesPoint], period: FiscalPeriod) -> float | None:
    """Actual YoY minus the rate reported one quarter earlier. Pandemic quarters are dropped."""
    if yoy_estimation_weight(period, include_pandemic=False) <= 0.0:
        return None
    actual = growth.get(period)
    if actual is None:
        return None
    previous = persistence_point(growth, prev_period(period, 1))
    if previous is None:
        return None
    return actual.value - previous


def persistence_residuals(
    growth: Mapping[FiscalPeriod, SeriesPoint],
    *,
    through: FiscalPeriod,
) -> list[float]:
    out: list[float] = []
    cursor = RESIDUAL_START
    while period_ord(cursor) <= period_ord(through):
        residual = persistence_residual(growth, cursor)
        if residual is not None:
            out.append(residual)
        cursor = next_fiscal(cursor, 1)
    return out


def residual_scale(residuals: Sequence[float], *, minimum: int = MIN_RESIDUALS) -> tuple[float, bool]:
    """Sample standard deviation. ``low`` is true when fewer than ``minimum`` residuals exist."""
    values = [float(value) for value in residuals if math.isfinite(value)]
    low = len(values) < minimum
    if len(values) < 2:
        return 0.0, True
    scale = float(np.std(np.asarray(values, dtype=np.float64), ddof=1))
    if not math.isfinite(scale) or scale < 0.0:
        return 0.0, True
    return scale, low


def normal_draws(seed: int, n_paths: int, scale: float) -> FloatArray:
    if n_paths < 1:
        raise ValueError("n_paths must be positive")
    if scale <= 0.0 or not math.isfinite(scale):
        return np.zeros(n_paths, dtype=np.float64)
    rng = np.random.default_rng(seed)
    return np.asarray(rng.normal(0.0, scale, size=n_paths), dtype=np.float64)


def log_level_samples(point: float, draws: FloatArray) -> FloatArray:
    if point <= 0.0:
        raise ValueError("log-level samples require a positive point forecast")
    return np.asarray(point * np.exp(np.asarray(draws, dtype=np.float64)), dtype=np.float64)


def additive_samples(point: float, draws: FloatArray) -> FloatArray:
    return np.asarray(float(point) + np.asarray(draws, dtype=np.float64), dtype=np.float64)


def split_origins(
    *,
    window: str = "all",
    origin_dates: list[str] | None = None,
) -> tuple[list[EvaluationOrigin], list[dict[str, str]]]:
    origins = load_evaluation_origins(window=window, origin_dates=origin_dates)
    scored = [origin for origin in origins if origin.scored]
    excluded = [origin for origin in origins if origin.status == "candidate" and origin.exclusion_reason]
    rows = [
        {"origin_date": origin.origin_date, "label": origin.label, "reason": origin.exclusion_reason or ""}
        for origin in excluded
    ]
    return scored, rows


def stamp_rows(
    rows: list[dict[str, Any]],
    *,
    config: EvaluationConfig,
    config_digest: str,
    origin: EvaluationOrigin,
) -> list[dict[str, Any]]:
    for row in rows:
        row["suite_version"] = config.suite_version
        row["model_variant"] = config.model_variant
        row["origin_ts"] = origin.cutoff_ts
        row["config_hash"] = config_digest
    return rows


def unavailable_row(
    *,
    horizon: str,
    target: str,
    reason: str,
    details_base: Mapping[str, Any],
    config: EvaluationConfig,
    config_digest: str,
    origin: EvaluationOrigin,
) -> dict[str, Any]:
    """A marker row. Aggregates ignore it because it has no ``abs_error``."""
    details = {
        **details_base,
        "target": target,
        "horizon": horizon,
        "statistic": "available",
        "status": "unavailable",
        "reason": reason,
    }
    row = {
        "metric": f"{horizon}.{target}.available",
        "value": 0.0,
        "details": details,
    }
    return stamp_rows([row], config=config, config_digest=config_digest, origin=origin)[0]


def assemble_report(
    config: EvaluationConfig,
    digest: str,
    origin_evals: list[Any],
    exclusions: list[dict[str, str]],
) -> EvaluationReport:
    return EvaluationReport(
        config=config,
        config_hash=digest,
        origins=origin_evals,
        exclusions=exclusions,
        aggregates=collect_aggregates(origin_evals),
        four_quarter=collect_four_quarter(origin_evals),
        n_scored=sum(1 for item in origin_evals if item.error is None and item.rows),
        n_excluded=len(exclusions),
    )


def persist_variant(
    factory: sessionmaker[Session],
    rows: Sequence[dict[str, Any]],
    digest: str,
    model_variant: str,
) -> None:
    with factory() as session:
        persist_rows(session, rows, digest, model_variant)
        session.commit()


def hashed_config(config: EvaluationConfig) -> tuple[EvaluationConfig, str]:
    return config, config_hash(config)


def origin_details(origin: EvaluationOrigin) -> dict[str, Any]:
    return {
        "origin_label": origin.label,
        "origin_date": origin.origin_date,
        "origin_window": origin.origin_window,
        "target_quarter": origin.target.label(),
    }


def guard_origin(
    origin: EvaluationOrigin,
    score: Callable[[EvaluationOrigin], OriginEvaluation],
) -> OriginEvaluation:
    """Run ``score`` and record a per-origin failure instead of aborting the suite."""
    try:
        result = score(origin)
    except Exception as exc:  # noqa: BLE001 — one origin must not drop the rest
        return OriginEvaluation(
            origin=origin,
            run_id=None,
            rows=[],
            skipped_drivers={},
            error=f"{type(exc).__name__}: {exc}",
        )
    return result


def finish_report(
    factory: sessionmaker[Session],
    config: EvaluationConfig,
    origin_evals: list[OriginEvaluation],
    exclusions: list[dict[str, str]],
) -> EvaluationReport:
    digest = config_hash(config)
    rows = [row for item in origin_evals for row in item.rows]
    persist_variant(factory, rows, digest, config.model_variant)
    return assemble_report(config, digest, origin_evals, exclusions)


__all__ = [
    "MIN_GUIDANCE_ERRORS",
    "MIN_RESIDUALS",
    "RESIDUAL_START",
    "SUITE_VERSION",
    "TREND_QUARTERS",
    "SeriesPoint",
    "additive_samples",
    "assemble_report",
    "assert_history_before_cutoff",
    "finish_report",
    "four_quarter_level_point",
    "four_quarter_log_residual",
    "four_quarter_log_residuals",
    "guard_origin",
    "hashed_config",
    "origin_details",
    "index_series",
    "level_log_residual",
    "level_log_residuals",
    "log_level_samples",
    "mean_recent_yoy",
    "normal_draws",
    "persist_variant",
    "persistence_point",
    "persistence_residual",
    "persistence_residuals",
    "points_used_for_level_forecast",
    "residual_scale",
    "seasonal_level_point",
    "series_seed",
    "split_origins",
    "stamp_rows",
    "unavailable_row",
    "yoy_change",
]
