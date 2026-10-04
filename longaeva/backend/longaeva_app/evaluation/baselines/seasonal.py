"""Seasonal/trend baseline (LON-29).

Levels: year-ago value times one plus the mean YoY of the last four eligible
quarters. Drivers: the last reported YoY. Uncertainty is a normal draw around
that point, scaled by rolling-origin residuals whose actuals were already
published at the cutoff.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.companies.visa.calibration import ObsRow, load_observation_rows
from longaeva_app.evaluation.baselines.common import (
    SUITE_VERSION,
    SeriesPoint,
    additive_samples,
    finish_report,
    four_quarter_level_point,
    four_quarter_log_residuals,
    guard_origin,
    index_series,
    level_log_residuals,
    log_level_samples,
    normal_draws,
    origin_details,
    persistence_point,
    persistence_residuals,
    residual_scale,
    seasonal_level_point,
    series_seed,
    split_origins,
    stamp_rows,
    unavailable_row,
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
from longaeva_app.evaluation.origins import EvaluationOrigin
from longaeva_app.evaluation.targets import (
    DRIVER_TARGETS,
    LEVEL_TARGETS,
    has_four_quarter_actuals,
    load_actuals,
    load_four_quarter_actuals,
)
from longaeva_app.hashing import utc_isoformat

VARIANT = "seasonal_trend"
METHOD = "seasonal_naive_drift"
LABEL = "seasonal/trend"


def _history(
    rows: Sequence[ObsRow],
    origin: EvaluationOrigin,
) -> tuple[dict[str, dict[Any, SeriesPoint]], dict[str, dict[Any, SeriesPoint]]]:
    levels = {name: index_series(rows, origin.cutoff_ts, name) for name in LEVEL_TARGETS}
    growth = {name: index_series(rows, origin.cutoff_ts, name) for name in DRIVER_TARGETS}
    return levels, growth


def _scale_meta(residuals: Sequence[float]) -> dict[str, Any]:
    scale, low = residual_scale(residuals)
    return {
        "residual_n": len(residuals),
        "residual_scale": float(scale),
        "residual_n_low": low,
    }


def _actual_details(actual: Any) -> dict[str, Any]:
    return {
        "actual_source_id": actual.source_id,
        "actual_publication_ts": utc_isoformat(actual.publication_ts),
    }


def _score_level(
    *,
    origin: EvaluationOrigin,
    config: EvaluationConfig,
    digest: str,
    horizon: str,
    target: str,
    point: float | None,
    residuals: Sequence[float],
    actual: float | None,
    actual_meta: dict[str, Any],
    details_base: dict[str, Any],
) -> list[dict[str, Any]]:
    shared = {**details_base, "residual_kind": "log"}
    if actual is None:
        return [
            unavailable_row(
                horizon=horizon,
                target=target,
                reason="no released actual",
                details_base=shared,
                config=config,
                config_digest=digest,
                origin=origin,
            )
        ]
    if point is None or point <= 0.0:
        return [
            unavailable_row(
                horizon=horizon,
                target=target,
                reason="insufficient history for the seasonal/trend rule",
                details_base=shared,
                config=config,
                config_digest=digest,
                origin=origin,
            )
        ]
    meta = _scale_meta(residuals)
    seed = series_seed(config.base_seed, origin.origin_date, horizon, target)
    samples = log_level_samples(point, normal_draws(seed, config.n_paths, meta["residual_scale"]))
    rows = score_point(
        horizon=horizon,
        target=target,
        samples=samples,
        actual=actual,
        percentage_error=True,
        details_base={**shared, **meta, **actual_meta, "point": float(point)},
    )
    return stamp_rows(rows, config=config, config_digest=digest, origin=origin)


def _score_driver(
    *,
    origin: EvaluationOrigin,
    config: EvaluationConfig,
    digest: str,
    horizon: str,
    target: str,
    point: float | None,
    residuals: Sequence[float],
    actual: float | None,
    actual_meta: dict[str, Any],
    details_base: dict[str, Any],
    method_flags: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    flags = {"driver_method": METHOD}
    if method_flags:
        flags.update(method_flags)
    shared = {**details_base, "residual_kind": "additive", "method_flags": flags}
    if actual is None:
        return [
            unavailable_row(
                horizon=horizon,
                target=target,
                reason="no released actual",
                details_base=shared,
                config=config,
                config_digest=digest,
                origin=origin,
            )
        ]
    if point is None:
        return [
            unavailable_row(
                horizon=horizon,
                target=target,
                reason="no reported year-over-year rate at or before the origin",
                details_base=shared,
                config=config,
                config_digest=digest,
                origin=origin,
            )
        ]
    meta = _scale_meta(residuals)
    seed = series_seed(config.base_seed, origin.origin_date, horizon, target)
    samples = additive_samples(point, normal_draws(seed, config.n_paths, meta["residual_scale"]))
    rows = score_point(
        horizon=horizon,
        target=target,
        samples=np.asarray(samples, dtype=np.float64),
        actual=actual,
        percentage_error=False,
        details_base={**shared, **meta, **actual_meta, "point": float(point)},
    )
    return stamp_rows(rows, config=config, config_digest=digest, origin=origin)


def score_seasonal_origin(
    origin: EvaluationOrigin,
    config: EvaluationConfig,
    config_digest: str,
    observation_rows: Sequence[ObsRow],
) -> OriginEvaluation:
    """Score one origin. Inputs are observations published at or before the cutoff."""
    levels, growth = _history(observation_rows, origin)
    actuals = load_actuals(origin, rows=observation_rows)
    details_base = {**origin_details(origin), "label": LABEL, "method": METHOD}
    rows: list[dict[str, Any]] = []
    skipped: dict[str, str] = {}

    for name in LEVEL_TARGETS:
        series = levels[name]
        point = seasonal_level_point(series, origin.target, cutoff=origin.cutoff_ts)
        residuals = level_log_residuals(series, through=origin.origin)
        actual = actuals.get(name)
        rows.extend(
            _score_level(
                origin=origin,
                config=config,
                digest=config_digest,
                horizon="q1",
                target=name,
                point=point,
                residuals=residuals,
                actual=None if actual is None else actual.value,
                actual_meta={} if actual is None else _actual_details(actual),
                details_base=details_base,
            )
        )

    for name in DRIVER_TARGETS:
        series = growth[name]
        point = persistence_point(series, origin.origin)
        residuals = persistence_residuals(series, through=origin.origin)
        actual = actuals.get(name)
        if point is None:
            skipped[name] = "no reported year-over-year rate at or before the origin"
        rows.extend(
            _score_driver(
                origin=origin,
                config=config,
                digest=config_digest,
                horizon="q1",
                target=name,
                point=point,
                residuals=residuals,
                actual=None if actual is None else actual.value,
                actual_meta={} if actual is None else _actual_details(actual),
                details_base=details_base,
            )
        )

    if has_four_quarter_actuals(origin, rows=observation_rows):
        totals = load_four_quarter_actuals(origin, rows=observation_rows)
        for name in LEVEL_TARGETS:
            series = levels[name]
            point = four_quarter_level_point(series, origin.origin)
            residuals = four_quarter_log_residuals(series, through=origin.origin)
            rows.extend(
                _score_level(
                    origin=origin,
                    config=config,
                    digest=config_digest,
                    horizon="4q",
                    target=f"{name}_sum",
                    point=point,
                    residuals=residuals,
                    actual=totals.get(name),
                    actual_meta={},
                    details_base=details_base,
                )
            )
        for name in DRIVER_TARGETS:
            series = growth[name]
            # Quarter-4 YoY is the same statistic as the last reported quarterly YoY.
            point = persistence_point(series, origin.origin)
            residuals = persistence_residuals(series, through=origin.origin)
            rows.extend(
                _score_driver(
                    origin=origin,
                    config=config,
                    digest=config_digest,
                    horizon="4q",
                    target=name,
                    point=point,
                    residuals=residuals,
                    actual=totals.get(name),
                    actual_meta={},
                    details_base=details_base,
                    method_flags={"driver_4q": "persisted_quarterly_yoy"},
                )
            )

    return OriginEvaluation(origin=origin, run_id=None, rows=rows, skipped_drivers=skipped)


def run_seasonal_trend(
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
    """Run the seasonal/trend baseline on the harness origin set."""
    del use_cache, calibrate_fn, artifact_store
    scored, exclusions = split_origins(window=window, origin_dates=origin_dates)
    config = build_config(
        scored,
        n_paths=n_paths,
        base_seed=base_seed,
        model_variant=VARIANT,
        suite_version=SUITE_VERSION,
        driver_method=METHOD,
        baseline=_baseline_config_payload(),
    )
    digest = config_hash(config)
    observations = load_observation_rows()

    def _score(origin: EvaluationOrigin) -> OriginEvaluation:
        return score_seasonal_origin(origin, config, digest, observations)

    origin_evals = [guard_origin(origin, _score) for origin in scored]
    return finish_report(factory, config, origin_evals, exclusions)


def _baseline_config_payload() -> dict[str, Any]:
    return {
        "method": METHOD,
        "label": LABEL,
        "level_rule": "year_ago_times_one_plus_mean_recent_yoy",
        "driver_rule": "persist_last_reported_yoy",
        "residual": "rolling_origin_from_fy2018q2_pandemic_excluded",
    }


__all__ = [
    "LABEL",
    "METHOD",
    "VARIANT",
    "run_seasonal_trend",
    "score_seasonal_origin",
]
