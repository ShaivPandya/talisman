"""Matched ablations and predefined parameter-range persistence (LON-31 / ER-08)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.evaluation.evidence import EvidenceSnapshot, freeze_evidence
from longaeva_app.evaluation.harness import (
    DEFAULT_BASE_SEED,
    DEFAULT_N_PATHS,
    CalibrateFn,
    EvaluationReport,
    report_to_dict,
    run_evaluation,
)
from longaeva_app.evaluation.origins import load_evaluation_origins
from longaeva_app.hashing import content_hash
from longaeva_app.storage.local import LocalArtifactStore

ABLATION_VARIANTS = ("no_external_commentary", "pooled_spending", "no_service_lag")
SENSITIVITY_PARAMETERS = (
    "payments_volume_growth",
    "cross_border_growth_premium",
    "service_yield_drift",
    "data_processing_yield_drift",
    "international_yield_drift",
    "incentive_intensity_drift",
)
SWITCHES = {
    "full_model": {"service_lag": True, "pool_mix": False},
    "no_external_commentary": {"service_lag": True, "pool_mix": False},
    "pooled_spending": {"service_lag": True, "pool_mix": True},
    "no_service_lag": {"service_lag": False, "pool_mix": False},
}


def sensitivity_profiles() -> dict[str, dict[str, str]]:
    return {
        "central": {},
        **{
            f"{name}_{endpoint}": {"parameter": name, "endpoint": endpoint}
            for name in SENSITIVITY_PARAMETERS
            for endpoint in ("low", "high")
        },
    }


def run_ablation(
    name: str,
    factory: sessionmaker[Session],
    *,
    window: str = "all",
    origin_dates: list[str] | None = None,
    n_paths: int = DEFAULT_N_PATHS,
    base_seed: int = DEFAULT_BASE_SEED,
    use_cache: bool = True,
    calibrate_fn: CalibrateFn | None = None,
    artifact_store: LocalArtifactStore | None = None,
    evidence_snapshot: EvidenceSnapshot | None = None,
    sensitivity: Mapping[str, str] | None = None,
) -> EvaluationReport:
    if name not in SWITCHES:
        raise ValueError(f"unknown ablation variant {name!r}")
    if sensitivity and (
        sensitivity.get("parameter") not in SENSITIVITY_PARAMETERS or sensitivity.get("endpoint") not in {"low", "high"}
    ):
        raise ValueError("sensitivity must name a predefined parameter and a low/high endpoint")
    return run_evaluation(
        factory,
        window=window,
        origin_dates=origin_dates,
        n_paths=n_paths,
        base_seed=base_seed,
        use_cache=use_cache,
        calibrate_fn=calibrate_fn,
        artifact_store=artifact_store,
        model_variant=name,
        switches=SWITCHES[name],
        external_evidence=name != "no_external_commentary",
        evidence_snapshot=evidence_snapshot,
        sensitivity=sensitivity,
    )


def compare_reports(reports: Sequence[EvaluationReport]) -> dict[str, Any]:
    """Positive delta means the full model has lower error. Missing pairs are failures."""
    indexed = {report.config.model_variant: report for report in reports}
    if set(indexed) != {"full_model", *ABLATION_VARIANTS} or len(reports) != 4:
        raise ValueError("comparison requires exactly the full model and three ablations")
    full = indexed["full_model"]
    dates = full.config.origin_dates
    for report in reports:
        if report.config.origin_dates != dates or report.n_scored != len(dates):
            failures = [(item.origin.origin_date, item.error) for item in report.origins if item.error]
            raise ValueError(f"incomplete origin set for {report.config.model_variant}: {failures}")
        if any(item.error or not item.rows for item in report.origins):
            raise ValueError(f"failed origin in {report.config.model_variant}")
        if (report.config.n_paths, report.config.n_quarters, report.config.base_seed) != (
            full.config.n_paths,
            full.config.n_quarters,
            full.config.base_seed,
        ):
            raise ValueError("comparison must use matched paths, horizons and seeds")
        for attribute in ("observations_hash", "manifest_hash", "origins_hash", "code_version", "evaluation_code_hash"):
            if getattr(report.config, attribute) != getattr(full.config, attribute):
                raise ValueError("comparison must use matched code and data inputs")
    comparisons: list[dict[str, Any]] = []
    summary: dict[str, dict[str, Any]] = {}
    for name in ABLATION_VARIANTS:
        ablated = {item.origin.origin_date: item for item in indexed[name].origins}
        for original in full.origins:
            other = ablated[original.origin.origin_date]
            for attribute in ("seed", "sensitivity_parent_hash"):
                if original.input_details.get(attribute) != other.input_details.get(attribute):
                    raise ValueError("comparison must use matched upstream parameter settings and seeds")
            if original.rows[0]["details"]["starting_state_hash"] != other.rows[0]["details"]["starting_state_hash"]:
                raise ValueError("comparison must use matched starting states")
            base_scores = {row["metric"]: float(row["value"]) for row in original.rows}
            other_scores = {row["metric"]: float(row["value"]) for row in other.rows}
            if set(base_scores) != set(other_scores):
                raise ValueError(f"unmatched scoring targets: {name} at {original.origin.origin_date}")
            for metric, value in base_scores.items():
                horizon, target, statistic = metric.split(".")
                if statistic not in {"abs_error", "crps", "wis"}:
                    continue
                delta = other_scores[metric] - value
                tie = math.isclose(other_scores[metric], value, rel_tol=1e-10, abs_tol=1e-9)
                winner = "tie" if tie else "full_model" if delta > 0 else name
                coverage_key = f"{horizon}.{target}.covered_80"
                row = {
                    "variant": name,
                    "origin_date": original.origin.origin_date,
                    "window": original.origin.origin_window,
                    "horizon": horizon,
                    "target": target,
                    "statistic": statistic,
                    "full": value,
                    "ablated": other_scores[metric],
                    "ablated_minus_full": delta,
                    "winner": winner,
                    "full_covered_80": base_scores.get(coverage_key),
                    "ablated_covered_80": other_scores.get(coverage_key),
                }
                comparisons.append(row)
                for window in ("overall", original.origin.origin_window):
                    key = f"{name}.{window}.{metric}"
                    totals = summary.setdefault(
                        key,
                        {
                            "n": 0,
                            "full_wins": 0,
                            "ablated_wins": 0,
                            "ties": 0,
                            "delta_sum": 0.0,
                            "full_covered": 0,
                            "ablated_covered": 0,
                        },
                    )
                    totals["n"] += 1
                    totals["ties" if tie else "full_wins" if delta > 0 else "ablated_wins"] += 1
                    totals["delta_sum"] += delta
                    totals["full_covered"] += int(base_scores.get(coverage_key, 0))
                    totals["ablated_covered"] += int(other_scores.get(coverage_key, 0))
    for totals in summary.values():
        totals["mean_ablated_minus_full"] = totals.pop("delta_sum") / totals["n"]
        totals["full_coverage"] = totals["full_covered"] / totals["n"]
        totals["ablated_coverage"] = totals["ablated_covered"] / totals["n"]
    return {"comparisons": comparisons, "summary": summary}


@dataclass
class AblationSuite:
    profiles: dict[str, list[EvaluationReport]]
    persistence: dict[str, Any]


def run_ablations(
    factory: sessionmaker[Session],
    *,
    window: str = "all",
    origin_dates: list[str] | None = None,
    n_paths: int = DEFAULT_N_PATHS,
    base_seed: int = DEFAULT_BASE_SEED,
    use_cache: bool = True,
    calibrate_fn: CalibrateFn | None = None,
    artifact_store: LocalArtifactStore | None = None,
    progress: Callable[[str], None] | None = None,
) -> AblationSuite:
    origins = [item for item in load_evaluation_origins(window=window, origin_dates=origin_dates) if item.scored]
    snapshot = freeze_evidence(factory, origins)
    settings = sensitivity_profiles()
    profiles: dict[str, list[EvaluationReport]] = {}
    comparisons: dict[str, Any] = {}
    for profile, sensitivity in settings.items():
        if progress:
            progress(f"Ablations: {profile} ({len(origins)} origins, four matched variants)")
        reports = [
            run_ablation(
                name,
                factory,
                window=window,
                origin_dates=origin_dates,
                n_paths=n_paths,
                base_seed=base_seed,
                use_cache=use_cache,
                calibrate_fn=calibrate_fn,
                artifact_store=artifact_store,
                evidence_snapshot=snapshot,
                sensitivity=sensitivity,
            )
            for name in SWITCHES
        ]
        profiles[profile] = reports
        comparisons[profile] = compare_reports(reports)
    # Count the direction of each profile's aggregate advantage; never select a best profile.
    robustness: dict[str, dict[str, int]] = {}
    for comparison in comparisons.values():
        for key, stats in comparison["summary"].items():
            counts = robustness.setdefault(key, {"profiles": 0, "full_better": 0, "ablated_better": 0, "ties": 0})
            delta = stats["mean_ablated_minus_full"]
            counts["profiles"] += 1
            counts["ties" if abs(delta) <= 1e-9 else "full_better" if delta > 0 else "ablated_better"] += 1
    persistence = {
        "suite_version": "lon31-v1",
        "profile_policy": "central plus one-at-a-time calibrated low/high before external updates; no retuning",
        "delta_convention": "ablated minus full; positive means lower error for full model",
        "settings": settings,
        "evidence": snapshot.policy,
        "profiles": {
            profile: {"reports": [report_to_dict(report) for report in reports], **comparisons[profile]}
            for profile, reports in profiles.items()
        },
        "robustness": robustness,
    }
    persistence["content_hash"] = content_hash(persistence)
    return AblationSuite(profiles, persistence)


def write_persistence(suite: AblationSuite, directory: Path) -> None:
    import json

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "visa_ablation_persistence.json").write_text(
        json.dumps(suite.persistence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# Ablation persistence (LON-31)",
        "",
        "Positive error difference means the full model has lower error. No parameter setting was selected using outcomes.",
        "",
        "| Profile | Variant | Horizon/target/statistic | n | Full wins | Ablated wins | Ties | Mean difference | Full coverage | Ablated coverage |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for profile, item in suite.persistence["profiles"].items():
        for key, stats in sorted(item["summary"].items()):
            variant, window, metric = key.split(".", 2)
            if window != "overall":
                continue
            lines.append(
                f"| {profile} | {variant} | {metric} | {stats['n']} | {stats['full_wins']} | "
                f"{stats['ablated_wins']} | {stats['ties']} | {stats['mean_ablated_minus_full']:.6g} | "
                f"{stats['full_coverage']:.3f} | {stats['ablated_coverage']:.3f} |"
            )
    (directory / "ablation_persistence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
