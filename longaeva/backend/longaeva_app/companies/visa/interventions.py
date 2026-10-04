"""Visa engine interventions (LON-22 / FR-10, MR-11).

Both interventions are persistent level shifts. They are applied once, in the
quarter named by ``start_quarter`` (1-based within the simulated horizon), after
the activity step. Later quarters inherit the shifted state, so the change
persists without being re-applied.

``mix_shift_conserving_total`` rescales the cross-border share and leaves total
payments volume untouched, so domestic volume absorbs the difference.

``total_spend_reduction`` scales nominal payments volume and the constant-dollar
index. Processed transactions are left unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from longaeva_app.hashing import content_hash

FloatArray = npt.NDArray[np.float64]
InputArray = npt.NDArray[np.floating[Any]]

INTERVENTION_TYPES: tuple[str, ...] = ("mix_shift_conserving_total", "total_spend_reduction")

# SHA-256 of the canonical JSON ``[]``. Migration 0006 backfills this literal.
EMPTY_INTERVENTIONS_HASH = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"


class InterventionError(ValueError):
    """An intervention cannot be applied on the current paths."""


class _InterventionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_quarter: int = Field(default=1, ge=1, le=8)


class MixShiftConservingTotal(_InterventionModel):
    type: Literal["mix_shift_conserving_total"]
    cross_border_change: float = Field(gt=-1.0, le=3.0)


class TotalSpendReduction(_InterventionModel):
    type: Literal["total_spend_reduction"]
    reduction: float = Field(gt=0.0, lt=1.0)


VisaIntervention = Annotated[
    MixShiftConservingTotal | TotalSpendReduction,
    Field(discriminator="type"),
]

_ADAPTER: TypeAdapter[VisaIntervention] = TypeAdapter(VisaIntervention)


def parse_visa_interventions(raw: Sequence[Mapping[str, Any]]) -> tuple[VisaIntervention, ...]:
    """Validate a scenario's intervention list. An empty list is the baseline."""
    parsed: list[VisaIntervention] = []
    for index, item in enumerate(raw):
        try:
            parsed.append(_ADAPTER.validate_python(dict(item)))
        except ValidationError as exc:
            raise ValueError(f"invalid intervention at index {index}: {exc}") from exc
    return tuple(parsed)


def canonical_interventions(items: Sequence[VisaIntervention]) -> list[dict[str, Any]]:
    """JSON-ready records with defaults filled in, in list order."""
    return [item.model_dump(mode="json") for item in items]


def interventions_content_hash(items: Sequence[VisaIntervention]) -> str:
    """Stable hash of a parsed intervention list. The empty list has a fixed digest."""
    digest = content_hash(canonical_interventions(items))
    if not items and digest != EMPTY_INTERVENTIONS_HASH:
        raise RuntimeError("empty intervention hash drifted from the migration backfill")
    return digest


def apply_level_shifts(
    *,
    payments_volume: InputArray,
    index_constant: InputArray,
    cross_border_share: InputArray,
    interventions: Sequence[VisaIntervention],
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Apply this quarter's interventions. Does not mutate the inputs.

    Interventions run in list order. A mix shift that would push any path's
    cross-border share out of (0, 1) is rejected.
    """
    pv = np.array(payments_volume, dtype=np.float64, copy=True)
    index = np.array(index_constant, dtype=np.float64, copy=True)
    share = np.array(cross_border_share, dtype=np.float64, copy=True)
    for item in interventions:
        if isinstance(item, MixShiftConservingTotal):
            share = np.asarray(share * (1.0 + float(item.cross_border_change)), dtype=np.float64)
            if bool(np.any((share <= 0.0) | (share >= 1.0) | ~np.isfinite(share))):
                raise InterventionError(
                    "mix_shift_conserving_total would move cross-border share outside (0, 1) on at least one path"
                )
        elif isinstance(item, TotalSpendReduction):
            scale = 1.0 - float(item.reduction)
            pv = np.asarray(pv * scale, dtype=np.float64)
            index = np.asarray(index * scale, dtype=np.float64)
        else:
            raise InterventionError(f"unsupported intervention type: {getattr(item, 'type', type(item))!r}")
    return (
        np.asarray(pv, dtype=np.float64),
        np.asarray(index, dtype=np.float64),
        np.asarray(share, dtype=np.float64),
    )


__all__ = [
    "EMPTY_INTERVENTIONS_HASH",
    "INTERVENTION_TYPES",
    "InterventionError",
    "MixShiftConservingTotal",
    "TotalSpendReduction",
    "VisaIntervention",
    "apply_level_shifts",
    "canonical_interventions",
    "interventions_content_hash",
    "parse_visa_interventions",
]
