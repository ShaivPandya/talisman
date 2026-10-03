"""Canonical path-output hashing, npz artifacts, and summary payloads (LON-23)."""

from __future__ import annotations

import hashlib
import io
from typing import Any

import numpy as np
import numpy.typing as npt

from longaeva_app.engine.runner import SimulationResult
from longaeva_app.engine.summary import summarize_paths
from longaeva_app.hashing import canonical_json

FloatArray = npt.NDArray[np.floating]

OUTPUTS_FORMAT_VERSION = 1
OUTPUTS_DTYPE = "<f8"
RELATIVE_TOLERANCE = 1e-9


def _le_float64(arr: npt.NDArray[Any]) -> npt.NDArray[np.float64]:
    return np.asarray(arr, dtype=np.float64).astype(OUTPUTS_DTYPE, copy=False)


def canonical_outputs_hash(result: SimulationResult) -> str:
    """SHA-256 of a canonical header plus little-endian float64 path bytes."""
    digest = hashlib.sha256()
    header = {
        "dtype": "float64",
        "format_version": OUTPUTS_FORMAT_VERSION,
        "metrics": sorted(result.metrics),
        "n_paths": int(result.n_paths),
        "n_quarters": len(result.periods),
        "periods": [period.label() for period in result.periods],
        "states": sorted(result.states),
    }
    digest.update(canonical_json(header).encode("utf-8"))
    for name in sorted(result.metrics):
        arr = _le_float64(result.metrics[name])
        digest.update(b"metric:")
        digest.update(name.encode("utf-8"))
        digest.update(b":")
        digest.update(arr.tobytes(order="C"))
    for name in sorted(result.states):
        arr = _le_float64(result.states[name])
        digest.update(b"state:")
        digest.update(name.encode("utf-8"))
        digest.update(b":")
        digest.update(arr.tobytes(order="C"))
    return digest.hexdigest()


def simulation_to_npz_bytes(result: SimulationResult) -> bytes:
    """Serialize metric and state arrays. The npz bytes are not the hashed object."""
    payload: dict[str, npt.NDArray[Any]] = {
        "_periods": np.array([period.label() for period in result.periods], dtype=object),
    }
    for name, arr in result.metrics.items():
        payload[f"metric:{name}"] = _le_float64(arr)
    for name, arr in result.states.items():
        payload[f"state:{name}"] = _le_float64(arr)
    buf = io.BytesIO()
    np.savez_compressed(buf, **payload)  # type: ignore[arg-type]
    return buf.getvalue()


def load_npz_arrays(data: bytes) -> tuple[dict[str, FloatArray], dict[str, FloatArray], list[str]]:
    """Return ``(metrics, states, period_labels)`` from a paths.npz payload."""
    with np.load(io.BytesIO(data), allow_pickle=True) as handle:
        metrics: dict[str, FloatArray] = {}
        states: dict[str, FloatArray] = {}
        periods = [str(item) for item in handle["_periods"].tolist()]
        for key in handle.files:
            if key == "_periods":
                continue
            arr = np.asarray(handle[key], dtype=np.float64)
            if key.startswith("metric:"):
                metrics[key.removeprefix("metric:")] = arr
            elif key.startswith("state:"):
                states[key.removeprefix("state:")] = arr
    return metrics, states, periods


def summary_payload(result: SimulationResult) -> list[dict[str, Any]]:
    """Per-metric, per-quarter summaries matching ``RunResultSummary``."""
    out: list[dict[str, Any]] = []
    for item in summarize_paths(result):
        period = result.periods[item.quarter_index]
        out.append(
            {
                "metric": item.metric,
                "quarter_index": item.quarter_index,
                "period_label": period.label(),
                "mean": item.mean,
                "std": item.std,
                "std_error": item.std_error,
                "quantiles": item.quantiles,
                "quantile_std_errors": item.quantile_std_errors,
            }
        )
    return out


def max_relative_difference(
    left: dict[str, FloatArray],
    right: dict[str, FloatArray],
) -> float:
    """Maximum relative difference across equally named arrays."""
    names = set(left) | set(right)
    if not names:
        return 0.0
    worst = 0.0
    for name in names:
        if name not in left or name not in right:
            return float("inf")
        a = np.asarray(left[name], dtype=np.float64)
        b = np.asarray(right[name], dtype=np.float64)
        if a.shape != b.shape:
            return float("inf")
        denom = np.maximum(np.maximum(np.abs(a), np.abs(b)), 1.0)
        worst = max(worst, float(np.max(np.abs(a - b) / denom)))
    return worst


def max_summary_relative_difference(
    recorded: list[dict[str, Any]],
    recomputed: list[dict[str, Any]],
) -> float:
    """Fallback comparison when path arrays are unavailable."""
    if len(recorded) != len(recomputed):
        return float("inf")
    worst = 0.0
    for left, right in zip(recorded, recomputed, strict=True):
        if left.get("metric") != right.get("metric") or left.get("quarter_index") != right.get("quarter_index"):
            return float("inf")
        for key in ("mean", "std", "std_error"):
            a = float(left[key])
            b = float(right[key])
            denom = max(abs(a), abs(b), 1.0)
            worst = max(worst, abs(a - b) / denom)
        lq = left.get("quantiles") or {}
        rq = right.get("quantiles") or {}
        for qkey in set(lq) | set(rq):
            if qkey not in lq or qkey not in rq:
                return float("inf")
            a = float(lq[qkey])
            b = float(rq[qkey])
            denom = max(abs(a), abs(b), 1.0)
            worst = max(worst, abs(a - b) / denom)
    return worst


__all__ = [
    "OUTPUTS_DTYPE",
    "OUTPUTS_FORMAT_VERSION",
    "RELATIVE_TOLERANCE",
    "canonical_outputs_hash",
    "load_npz_arrays",
    "max_relative_difference",
    "max_summary_relative_difference",
    "simulation_to_npz_bytes",
    "summary_payload",
]
