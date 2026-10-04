"""Model-conditional attribution of paired scenario differences (LON-22 / FR-11).

Sequential contributions follow a fixed order and sum to the total difference.
One-at-a-time contributions need not. The joint residual is the gap. Every
label says the effect is conditional on the model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from longaeva_app.companies.base import CompanyModel, FiscalPeriod, StartingState
from longaeva_app.engine.runner import SimulationResult, simulate

ATTRIBUTION_METRICS: tuple[str, ...] = ("net_revenue", "operating_profit_ex_special_items")
SENSITIVITY_METRIC = "net_revenue"
FLAG_NAME = "high_sensitivity_weak_support"
FLAG_THRESHOLD = 0.25
ORDER_NOTE = (
    "Sequential contributions follow a fixed order (parameters by name, then interventions "
    "in listed order) and sum to the total difference. One-at-a-time contributions need not "
    "sum to the total when changes interact; the joint residual is that gap. "
    "Every effect is conditional on the model."
)
_UNREVIEWED = frozenset({"pending", "rejected"})


@dataclass(frozen=True, slots=True)
class QuarterEffect:
    quarter_index: int
    period_label: str
    mean_difference: float


@dataclass(frozen=True, slots=True)
class MetricEffects:
    one_at_a_time: tuple[QuarterEffect, ...]
    sequential: tuple[QuarterEffect, ...]

    @property
    def one_at_a_time_horizon(self) -> float:
        return float(sum(item.mean_difference for item in self.one_at_a_time))

    @property
    def sequential_horizon(self) -> float:
        return float(sum(item.mean_difference for item in self.sequential))


@dataclass(frozen=True, slots=True)
class ChangeContribution:
    kind: str
    name: str
    key: str
    label: str
    before: float | None
    after: float | None
    size: float | None
    intervention: dict[str, Any] | None
    effects: dict[str, MetricEffects]


@dataclass(frozen=True, slots=True)
class SensitivityEntry:
    parameter: str
    range_low: float
    range_high: float
    low_mean: float
    high_mean: float
    swing: float
    normalized_sensitivity: float


@dataclass(frozen=True, slots=True)
class RankedSensitivity:
    parameter: str
    range_low: float
    range_high: float
    low_mean: float
    high_mean: float
    swing: float
    normalized_sensitivity: float
    support_score: float
    flag: str | None


@dataclass(frozen=True, slots=True)
class AttributionResult:
    order_note: str
    sequential_order: tuple[str, ...]
    totals: dict[str, tuple[QuarterEffect, ...]]
    horizon_totals: dict[str, float]
    contributions: tuple[ChangeContribution, ...]
    joint_residual: dict[str, tuple[QuarterEffect, ...]]
    joint_residual_horizon: dict[str, float]
    sensitivity: tuple[SensitivityEntry, ...]
    sensitivity_metric: str
    baseline: SimulationResult
    variant: SimulationResult


def _dump(item: Any) -> dict[str, Any]:
    dump = getattr(item, "model_dump", None)
    if dump is None:
        raise TypeError(f"intervention {type(item).__name__} has no canonical form")
    payload = dump(mode="json")
    if not isinstance(payload, dict):
        raise TypeError("intervention dump must be an object")
    return payload


def _changed_parameters(
    baseline: Mapping[str, float],
    variant: Mapping[str, float],
) -> list[str]:
    names = sorted(set(baseline) | set(variant))
    return [name for name in names if float(baseline[name]) != float(variant[name])]


def _split_interventions(
    model: CompanyModel,
    baseline_raw: Sequence[Mapping[str, Any]],
    variant_raw: Sequence[Mapping[str, Any]],
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """Return ``(shared prefix, variant-only tail)``.

    The variant list must start with the baseline list. Removals and reorderings
    are rejected so the sequential order stays well defined.
    """
    baseline = model.parse_interventions(list(baseline_raw))
    variant = model.parse_interventions(list(variant_raw))
    shared = 0
    while shared < len(baseline) and shared < len(variant) and _dump(baseline[shared]) == _dump(variant[shared]):
        shared += 1
    if shared != len(baseline):
        raise ValueError("variant interventions must start with the baseline interventions, in the same order")
    return baseline, variant[shared:]


def _effects(delta: np.ndarray, periods: tuple[FiscalPeriod, ...]) -> tuple[QuarterEffect, ...]:
    return tuple(
        QuarterEffect(index, periods[index].label(), float(delta[index])) for index in range(int(delta.shape[0]))
    )


def _means(result: SimulationResult, metrics: tuple[str, ...]) -> dict[str, np.ndarray]:
    return {name: np.mean(result.metrics[name], axis=0) for name in metrics}


def _run(
    model: CompanyModel,
    start: StartingState,
    params: Mapping[str, float],
    interventions: Sequence[Any],
    *,
    origin: FiscalPeriod,
    seed: int,
    n_paths: int,
    n_quarters: int,
    switches: Mapping[str, bool],
    draws: np.ndarray,
) -> SimulationResult:
    return simulate(
        model,
        start,
        params,
        origin=origin,
        seed=seed,
        n_paths=n_paths,
        n_quarters=n_quarters,
        switches=switches,
        draws=draws,
        interventions=[_dump(item) for item in interventions],
    )


def _range_for(
    model: CompanyModel,
    name: str,
    ranges: Mapping[str, Sequence[float]] | None,
) -> tuple[float, float]:
    spec = next(item for item in model.parameters if item.name == name)
    raw = None if ranges is None else ranges.get(name)
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        low = min(max(float(raw[0]), spec.lower), spec.upper)
        high = min(max(float(raw[1]), spec.lower), spec.upper)
        if low > high:
            low, high = high, low
        return low, high
    return float(spec.lower), float(spec.upper)


def _horizon_or_variant(
    model: CompanyModel,
    start: StartingState,
    params: dict[str, float],
    interventions: Sequence[Any],
    *,
    origin: FiscalPeriod,
    seed: int,
    n_paths: int,
    n_quarters: int,
    switches: Mapping[str, bool],
    draws: np.ndarray,
    fallback: float,
) -> float:
    try:
        result = _run(
            model,
            start,
            params,
            interventions,
            origin=origin,
            seed=seed,
            n_paths=n_paths,
            n_quarters=n_quarters,
            switches=switches,
            draws=draws,
        )
    except ValueError:
        return fallback
    return float(np.sum(np.mean(result.metrics[SENSITIVITY_METRIC], axis=0)))


def attribute_changes(
    model: CompanyModel,
    start: StartingState,
    *,
    baseline_params: Mapping[str, float],
    variant_params: Mapping[str, float],
    baseline_interventions: Sequence[Mapping[str, Any]] | None = None,
    variant_interventions: Sequence[Mapping[str, Any]] | None = None,
    origin: FiscalPeriod,
    seed: int,
    n_paths: int,
    n_quarters: int,
    switches: Mapping[str, bool] | None = None,
    metrics: tuple[str, ...] = ATTRIBUTION_METRICS,
    ranges: Mapping[str, Sequence[float]] | None = None,
    include_sensitivity: bool = True,
) -> AttributionResult:
    """Decompose the variant-minus-baseline difference under one shared draw set."""
    unknown = [name for name in metrics if name not in {spec.name for spec in model.metrics}]
    if unknown:
        raise ValueError(f"unknown metrics: {unknown}")
    base_params = {name: float(baseline_params[name]) for name in baseline_params}
    var_params = {name: float(variant_params[name]) for name in variant_params}
    prefix, extras = _split_interventions(model, list(baseline_interventions or ()), list(variant_interventions or ()))
    switch_map = model.default_switches()
    switch_map.update({key: bool(val) for key, val in (switches or {}).items()})

    baseline = simulate(
        model,
        start,
        base_params,
        origin=origin,
        seed=seed,
        n_paths=n_paths,
        n_quarters=n_quarters,
        switches=switch_map,
        interventions=[_dump(item) for item in prefix],
    )
    draws = baseline.draws
    full_interventions = prefix + extras
    variant = _run(
        model,
        start,
        var_params,
        full_interventions,
        origin=origin,
        seed=seed,
        n_paths=n_paths,
        n_quarters=n_quarters,
        switches=switch_map,
        draws=draws,
    )
    periods = variant.periods
    base_means = _means(baseline, metrics)
    var_means = _means(variant, metrics)
    totals = {name: _effects(var_means[name] - base_means[name], periods) for name in metrics}
    horizon_totals = {name: float(sum(item.mean_difference for item in totals[name])) for name in metrics}

    param_names = _changed_parameters(base_params, var_params)
    changes: list[tuple[str, str, Any]] = [("parameter", name, None) for name in param_names]
    changes.extend(("intervention", str(_dump(item)["type"]), item) for item in extras)

    contributions: list[ChangeContribution] = []
    oat_sum = {name: np.zeros(n_quarters, dtype=np.float64) for name in metrics}
    running_params = dict(base_params)
    running_extras: list[Any] = []
    previous = {name: np.array(base_means[name], copy=True) for name in metrics}
    order: list[str] = []

    for kind, name, item in changes:
        key = f"parameter:{name}" if kind == "parameter" else f"intervention:{len(order)}:{name}"
        order.append(key)
        if kind == "parameter":
            label = (
                f"Conditional on the model, {name} moves from {float(base_params[name]):.6g} "
                f"to {float(var_params[name]):.6g}."
            )
            before_value = float(base_params[name])
            after_value = float(var_params[name])
            before: float | None = before_value
            after: float | None = after_value
            size: float | None = after_value - before_value
            payload = None
            alone_params = dict(base_params)
            alone_params[name] = float(var_params[name])
            alone_interventions: tuple[Any, ...] = prefix
            running_params[name] = float(var_params[name])
        else:
            payload = _dump(item)
            label = f"Conditional on the model, {payload['type']} applies from quarter {payload['start_quarter']}."
            before = None
            after = None
            size = None
            alone_params = dict(base_params)
            alone_interventions = prefix + (item,)
            running_extras.append(item)

        alone = _run(
            model,
            start,
            alone_params,
            alone_interventions,
            origin=origin,
            seed=seed,
            n_paths=n_paths,
            n_quarters=n_quarters,
            switches=switch_map,
            draws=draws,
        )
        sequential = _run(
            model,
            start,
            running_params,
            prefix + tuple(running_extras),
            origin=origin,
            seed=seed,
            n_paths=n_paths,
            n_quarters=n_quarters,
            switches=switch_map,
            draws=draws,
        )
        alone_means = _means(alone, metrics)
        seq_means = _means(sequential, metrics)
        effects: dict[str, MetricEffects] = {}
        for metric in metrics:
            oat_delta = alone_means[metric] - base_means[metric]
            seq_delta = seq_means[metric] - previous[metric]
            oat_sum[metric] = oat_sum[metric] + oat_delta
            previous[metric] = seq_means[metric]
            effects[metric] = MetricEffects(_effects(oat_delta, periods), _effects(seq_delta, periods))
        contributions.append(
            ChangeContribution(
                kind=kind,
                name=name,
                key=key,
                label=label,
                before=before,
                after=after,
                size=size,
                intervention=payload,
                effects=effects,
            )
        )

    residual = {name: _effects(var_means[name] - base_means[name] - oat_sum[name], periods) for name in metrics}
    residual_horizon = {name: float(sum(item.mean_difference for item in residual[name])) for name in metrics}

    sensitivity: list[SensitivityEntry] = []
    if include_sensitivity:
        variant_horizon = float(np.sum(var_means[SENSITIVITY_METRIC])) if SENSITIVITY_METRIC in var_means else 0.0
        if SENSITIVITY_METRIC not in metrics:
            variant_horizon = _horizon_or_variant(
                model,
                start,
                var_params,
                full_interventions,
                origin=origin,
                seed=seed,
                n_paths=n_paths,
                n_quarters=n_quarters,
                switches=switch_map,
                draws=draws,
                fallback=0.0,
            )
        raw_entries: list[SensitivityEntry] = []
        for spec in model.parameters:
            low, high = _range_for(model, spec.name, ranges)
            if low == high:
                raw_entries.append(SensitivityEntry(spec.name, low, high, variant_horizon, variant_horizon, 0.0, 0.0))
                continue
            low_params = dict(var_params)
            high_params = dict(var_params)
            low_params[spec.name] = low
            high_params[spec.name] = high
            low_mean = _horizon_or_variant(
                model,
                start,
                low_params,
                full_interventions,
                origin=origin,
                seed=seed,
                n_paths=n_paths,
                n_quarters=n_quarters,
                switches=switch_map,
                draws=draws,
                fallback=variant_horizon,
            )
            high_mean = _horizon_or_variant(
                model,
                start,
                high_params,
                full_interventions,
                origin=origin,
                seed=seed,
                n_paths=n_paths,
                n_quarters=n_quarters,
                switches=switch_map,
                draws=draws,
                fallback=variant_horizon,
            )
            raw_entries.append(SensitivityEntry(spec.name, low, high, low_mean, high_mean, high_mean - low_mean, 0.0))
        peak = max((abs(item.swing) for item in raw_entries), default=0.0)
        for item in raw_entries:
            normalized = abs(item.swing) / peak if peak > 0.0 else 0.0
            sensitivity.append(
                SensitivityEntry(
                    item.parameter,
                    item.range_low,
                    item.range_high,
                    item.low_mean,
                    item.high_mean,
                    item.swing,
                    normalized,
                )
            )
        sensitivity.sort(key=lambda item: (-item.normalized_sensitivity, item.parameter))

    return AttributionResult(
        order_note=ORDER_NOTE,
        sequential_order=tuple(order),
        totals=totals,
        horizon_totals=horizon_totals,
        contributions=tuple(contributions),
        joint_residual=residual,
        joint_residual_horizon=residual_horizon,
        sensitivity=tuple(sensitivity),
        sensitivity_metric=SENSITIVITY_METRIC,
        baseline=baseline,
        variant=variant,
    )


def support_score(
    observation_ids: Sequence[str],
    *,
    assumption: bool,
    review_statuses: Mapping[str, str],
) -> float:
    """Score how well a parameter is supported.

    1.0: linked observations, and the assumption flag is false.
    0.5: linked observations plus an assumption flag.
    0.0: no observations, or every linked database row is pending or rejected.
    Ids missing from ``review_statuses`` are not database rows.
    """
    linked = [str(item) for item in observation_ids]
    if not linked:
        return 0.0
    db_statuses = [review_statuses[item] for item in linked if item in review_statuses]
    if db_statuses and all(status in _UNREVIEWED for status in db_statuses):
        return 0.0
    if assumption:
        return 0.5
    return 1.0


def weak_support_flag(
    normalized_sensitivity: float, support: float, *, threshold: float = FLAG_THRESHOLD
) -> str | None:
    """Flag a high-sensitivity parameter whose support is weak. Magnitude only."""
    if normalized_sensitivity * (1.0 - support) >= threshold:
        return FLAG_NAME
    return None


def annotate_support(
    entries: Sequence[SensitivityEntry],
    *,
    evidence: Mapping[str, tuple[Sequence[str], bool]],
    review_statuses: Mapping[str, str] | None = None,
) -> list[RankedSensitivity]:
    """Attach support scores and weak-support flags. ``evidence`` is ``(ids, assumption)``."""
    statuses = review_statuses or {}
    ranked: list[RankedSensitivity] = []
    for entry in entries:
        observation_ids, assumption = evidence.get(entry.parameter, ((), False))
        score = support_score(observation_ids, assumption=assumption, review_statuses=statuses)
        ranked.append(
            RankedSensitivity(
                parameter=entry.parameter,
                range_low=entry.range_low,
                range_high=entry.range_high,
                low_mean=entry.low_mean,
                high_mean=entry.high_mean,
                swing=entry.swing,
                normalized_sensitivity=entry.normalized_sensitivity,
                support_score=score,
                flag=weak_support_flag(entry.normalized_sensitivity, score),
            )
        )
    return ranked


__all__ = [
    "ATTRIBUTION_METRICS",
    "FLAG_NAME",
    "FLAG_THRESHOLD",
    "ORDER_NOTE",
    "SENSITIVITY_METRIC",
    "AttributionResult",
    "ChangeContribution",
    "MetricEffects",
    "QuarterEffect",
    "RankedSensitivity",
    "SensitivityEntry",
    "annotate_support",
    "attribute_changes",
    "support_score",
    "weak_support_flag",
]
