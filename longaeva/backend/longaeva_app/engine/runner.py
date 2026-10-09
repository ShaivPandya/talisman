"""Company-agnostic path runner with per-path identity checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from longaeva_app.companies.base import CompanyModel, FiscalPeriod, PathArrays, StartingState
from longaeva_app.engine.sampler import correlate_draws, draw_factors, factor_root

FloatArray = npt.NDArray[np.floating]


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Path-complete outputs from ``simulate``."""

    metrics: dict[str, FloatArray]  # name -> (n_paths, n_quarters)
    states: dict[str, FloatArray]  # name -> (n_paths, n_quarters) end-of-quarter state
    draws: FloatArray  # correlated (n_paths, n_quarters, n_factors)
    periods: tuple[FiscalPeriod, ...]
    seed: int
    n_paths: int
    switches: dict[str, bool]
    params: dict[str, float]


class IdentityViolationError(ValueError):
    """Raised when an accounting identity fails on any path."""


def _check_identities(model: CompanyModel, metrics: PathArrays, *, n_paths: int, period: FiscalPeriod) -> None:
    for identity in model.identities:
        result = np.asarray(metrics[identity.result], dtype=np.float64)
        total = np.zeros(n_paths, dtype=np.float64)
        for term in identity.terms:
            total = total + term.sign * np.asarray(metrics[term.metric], dtype=np.float64)
        denom = np.maximum(np.abs(result), 1.0)
        rel = np.abs(result - total) / denom
        if not bool(np.all(rel <= identity.relative_tolerance)):
            worst = int(np.argmax(rel))
            raise IdentityViolationError(
                f"identity {identity.result!r} failed at {period.label()} "
                f"path={worst} rel={float(rel[worst]):.3e} "
                f"(tol={identity.relative_tolerance})"
            )


def _validate_switches(model: CompanyModel, switches: Mapping[str, bool]) -> dict[str, bool]:
    known = {spec.name for spec in model.switches}
    unknown = sorted(set(switches) - known)
    if unknown:
        raise ValueError(f"unknown switches: {unknown}")
    merged = model.default_switches()
    merged.update({k: bool(v) for k, v in switches.items()})
    return merged


def simulate(
    model: CompanyModel,
    start: StartingState,
    params: Mapping[str, float],
    *,
    origin: FiscalPeriod,
    seed: int,
    n_paths: int = 5000,
    n_quarters: int = 4,
    switches: Mapping[str, bool] | None = None,
    draws: FloatArray | None = None,
    interventions: Sequence[Mapping[str, Any]] | None = None,
) -> SimulationResult:
    """Run ``n_quarters`` transitions from the quarter *after* ``origin``.

    ``origin`` is the starting-state fiscal period (already realized). The first
    simulated period is ``origin.next()``.
    """
    if n_paths < 1:
        raise ValueError("n_paths must be >= 1")
    if n_quarters < 1:
        raise ValueError("n_quarters must be >= 1")

    param_errors = model.validate_parameters(params)
    if param_errors:
        raise ValueError(f"invalid parameters: {param_errors}")
    param_map = {name: float(params[name]) for name in (spec.name for spec in model.parameters)}
    switch_map = _validate_switches(model, switches or {})
    parsed_interventions = model.parse_interventions(list(interventions or ()))
    for item in parsed_interventions:
        start_quarter = int(item.start_quarter)
        if start_quarter > n_quarters:
            raise ValueError(f"intervention start_quarter {start_quarter} is past the horizon of {n_quarters}")

    n_factors = len(model.factors)
    if draws is None:
        raw = draw_factors(n_paths=n_paths, n_quarters=n_quarters, n_factors=n_factors, seed=seed)
        root = factor_root(model.factor_correlation(param_map))
        correlated = correlate_draws(raw, root)
    else:
        correlated = np.asarray(draws, dtype=np.float64)
        if correlated.shape != (n_paths, n_quarters, n_factors):
            raise ValueError(f"draws shape {correlated.shape} != ({n_paths}, {n_quarters}, {n_factors})")

    state = model.initial_state(start, param_map, n_paths)
    metric_hist: dict[str, list[FloatArray]] = {m.name: [] for m in model.metrics}
    state_hist: dict[str, list[FloatArray]] = {s.name: [] for s in model.state_variables}
    periods: list[FiscalPeriod] = []

    period = origin.next()
    for q in range(n_quarters):
        shock: PathArrays = {name: correlated[:, q, i] for i, name in enumerate(model.factors)}
        # Defensive copies so company code cannot mutate shared arrays unnoticed.
        state_in: PathArrays = {k: np.array(v, dtype=np.float64, copy=True) for k, v in state.items()}
        shock_in: PathArrays = {k: np.array(v, dtype=np.float64, copy=True) for k, v in shock.items()}
        active = tuple(item for item in parsed_interventions if int(item.start_quarter) == q + 1)
        step = model.transition(state_in, shock_in, param_map, switch_map, period, interventions=active)

        for key, arr in state_in.items():
            if not np.array_equal(arr, state[key]):
                raise RuntimeError(f"transition mutated input state[{key!r}]")
        for key, arr in shock_in.items():
            if not np.array_equal(arr, shock[key]):
                raise RuntimeError(f"transition mutated input shocks[{key!r}]")

        for m in model.metrics:
            if m.name not in step.metrics:
                raise KeyError(f"transition omitted metric {m.name!r}")
            values = np.asarray(step.metrics[m.name], dtype=np.float64)
            if values.shape != (n_paths,):
                raise ValueError(f"metric {m.name} shape {values.shape} != ({n_paths},)")
            metric_hist[m.name].append(values)
        for s in model.state_variables:
            if s.name not in step.state:
                raise KeyError(f"transition omitted state {s.name!r}")
            values = np.asarray(step.state[s.name], dtype=np.float64)
            if values.shape != (n_paths,):
                raise ValueError(f"state {s.name} shape {values.shape} != ({n_paths},)")
            state_hist[s.name].append(values)

        _check_identities(model, step.metrics, n_paths=n_paths, period=period)
        state = step.state
        periods.append(period)
        period = period.next()

    metrics_out = {name: np.stack(series, axis=1) for name, series in metric_hist.items()}
    states_out = {name: np.stack(series, axis=1) for name, series in state_hist.items()}
    return SimulationResult(
        metrics=metrics_out,
        states=states_out,
        draws=correlated,
        periods=tuple(periods),
        seed=seed,
        n_paths=n_paths,
        switches=switch_map,
        params=param_map,
    )


__all__ = [
    "IdentityViolationError",
    "SimulationResult",
    "simulate",
]
