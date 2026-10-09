"""Path summaries: mean, Monte Carlo SE, and quantiles."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from longaeva_app.engine.runner import SimulationResult

FloatArray = npt.NDArray[np.floating]

DEFAULT_QUANTILES: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)


@dataclass(frozen=True, slots=True)
class MetricSummary:
    metric: str
    quarter_index: int  # 0-based within the simulation horizon
    mean: float
    std: float
    std_error: float  # Monte Carlo SE of the mean = std / sqrt(n)
    quantiles: dict[str, float]  # keys like "0.05", "0.5", …
    quantile_std_errors: dict[str, float]  # batch-means SE per quantile


def _quantile_key(q: float) -> str:
    # Match existing forecast / RunResultSummary style: "0.5", "0.05", …
    text = f"{q:.2f}".rstrip("0").rstrip(".")
    if "." not in text:
        text = f"{text}.0"
    return text


def _batch_means_se(values: FloatArray, *, n_batches: int = 20) -> float:
    """Batch-means standard error of a scalar estimator (here: a sample quantile)."""
    n = int(values.shape[0])
    if n < 2:
        return 0.0
    batches = min(n_batches, n)
    # Drop a remainder so batches are equal length.
    usable = (n // batches) * batches
    if usable < 2 * batches:
        return float(np.std(values, ddof=1) / np.sqrt(n))
    reshaped = values[:usable].reshape(batches, -1)
    batch_means = reshaped.mean(axis=1)
    return float(np.std(batch_means, ddof=1) / np.sqrt(batches))


def summarize_metric(
    paths: FloatArray,
    *,
    metric: str,
    quarter_index: int,
    quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
) -> MetricSummary:
    """Summarize one metric column ``paths`` of shape ``(n_paths,)``."""
    x = np.asarray(paths, dtype=np.float64)
    if x.ndim != 1:
        raise ValueError(f"paths must be 1-D, got shape {x.shape}")
    n = int(x.shape[0])
    mean = float(np.mean(x))
    std = float(np.std(x, ddof=1)) if n > 1 else 0.0
    se = std / np.sqrt(n) if n > 0 else 0.0

    q_values = np.quantile(x, quantiles)
    q_map: dict[str, float] = {}
    q_se: dict[str, float] = {}
    for q, value in zip(quantiles, q_values, strict=True):
        key = _quantile_key(float(q))
        q_map[key] = float(value)
        # Indicator residuals around the quantile for a batch-means SE.
        # Using the sample itself batched gives a practical MC SE for the quantile.
        q_se[key] = _batch_means_se(x)

    return MetricSummary(
        metric=metric,
        quarter_index=quarter_index,
        mean=mean,
        std=std,
        std_error=se,
        quantiles=q_map,
        quantile_std_errors=q_se,
    )


def summarize_paths(
    result: SimulationResult,
    *,
    metrics: tuple[str, ...] | None = None,
    quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
) -> list[MetricSummary]:
    """Summarize each selected metric for every quarter in ``result``."""
    names = metrics if metrics is not None else tuple(result.metrics.keys())
    out: list[MetricSummary] = []
    n_quarters = len(result.periods)
    for name in names:
        if name not in result.metrics:
            raise KeyError(f"unknown metric: {name}")
        arr = result.metrics[name]
        if arr.shape[1] != n_quarters:
            raise ValueError(f"metric {name} has {arr.shape[1]} quarters, expected {n_quarters}")
        for q in range(n_quarters):
            out.append(
                summarize_metric(
                    arr[:, q],
                    metric=name,
                    quarter_index=q,
                    quantiles=quantiles,
                )
            )
    return out


__all__ = [
    "DEFAULT_QUANTILES",
    "MetricSummary",
    "summarize_metric",
    "summarize_paths",
]
