"""Baselines scored on the LON-27 harness origin set (LON-29)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.evaluation.baselines.financial_only import run_financial_only
from longaeva_app.evaluation.baselines.guidance import run_guidance
from longaeva_app.evaluation.baselines.llm_docs import run_llm_docs
from longaeva_app.evaluation.baselines.seasonal import run_seasonal_trend
from longaeva_app.evaluation.harness import CalibrateFn, EvaluationReport
from longaeva_app.storage.local import LocalArtifactStore

BASELINE_VARIANTS: tuple[str, ...] = ("seasonal_trend", "financial_only", "guidance", "llm_baseline")
COMPARISON_TARGETS: tuple[str, ...] = ("net_revenue", "operating_profit_ex_special_items")


def run_baseline(
    name: str,
    factory: sessionmaker[Session],
    *,
    window: str = "all",
    origin_dates: list[str] | None = None,
    n_paths: int = 5000,
    base_seed: int = 27_000,
    use_cache: bool = True,
    calibrate_fn: CalibrateFn | None = None,
    artifact_store: LocalArtifactStore | None = None,
) -> EvaluationReport:
    """Dispatch one baseline by name. ``name`` is a member of ``BASELINE_VARIANTS``."""
    if name not in BASELINE_VARIANTS:
        joined = ", ".join(BASELINE_VARIANTS)
        raise ValueError(f"unknown baseline {name!r}; expected one of {joined}")
    runners = {
        "seasonal_trend": run_seasonal_trend,
        "financial_only": run_financial_only,
        "guidance": run_guidance,
        "llm_baseline": run_llm_docs,
    }
    return runners[name](
        factory,
        window=window,
        origin_dates=origin_dates,
        n_paths=n_paths,
        base_seed=base_seed,
        use_cache=use_cache,
        calibrate_fn=calibrate_fn,
        artifact_store=artifact_store,
    )


def format_comparison(reports: list[EvaluationReport]) -> str:
    """MAE, coverage and mean CRPS for each variant against ``full_model`` when present."""
    full = next((report for report in reports if report.config.model_variant == "full_model"), None)
    lines = [
        "Comparison (q1 overall, mae / coverage / mean CRPS):",
        f"{'variant':<16} {'target':<36} {'n':>4} {'mae':>12} {'coverage':>12} {'mean_crps':>12} {'mae_vs_full':>12}",
    ]
    for report in reports:
        variant = report.config.model_variant
        overall: dict[str, Any] = report.aggregates.get("overall", {})
        for target in COMPARISON_TARGETS:
            stats: dict[str, Any] = overall.get(target, {})
            mae = stats.get("mae")
            base_mae = None
            if full is not None:
                base_stats: dict[str, Any] = full.aggregates.get("overall", {}).get(target, {})
                base_mae = base_stats.get("mae")
            delta = ""
            if isinstance(mae, (int, float)) and isinstance(base_mae, (int, float)):
                delta = f"{mae - base_mae:.4g}"
            mae_text = "" if mae is None else f"{mae:.4g}"
            crps = stats.get("mean_crps")
            crps_text = "" if crps is None else f"{crps:.4g}"
            lines.append(
                f"{variant:<16} {target:<36} {stats.get('n', 0):>4} {mae_text:>12} "
                f"{str(stats.get('coverage', '')):>12} {crps_text:>12} {delta:>12}"
            )
    return "\n".join(lines)


__all__ = [
    "BASELINE_VARIANTS",
    "COMPARISON_TARGETS",
    "format_comparison",
    "run_baseline",
]
