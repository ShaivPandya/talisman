"""Scoring metrics for the evaluation harness (LON-27 / ER-05 / ER-06)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.floating[Any]]

# Avoid literal 0.01 / 0.03 outside companies/visa; still keep named constants here.
_HALF = 0.5
_COVERAGE_LO = 0.1
_COVERAGE_HI = 0.9
DEFAULT_QUANTILES: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)
WIS_INTERVALS: tuple[tuple[float, float], ...] = ((0.05, 0.95), (0.1, 0.9), (0.25, 0.75))


@dataclass(frozen=True, slots=True)
class PointScores:
    mean: float
    median: float
    signed_error: float
    abs_error: float
    pct_error: float | None
    covered_80: bool
    crps: float
    wis: float
    quantiles: dict[str, float]


def _quantile_key(q: float) -> str:
    text = f"{q:.12g}"
    return text


def empirical_crps(samples: Sequence[float] | FloatArray, actual: float) -> float:
    """Exact sample CRPS: E|X-y| - 0.5 E|X-X'| via the sorted O(n log n) form."""
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    if x.size == 0:
        raise ValueError("CRPS requires at least one sample")
    y = float(actual)
    ordered = np.sort(x)
    n = ordered.size
    # E|X - y|
    mean_abs = float(np.mean(np.abs(ordered - y)))
    # E|X - X'| = (2 / n^2) * sum_i (2i - n - 1) * x_(i)
    indices = np.arange(1, n + 1, dtype=np.float64)
    coef = 2.0 * indices - n - 1.0
    mean_abs_xx = float(np.dot(coef, ordered) * 2.0 / (n * n))
    return mean_abs - _HALF * mean_abs_xx


def empirical_crps_quadratic(samples: Sequence[float] | FloatArray, actual: float) -> float:
    """O(n²) CRPS for tests against the sorted form."""
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    y = float(actual)
    mean_abs = float(np.mean(np.abs(x - y)))
    diffs = np.abs(x[:, None] - x[None, :])
    mean_abs_xx = float(np.mean(diffs))
    return mean_abs - _HALF * mean_abs_xx


def weighted_interval_score(
    quantiles: Mapping[str, float],
    actual: float,
    *,
    intervals: Sequence[tuple[float, float]] = WIS_INTERVALS,
) -> float:
    """WIS from central intervals plus the median (absolute error term)."""
    y = float(actual)
    median = float(quantiles[_quantile_key(0.5)])
    score = abs(median - y)
    for lo_q, hi_q in intervals:
        alpha = 1.0 - (hi_q - lo_q)
        lower = float(quantiles[_quantile_key(lo_q)])
        upper = float(quantiles[_quantile_key(hi_q)])
        width = upper - lower
        under = lower - y if y < lower else 0.0
        over = y - upper if y > upper else 0.0
        score += (alpha / 2.0) * width + under + over
    # Average over (median term + intervals): Gneiting WIS divides by (K+1/2)?
    # Common forecasting form: (1/(K+0.5)) * (...). Use equal weight sum normalized by K+1.
    k = len(intervals)
    return score / (k + 1.0)


def covered_80(quantiles: Mapping[str, float], actual: float) -> bool:
    lo = float(quantiles[_quantile_key(_COVERAGE_LO)])
    hi = float(quantiles[_quantile_key(_COVERAGE_HI)])
    y = float(actual)
    return lo <= y <= hi


def score_quantiles(
    quantiles: Mapping[str, float], actual: float, *, percentage_error: bool = True
) -> dict[str, float | None]:
    """Exact shared quantile scores. Seven quantiles do not define a mean or CRPS."""
    values = [float(quantiles[_quantile_key(q)]) for q in DEFAULT_QUANTILES]
    if not np.all(np.isfinite(values)) or any(a > b for a, b in zip(values, values[1:], strict=False)):
        raise ValueError("Quantiles must be finite and nondecreasing")
    y = float(actual)
    median = float(quantiles["0.5"])
    signed = median - y
    return {
        "median": median,
        "signed_error": signed,
        "abs_error": abs(signed),
        "pct_error": abs(signed) / abs(y) if percentage_error and y != 0.0 else None,
        "covered_80": float(covered_80(quantiles, y)),
        "wis": weighted_interval_score(quantiles, y),
    }


def score_samples(
    samples: Sequence[float] | FloatArray,
    actual: float,
    *,
    quantiles: Sequence[float] = DEFAULT_QUANTILES,
    percentage_error: bool = True,
) -> PointScores:
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    if x.size == 0:
        raise ValueError("score_samples requires at least one sample")
    y = float(actual)
    q_values = np.quantile(x, list(quantiles))
    q_map = {_quantile_key(q): float(v) for q, v in zip(quantiles, q_values, strict=True)}
    median = float(q_map[_quantile_key(0.5)])
    mean = float(np.mean(x))
    signed = median - y
    abs_err = abs(signed)
    pct: float | None
    if percentage_error:
        if y == 0.0:
            pct = None
        else:
            pct = abs_err / abs(y)
    else:
        pct = None
    return PointScores(
        mean=mean,
        median=median,
        signed_error=signed,
        abs_error=abs_err,
        pct_error=pct,
        covered_80=covered_80(q_map, y),
        crps=empirical_crps(x, y),
        wis=weighted_interval_score(q_map, y),
        quantiles=q_map,
    )


@dataclass(frozen=True, slots=True)
class AggregateScores:
    n: int
    mae: float | None
    bias: float | None
    mape: float | None
    covered_k: int
    covered_n: int
    mean_crps: float | None
    mean_wis: float | None


def aggregate_scores(rows: Sequence[Mapping[str, Any]]) -> AggregateScores:
    """Aggregate per-origin score dicts with keys abs_error, signed_error, pct_error, covered_80, crps, wis."""
    n = len(rows)
    if n == 0:
        return AggregateScores(
            n=0,
            mae=None,
            bias=None,
            mape=None,
            covered_k=0,
            covered_n=0,
            mean_crps=None,
            mean_wis=None,
        )
    abs_errors = [float(r["abs_error"]) for r in rows]
    signed = [float(r["signed_error"]) for r in rows]
    pcts = [float(r["pct_error"]) for r in rows if r.get("pct_error") is not None]
    covered = [bool(r["covered_80"]) for r in rows]
    crps = [float(r["crps"]) for r in rows if r.get("crps") is not None]
    wis = [float(r["wis"]) for r in rows if r.get("wis") is not None]
    return AggregateScores(
        n=n,
        mae=float(np.mean(abs_errors)),
        bias=float(np.mean(signed)),
        mape=float(np.mean(pcts)) if pcts else None,
        covered_k=sum(1 for flag in covered if flag),
        covered_n=n,
        mean_crps=float(np.mean(crps)) if crps else None,
        mean_wis=float(np.mean(wis)) if wis else None,
    )


def aggregate_to_dict(agg: AggregateScores) -> dict[str, Any]:
    return {
        "n": agg.n,
        "mae": agg.mae,
        "bias": agg.bias,
        "mape": agg.mape,
        "covered_k": agg.covered_k,
        "covered_n": agg.covered_n,
        "coverage": f"{agg.covered_k} of {agg.covered_n}" if agg.n else "0 of 0",
        "mean_crps": agg.mean_crps,
        "mean_wis": agg.mean_wis,
    }


__all__ = [
    "AggregateScores",
    "DEFAULT_QUANTILES",
    "PointScores",
    "WIS_INTERVALS",
    "aggregate_scores",
    "aggregate_to_dict",
    "covered_80",
    "empirical_crps",
    "empirical_crps_quadratic",
    "score_samples",
    "score_quantiles",
    "weighted_interval_score",
]
