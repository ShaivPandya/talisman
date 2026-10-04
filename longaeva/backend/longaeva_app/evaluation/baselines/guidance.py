"""Company-guidance baseline (LON-29).

The point forecast is the midpoint of Visa's own next-quarter outlook, applied
to the year-ago actual. Operating profit is derived from guided revenue and
guided operating expenses and flagged ``derived``. Uncertainty uses prior
guidance errors when at least four have actuals published at or before the
cutoff; otherwise the seasonal/trend residual spread, flagged
``residual_source=seasonal_trend_fallback``.

This is company guidance, not a sell-side estimate. The only estimates string
this module uses is ``ESTIMATES_NOTE``.
"""

from __future__ import annotations

import csv
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.calibration import ObsRow, load_observation_rows, prev_period
from longaeva_app.evaluation.baselines.common import (
    MIN_GUIDANCE_ERRORS,
    SUITE_VERSION,
    SeriesPoint,
    finish_report,
    guard_origin,
    index_series,
    level_log_residuals,
    log_level_samples,
    normal_draws,
    origin_details,
    residual_scale,
    series_seed,
    split_origins,
    stamp_rows,
    unavailable_row,
    yoy_change,
)
from longaeva_app.evaluation.harness import (
    DEFAULT_BASE_SEED,
    DEFAULT_N_PATHS,
    EvaluationConfig,
    EvaluationReport,
    OriginEvaluation,
    build_config,
    config_hash,
    score_point,
)
from longaeva_app.evaluation.origins import PACKAGE_ROOT, EvaluationOrigin
from longaeva_app.evaluation.targets import (
    DRIVER_TARGETS,
    LEVEL_TARGETS,
    ActualValue,
    load_actuals,
)
from longaeva_app.extract.visa_guidance import parse_guidance_phrase
from longaeva_app.hashing import utc_isoformat

VARIANT = "guidance"
METHOD = "guidance_midpoint_v1"
LABEL = "company guidance"
ESTIMATES_NOTE = "consensus unavailable (no licensed free historical source)"
DECK_BASIS_NOTE = (
    "Deck outlook is adjusted constant-dollar growth; scored against GAAP nominal actuals. "
    "The residual distribution absorbs the basis gap."
)
NO_DRIVER_REASON = "no numeric driver guidance"
NO_QUARTER_REASON = "no next-quarter company guidance"
NO_OPEX_REASON = "no operating-expense guidance"
FOUR_QUARTER_REASON = "guidance is next-quarter only"
OPEX_FIELD = "operating_expenses_ex_special_items"
_RELATIVE_OPEX = re.compile(
    r"(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)\s+points?\s+lower",
    re.IGNORECASE,
)
_GUIDANCE_DIR = PACKAGE_ROOT / "data" / "fixtures" / "guidance"
_RANGE_TOLERANCE = 0.51


@dataclass(frozen=True, slots=True)
class GuidanceStatement:
    origin_label: str
    source_kind: str
    metric: str
    phrase: str
    range_low: float | None
    range_high: float | None
    basis: str
    comparable: str
    note: str


@dataclass(frozen=True, slots=True)
class GuidanceCase:
    """Point forecasts and realized actuals for one origin, for residual history."""

    origin: EvaluationOrigin
    revenue_point: float | None
    profit_point: float | None
    revenue_actual: float | None
    profit_actual: float | None
    revenue_actual_ts: datetime | None
    profit_actual_ts: datetime | None
    revenue_stmt: GuidanceStatement | None
    opex_stmt: GuidanceStatement | None
    opex_growth: float | None
    opex_resolution: str | None


def growth_midpoint_ratio(range_low: float, range_high: float) -> float:
    """Midpoint of a percent range, as a ratio (18 and 19 -> 0.185)."""
    return (float(range_low) + float(range_high)) / 200.0


def relative_opex_growth(reported_yoy: float, phrase: str) -> float:
    """Reported YoY minus the midpoint of 'N to M points lower'."""
    match = _RELATIVE_OPEX.search(phrase)
    if match is None:
        raise ValueError(f"relative operating-expense phrase not recognized: {phrase!r}")
    points = (float(match.group(1)) + float(match.group(2))) / 2.0
    return float(reported_yoy) - points / 100.0


def derived_operating_profit(forecast_revenue: float, year_ago_opex: float, opex_growth: float) -> float:
    """Forecast revenue minus year-ago operating expenses grown at ``opex_growth``."""
    return float(forecast_revenue) - float(year_ago_opex) * (1.0 + float(opex_growth))


def choose_guidance_scale(
    guidance_errors: Sequence[float],
    seasonal_residuals: Sequence[float],
) -> tuple[float, bool, str]:
    """Prefer prior guidance errors once four exist; otherwise the seasonal spread."""
    usable = [float(value) for value in guidance_errors if math.isfinite(value)]
    if len(usable) >= MIN_GUIDANCE_ERRORS:
        scale, low = residual_scale(usable, minimum=MIN_GUIDANCE_ERRORS)
        return scale, low, "guidance_errors"
    scale, low = residual_scale(seasonal_residuals)
    return scale, low, "seasonal_trend_fallback"


def _optional_float(raw: str) -> float | None:
    text = raw.strip()
    if not text:
        return None
    return float(text)


def load_statements(path: Path | None = None) -> list[GuidanceStatement]:
    source = path or (_GUIDANCE_DIR / "statements.csv")
    out: list[GuidanceStatement] = []
    with source.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out.append(
                GuidanceStatement(
                    origin_label=row["origin_label"],
                    source_kind=row["source_kind"],
                    metric=row["metric"],
                    phrase=row["phrase"],
                    range_low=_optional_float(row["range_low"]),
                    range_high=_optional_float(row["range_high"]),
                    basis=row["basis"],
                    comparable=row["comparable"],
                    note=row["note"],
                )
            )
    return out


def lexicon_range(statement: GuidanceStatement) -> tuple[float, float]:
    """Parse ``statement.phrase`` with the LON-7 lexicon and check the stored range."""
    parsed = parse_guidance_phrase(statement.phrase)
    if statement.range_low is None or statement.range_high is None:
        return parsed
    low_off = abs(parsed[0] - statement.range_low) > _RANGE_TOLERANCE
    high_off = abs(parsed[1] - statement.range_high) > _RANGE_TOLERANCE
    if low_off or high_off:
        raise ValueError(
            f"{statement.origin_label} {statement.metric}: lexicon {parsed} != "
            f"stored {(statement.range_low, statement.range_high)} for {statement.phrase!r}"
        )
    return parsed


def _usable(statement: GuidanceStatement) -> bool:
    return statement.comparable in {"true", "derived"} and statement.metric in {
        "net_revenue",
        "operating_expenses",
    }


def statements_for(statements: Sequence[GuidanceStatement], origin_label: str) -> dict[str, GuidanceStatement]:
    chosen: dict[str, GuidanceStatement] = {}
    for statement in statements:
        if statement.origin_label != origin_label or not _usable(statement):
            continue
        if statement.metric in chosen:
            raise ValueError(f"{origin_label} has two usable {statement.metric} statements")
        chosen[statement.metric] = statement
    return chosen


def _year_ago_level(levels: Mapping[FiscalPeriod, SeriesPoint], target: FiscalPeriod) -> float | None:
    row = levels.get(prev_period(target, 4))
    if row is None or row.value <= 0.0:
        return None
    return row.value


def _revenue_point(
    levels: Mapping[FiscalPeriod, SeriesPoint],
    target: FiscalPeriod,
    statement: GuidanceStatement,
) -> tuple[float | None, float]:
    low, high = lexicon_range(statement)
    growth = growth_midpoint_ratio(low, high)
    base = _year_ago_level(levels, target)
    if base is None:
        return None, growth
    return base * (1.0 + growth), growth


def _opex_growth_for(
    statement: GuidanceStatement,
    opex_levels: Mapping[FiscalPeriod, SeriesPoint],
    origin: EvaluationOrigin,
) -> tuple[float | None, str | None]:
    if statement.comparable == "derived":
        reported = yoy_change(opex_levels, origin.origin)
        if reported is None:
            return None, None
        return relative_opex_growth(reported, statement.phrase), "reported_yoy_minus_midpoint"
    low, high = lexicon_range(statement)
    return growth_midpoint_ratio(low, high), "phrase_midpoint"


def _profit_point(
    revenue_point: float | None,
    opex_levels: Mapping[FiscalPeriod, SeriesPoint],
    target: FiscalPeriod,
    opex_growth: float | None,
) -> float | None:
    if revenue_point is None or opex_growth is None:
        return None
    year_ago = _year_ago_level(opex_levels, target)
    if year_ago is None:
        return None
    return derived_operating_profit(revenue_point, year_ago, opex_growth)


def _actual(actuals: Mapping[str, ActualValue], name: str) -> tuple[float | None, datetime | None]:
    row = actuals.get(name)
    if row is None:
        return None, None
    return row.value, row.publication_ts


def build_cases(
    origins: Sequence[EvaluationOrigin],
    statements: Sequence[GuidanceStatement],
    observation_rows: Sequence[ObsRow],
) -> list[GuidanceCase]:
    """Point and actual for every candidate, including ones the harness does not score."""
    cases: list[GuidanceCase] = []
    for origin in origins:
        chosen = statements_for(statements, origin.label)
        revenue_stmt = chosen.get("net_revenue")
        opex_stmt = chosen.get("operating_expenses")
        revenue_levels = index_series(observation_rows, origin.cutoff_ts, "net_revenue")
        opex_levels = index_series(observation_rows, origin.cutoff_ts, OPEX_FIELD)
        revenue_point: float | None = None
        opex_growth: float | None = None
        resolution: str | None = None
        if revenue_stmt is not None:
            revenue_point, _growth = _revenue_point(revenue_levels, origin.target, revenue_stmt)
        if opex_stmt is not None:
            opex_growth, resolution = _opex_growth_for(opex_stmt, opex_levels, origin)
        profit_point = _profit_point(revenue_point, opex_levels, origin.target, opex_growth)
        actuals = load_actuals(origin, rows=observation_rows)
        revenue_actual, revenue_ts = _actual(actuals, "net_revenue")
        profit_actual, profit_ts = _actual(actuals, "operating_profit_ex_special_items")
        cases.append(
            GuidanceCase(
                origin=origin,
                revenue_point=revenue_point,
                profit_point=profit_point,
                revenue_actual=revenue_actual,
                profit_actual=profit_actual,
                revenue_actual_ts=revenue_ts,
                profit_actual_ts=profit_ts,
                revenue_stmt=revenue_stmt,
                opex_stmt=opex_stmt,
                opex_growth=opex_growth,
                opex_resolution=resolution,
            )
        )
    return cases


def _log_errors(
    cases: Sequence[GuidanceCase],
    cutoff: datetime,
    *,
    field: str,
) -> list[float]:
    out: list[float] = []
    for case in cases:
        if case.origin.cutoff_ts >= cutoff:
            continue
        if field == "net_revenue":
            point, actual, published = case.revenue_point, case.revenue_actual, case.revenue_actual_ts
        else:
            point, actual, published = case.profit_point, case.profit_actual, case.profit_actual_ts
        if point is None or actual is None or published is None:
            continue
        if published > cutoff or point <= 0.0 or actual <= 0.0:
            continue
        out.append(math.log(actual / point))
    return out


def _basis_note(statement: GuidanceStatement | None) -> str | None:
    if statement is not None and statement.source_kind == "deck":
        return DECK_BASIS_NOTE
    return None


def _score_level(
    *,
    origin: EvaluationOrigin,
    config: EvaluationConfig,
    digest: str,
    target: str,
    point: float | None,
    scale: float,
    low: bool,
    source: str,
    error_n: int,
    actual: float | None,
    actual_meta: dict[str, Any],
    details_base: dict[str, Any],
    missing_reason: str,
) -> list[dict[str, Any]]:
    shared = {
        **details_base,
        "residual_source": source,
        "guidance_error_n": error_n,
        "residual_n_low": low,
        "residual_scale": float(scale),
    }
    if point is None or point <= 0.0 or actual is None:
        if point is None:
            reason = missing_reason
        elif point <= 0.0:
            reason = "non-positive point forecast"
        else:
            reason = "no released actual"
        return [
            unavailable_row(
                horizon="q1",
                target=target,
                reason=reason,
                details_base=shared,
                config=config,
                config_digest=digest,
                origin=origin,
            )
        ]
    seed = series_seed(config.base_seed, origin.origin_date, "q1", target)
    samples = log_level_samples(point, normal_draws(seed, config.n_paths, scale))
    rows = score_point(
        horizon="q1",
        target=target,
        samples=np.asarray(samples, dtype=np.float64),
        actual=actual,
        percentage_error=True,
        details_base={**shared, **actual_meta, "point": float(point)},
    )
    return stamp_rows(rows, config=config, config_digest=digest, origin=origin)


def _mark_unavailable(
    *,
    origin: EvaluationOrigin,
    config: EvaluationConfig,
    digest: str,
    horizon: str,
    target: str,
    reason: str,
    details_base: dict[str, Any],
) -> dict[str, Any]:
    return unavailable_row(
        horizon=horizon,
        target=target,
        reason=reason,
        details_base=details_base,
        config=config,
        config_digest=digest,
        origin=origin,
    )


def score_guidance_origin(
    origin: EvaluationOrigin,
    config: EvaluationConfig,
    config_digest: str,
    case: GuidanceCase,
    cases: Sequence[GuidanceCase],
    observation_rows: Sequence[ObsRow],
) -> OriginEvaluation:
    """Score one origin. Drivers and the four-quarter horizon are marked unavailable."""
    details_base: dict[str, Any] = {**origin_details(origin), "label": LABEL, "method": METHOD}
    rows: list[dict[str, Any]] = []
    revenue_levels = index_series(observation_rows, origin.cutoff_ts, "net_revenue")
    profit_levels = index_series(observation_rows, origin.cutoff_ts, "operating_profit_ex_special_items")
    actuals = load_actuals(origin, rows=observation_rows)

    revenue_errors = _log_errors(cases, origin.cutoff_ts, field="net_revenue")
    revenue_scale, revenue_low, revenue_source = choose_guidance_scale(
        revenue_errors,
        level_log_residuals(revenue_levels, through=origin.origin),
    )
    revenue_actual = actuals.get("net_revenue")
    revenue_meta = _statement_meta(case.revenue_stmt, case.opex_growth, case.opex_resolution, derived=False)
    rows.extend(
        _score_level(
            origin=origin,
            config=config,
            digest=config_digest,
            target="net_revenue",
            point=case.revenue_point,
            scale=revenue_scale,
            low=revenue_low,
            source=revenue_source,
            error_n=len(revenue_errors),
            actual=None if revenue_actual is None else revenue_actual.value,
            actual_meta={} if revenue_actual is None else _actual_meta(revenue_actual),
            details_base={**details_base, **revenue_meta, "derived": False},
            missing_reason=NO_QUARTER_REASON
            if case.revenue_stmt is None
            else "insufficient history for the guidance point",
        )
    )

    profit_errors = _log_errors(cases, origin.cutoff_ts, field="operating_profit")
    profit_scale, profit_low, profit_source = choose_guidance_scale(
        profit_errors,
        level_log_residuals(profit_levels, through=origin.origin),
    )
    profit_actual = actuals.get("operating_profit_ex_special_items")
    if case.opex_stmt is None:
        profit_reason = NO_OPEX_REASON
    elif case.revenue_stmt is None:
        profit_reason = NO_QUARTER_REASON
    elif case.opex_growth is None:
        profit_reason = "no reported operating-expense growth to resolve the relative outlook"
    else:
        profit_reason = "insufficient history for the guidance point"
    profit_meta = _statement_meta(
        case.opex_stmt or case.revenue_stmt, case.opex_growth, case.opex_resolution, derived=True
    )
    rows.extend(
        _score_level(
            origin=origin,
            config=config,
            digest=config_digest,
            target="operating_profit_ex_special_items",
            point=case.profit_point,
            scale=profit_scale,
            low=profit_low,
            source=profit_source,
            error_n=len(profit_errors),
            actual=None if profit_actual is None else profit_actual.value,
            actual_meta={} if profit_actual is None else _actual_meta(profit_actual),
            details_base={**details_base, **profit_meta, "derived": True},
            missing_reason=profit_reason,
        )
    )

    for name in DRIVER_TARGETS:
        rows.append(
            _mark_unavailable(
                origin=origin,
                config=config,
                digest=config_digest,
                horizon="q1",
                target=name,
                reason=NO_DRIVER_REASON,
                details_base=details_base,
            )
        )
    for name in LEVEL_TARGETS:
        rows.append(
            _mark_unavailable(
                origin=origin,
                config=config,
                digest=config_digest,
                horizon="4q",
                target=f"{name}_sum",
                reason=FOUR_QUARTER_REASON,
                details_base=details_base,
            )
        )
    for name in DRIVER_TARGETS:
        rows.append(
            _mark_unavailable(
                origin=origin,
                config=config,
                digest=config_digest,
                horizon="4q",
                target=name,
                reason=FOUR_QUARTER_REASON,
                details_base=details_base,
            )
        )
    skipped = {name: NO_DRIVER_REASON for name in DRIVER_TARGETS}
    return OriginEvaluation(origin=origin, run_id=None, rows=rows, skipped_drivers=skipped)


def _actual_meta(actual: ActualValue) -> dict[str, Any]:
    return {
        "actual_source_id": actual.source_id,
        "actual_publication_ts": utc_isoformat(actual.publication_ts),
    }


def _statement_meta(
    statement: GuidanceStatement | None,
    opex_growth: float | None,
    opex_resolution: str | None,
    *,
    derived: bool,
) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    note = _basis_note(statement)
    if note is not None:
        meta["basis_note"] = note
    if statement is not None:
        meta["guidance_phrase"] = statement.phrase
        meta["guidance_source_kind"] = statement.source_kind
    if derived and opex_growth is not None:
        meta["opex_growth"] = float(opex_growth)
    if derived and opex_resolution is not None:
        meta["opex_resolution"] = opex_resolution
    return meta


def baseline_payload() -> dict[str, Any]:
    return {
        "method": METHOD,
        "label": LABEL,
        "estimates": ESTIMATES_NOTE,
        "residual_rule": "guidance_errors_if_n_ge_4_else_seasonal_trend",
    }


def run_guidance(
    factory: sessionmaker[Session],
    *,
    window: str = "all",
    origin_dates: list[str] | None = None,
    n_paths: int = DEFAULT_N_PATHS,
    base_seed: int = DEFAULT_BASE_SEED,
    use_cache: bool = True,
    calibrate_fn: Any = None,
    artifact_store: Any = None,
) -> EvaluationReport:
    """Run the company-guidance baseline on the harness origin set."""
    del use_cache, calibrate_fn, artifact_store
    from longaeva_app.evaluation.origins import load_evaluation_origins

    scored, exclusions = split_origins(window=window, origin_dates=origin_dates)
    # Residual history may use excluded origins (their guidance is still prior data).
    history_origins = load_evaluation_origins(window="all")
    config = build_config(
        scored,
        n_paths=n_paths,
        base_seed=base_seed,
        model_variant=VARIANT,
        suite_version=SUITE_VERSION,
        driver_method=METHOD,
        baseline=baseline_payload(),
    )
    digest = config_hash(config)
    observations = load_observation_rows()
    statements = load_statements()
    cases = build_cases(history_origins, statements, observations)
    by_date = {case.origin.origin_date: case for case in cases}

    def _score(origin: EvaluationOrigin) -> OriginEvaluation:
        return score_guidance_origin(
            origin,
            config,
            digest,
            by_date[origin.origin_date],
            cases,
            observations,
        )

    origin_evals = [guard_origin(origin, _score) for origin in scored]
    return finish_report(factory, config, origin_evals, exclusions)


__all__ = [
    "DECK_BASIS_NOTE",
    "ESTIMATES_NOTE",
    "FOUR_QUARTER_REASON",
    "LABEL",
    "METHOD",
    "NO_DRIVER_REASON",
    "NO_OPEX_REASON",
    "NO_QUARTER_REASON",
    "VARIANT",
    "GuidanceStatement",
    "build_cases",
    "choose_guidance_scale",
    "derived_operating_profit",
    "growth_midpoint_ratio",
    "lexicon_range",
    "load_statements",
    "relative_opex_growth",
    "run_guidance",
    "score_guidance_origin",
    "statements_for",
]
