"""Financial-only driver-model baseline.

Same harness path as ``full_model``, with no external mapping rules applied.
Booking, Census and the second-wave families are recorded as excluded. It matches the
``no_external_commentary`` ablation, rebuilt from the calibrated parent.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.evaluation.baselines.common import SUITE_VERSION
from longaeva_app.evaluation.harness import (
    DEFAULT_BASE_SEED,
    DEFAULT_N_PATHS,
    CalibrateFn,
    EvaluationReport,
    run_evaluation,
)
from longaeva_app.storage.local import LocalArtifactStore

VARIANT = "financial_only"
METHOD = "financial_only"
LABEL = "financial-only"
# Families the mapping-rule registry can update. None are applied here.
EXTERNAL_FAMILIES_EXCLUDED: tuple[str, ...] = (
    "booking",
    "census",
    "airline",
    "retailer",
    "processor",
)


def baseline_payload() -> dict[str, Any]:
    return {
        "method": METHOD,
        "label": LABEL,
        "external_updates": [],
        "external_families_excluded": list(EXTERNAL_FAMILIES_EXCLUDED),
    }


def run_financial_only(
    factory: sessionmaker[Session],
    *,
    window: str = "all",
    origin_dates: list[str] | None = None,
    n_paths: int = DEFAULT_N_PATHS,
    base_seed: int = DEFAULT_BASE_SEED,
    use_cache: bool = True,
    calibrate_fn: CalibrateFn | None = None,
    artifact_store: LocalArtifactStore | None = None,
) -> EvaluationReport:
    """Run the harness with external updates explicitly empty."""
    payload = baseline_payload()
    return run_evaluation(
        factory,
        window=window,
        origin_dates=origin_dates,
        n_paths=n_paths,
        base_seed=base_seed,
        use_cache=use_cache,
        calibrate_fn=calibrate_fn,
        artifact_store=artifact_store,
        external_evidence=False,
        model_variant=VARIANT,
        suite_version=SUITE_VERSION,
        driver_method="history_anchored_v1",
        baseline=payload,
        details_extra={
            "label": LABEL,
            "external_updates": [],
            "external_families_excluded": list(EXTERNAL_FAMILIES_EXCLUDED),
        },
    )


__all__ = [
    "EXTERNAL_FAMILIES_EXCLUDED",
    "LABEL",
    "METHOD",
    "VARIANT",
    "baseline_payload",
    "run_financial_only",
]
