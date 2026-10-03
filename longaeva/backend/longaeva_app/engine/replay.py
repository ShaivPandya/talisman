"""Replay comparison of a saved run against a fresh simulation (LON-23 / ER-03)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from longaeva_app.engine.outputs import (
    RELATIVE_TOLERANCE,
    canonical_outputs_hash,
    max_relative_difference,
    max_summary_relative_difference,
)
from longaeva_app.engine.runner import SimulationResult

ReplayStatus = Literal["exact_match", "numerically_equivalent", "mismatch", "inputs_changed"]


@dataclass(frozen=True, slots=True)
class ReplayComparison:
    status: ReplayStatus
    recorded_hash: str
    recomputed_hash: str
    max_relative_difference: float
    differences: list[str] = field(default_factory=list)


def compare_simulation(
    result: SimulationResult,
    *,
    recorded_hash: str,
    recorded_metrics: dict[str, Any] | None = None,
    recorded_states: dict[str, Any] | None = None,
    recorded_summary: list[dict[str, Any]] | None = None,
    recomputed_summary: list[dict[str, Any]] | None = None,
    recorded_code_version: str = "",
    recomputed_code_version: str = "",
    recorded_lib_versions: dict[str, Any] | None = None,
    recomputed_lib_versions: dict[str, Any] | None = None,
) -> ReplayComparison:
    """Compare a fresh simulation to the recorded hash and stored arrays or summary."""
    recomputed_hash = canonical_outputs_hash(result)
    differences: list[str] = []
    if recorded_hash != recomputed_hash:
        differences.append("outputs_hash")
    if recorded_code_version and recomputed_code_version and recorded_code_version != recomputed_code_version:
        differences.append(f"code_version: {recorded_code_version} -> {recomputed_code_version}")
    rec_libs = recorded_lib_versions or {}
    new_libs = recomputed_lib_versions or {}
    for key in sorted(set(rec_libs) | set(new_libs)):
        if rec_libs.get(key) != new_libs.get(key):
            differences.append(f"lib_versions.{key}: {rec_libs.get(key)!r} -> {new_libs.get(key)!r}")

    if recorded_hash == recomputed_hash:
        return ReplayComparison(
            status="exact_match",
            recorded_hash=recorded_hash,
            recomputed_hash=recomputed_hash,
            max_relative_difference=0.0,
            differences=[],
        )

    rel = float("inf")
    if recorded_metrics is not None and recorded_states is not None:
        rel = max(
            max_relative_difference(recorded_metrics, result.metrics),
            max_relative_difference(recorded_states, result.states),
        )
    elif recorded_summary is not None and recomputed_summary is not None:
        rel = max_summary_relative_difference(recorded_summary, recomputed_summary)

    status: ReplayStatus
    if rel <= RELATIVE_TOLERANCE:
        status = "numerically_equivalent"
    else:
        status = "mismatch"
        differences.append(f"max_relative_difference={rel}")
    return ReplayComparison(
        status=status,
        recorded_hash=recorded_hash,
        recomputed_hash=recomputed_hash,
        max_relative_difference=rel,
        differences=differences,
    )


__all__ = [
    "ReplayComparison",
    "ReplayStatus",
    "compare_simulation",
]
