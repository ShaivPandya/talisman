"""Path-wise differences between two saved simulations (LON-22 / FR-10)."""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from longaeva_app.engine.summary import summarize_metric

FloatArray = npt.NDArray[np.floating]


def condition_mismatches(
    *,
    left_seed: int,
    right_seed: int,
    left_paths: int,
    right_paths: int,
    left_quarters: int,
    right_quarters: int,
    left_cutoff: str,
    right_cutoff: str,
    left_origin: str,
    right_origin: str,
    left_switches: dict[str, Any],
    right_switches: dict[str, Any],
) -> list[str]:
    """Return the condition names that differ. An empty list means the runs are a pair."""
    mismatches: list[str] = []
    if left_seed != right_seed:
        mismatches.append("seed")
    if left_paths != right_paths:
        mismatches.append("n_paths")
    if left_quarters != right_quarters:
        mismatches.append("n_quarters")
    if left_cutoff != right_cutoff:
        mismatches.append("cutoff_ts")
    if left_origin != right_origin:
        mismatches.append("origin_label")
    if dict(left_switches) != dict(right_switches):
        mismatches.append("switches")
    return mismatches


def summarize_differences(
    variant_metrics: dict[str, FloatArray],
    baseline_metrics: dict[str, FloatArray],
    period_labels: list[str],
) -> list[dict[str, Any]]:
    """Quantiles of ``variant - baseline`` for each shared metric and quarter.

    The arrays are the saved path outputs. Nothing is re-simulated here.
    """
    names = sorted(set(variant_metrics) & set(baseline_metrics))
    rows: list[dict[str, Any]] = []
    for name in names:
        variant = np.asarray(variant_metrics[name], dtype=np.float64)
        baseline = np.asarray(baseline_metrics[name], dtype=np.float64)
        if variant.shape != baseline.shape:
            raise ValueError(f"metric {name} shape {variant.shape} != baseline {baseline.shape}")
        if variant.shape[1] != len(period_labels):
            raise ValueError(f"metric {name} has {variant.shape[1]} quarters, expected {len(period_labels)}")
        for quarter, label in enumerate(period_labels):
            diff = variant[:, quarter] - baseline[:, quarter]
            summary = summarize_metric(diff, metric=name, quarter_index=quarter)
            rows.append(
                {
                    "metric": name,
                    "quarter_index": quarter,
                    "period_label": label,
                    "baseline_mean": float(np.mean(baseline[:, quarter])),
                    "variant_mean": float(np.mean(variant[:, quarter])),
                    "difference_mean": summary.mean,
                    "difference_std": summary.std,
                    "difference_std_error": summary.std_error,
                    "quantiles": summary.quantiles,
                    "quantile_std_errors": summary.quantile_std_errors,
                }
            )
    return rows


__all__ = [
    "condition_mismatches",
    "summarize_differences",
]
