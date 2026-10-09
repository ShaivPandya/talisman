"""Leakage guards for evaluation inputs and outcomes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from longaeva_app.hashing import utc_isoformat
from longaeva_app.runs.inputs import parse_aware_utc


class LeakageError(ValueError):
    """Raised when an input used for evaluation was published after the cutoff."""


def _as_utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        from datetime import UTC

        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return parse_aware_utc(value)


def assert_inputs_before_cutoff(
    cutoff: datetime,
    *,
    starting_state_sources: Mapping[str, Any] | None = None,
    calibration_evidence: Mapping[str, Mapping[str, Any]] | None = None,
    source_manifest: Sequence[Mapping[str, Any]] | None = None,
    driver_history: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Raise ``LeakageError`` if any used input was published after ``cutoff``."""
    cutoff_utc = _as_utc(cutoff)
    late: list[str] = []

    if starting_state_sources:
        for source_id, ref in starting_state_sources.items():
            role = getattr(ref, "role", None) or (ref.get("role") if isinstance(ref, Mapping) else None)
            if role not in {None, "input"}:
                continue
            acceptance = getattr(ref, "acceptance_utc", None) or (
                ref.get("acceptance_utc") if isinstance(ref, Mapping) else None
            )
            if acceptance is None:
                continue
            published = _as_utc(acceptance)
            if published > cutoff_utc:
                late.append(f"starting_state source {source_id} at {utc_isoformat(published)}")

    if calibration_evidence:
        for obs_id, payload in calibration_evidence.items():
            published_raw = payload.get("publication_ts") or payload.get("acceptance_utc")
            if published_raw is None:
                continue
            published = _as_utc(str(published_raw))
            if published > cutoff_utc:
                late.append(f"calibration evidence {obs_id} at {utc_isoformat(published)}")

    if source_manifest:
        for entry in source_manifest:
            published_raw = entry.get("publication_ts")
            if published_raw is None:
                continue
            published = _as_utc(str(published_raw))
            if published > cutoff_utc:
                key = entry.get("document_key", "?")
                late.append(f"run manifest {key} at {utc_isoformat(published)}")

    if driver_history:
        for entry in driver_history:
            published_raw = entry.get("publication_ts")
            if published_raw is None:
                continue
            published = _as_utc(str(published_raw))
            if published > cutoff_utc:
                label = entry.get("label", entry.get("field", "?"))
                late.append(f"driver history {label} at {utc_isoformat(published)}")

    if late:
        raise LeakageError(f"leakage: inputs published after cutoff {utc_isoformat(cutoff_utc)}: " + "; ".join(late))


def assert_outcome_after_cutoff(
    cutoff: datetime,
    *,
    publication_ts: datetime | str,
    label: str,
) -> None:
    """Raise if an actual used for scoring was published at or before the cutoff."""
    cutoff_utc = _as_utc(cutoff)
    published = _as_utc(publication_ts)
    if published <= cutoff_utc:
        raise LeakageError(
            f"leakage: outcome {label} published at {utc_isoformat(published)} "
            f"is not after cutoff {utc_isoformat(cutoff_utc)}"
        )


def input_fingerprint(
    *,
    starting_state_source_ids: Iterable[str],
    evidence_ids: Iterable[str],
    manifest_keys: Iterable[str],
    driver_labels: Iterable[str],
) -> dict[str, list[str]]:
    """Stable fingerprint of inputs used for an origin (for poison-row tests)."""
    return {
        "starting_state_sources": sorted(starting_state_source_ids),
        "evidence_ids": sorted(evidence_ids),
        "manifest_keys": sorted(manifest_keys),
        "driver_labels": sorted(driver_labels),
    }


__all__ = [
    "LeakageError",
    "assert_inputs_before_cutoff",
    "assert_outcome_after_cutoff",
    "input_fingerprint",
]
