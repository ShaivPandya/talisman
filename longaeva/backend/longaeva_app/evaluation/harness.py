"""Evaluation harness: calibrate, run, score, persist (LON-27)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.api.schemas import ParameterSetCreate
from longaeva_app.companies.visa.calibration import (
    MANIFEST_JSON,
    OBSERVATIONS_CSV,
    ORIGINS_CSV,
    CalibrationResult,
    MemberFit,
    calibrate,
    result_to_dict,
    round_sig,
)
from longaeva_app.companies.visa.starting_state import to_starting_state
from longaeva_app.config import get_settings
from longaeva_app.db.models import EvaluationResult, Job, Run
from longaeva_app.engine.outputs import load_npz_arrays
from longaeva_app.engine.provenance import code_version
from longaeva_app.evaluation.evidence import EvidenceSnapshot
from longaeva_app.evaluation.leakage import (
    LeakageError,
    assert_inputs_before_cutoff,
)
from longaeva_app.evaluation.metrics import (
    DEFAULT_QUANTILES,
    aggregate_scores,
    aggregate_to_dict,
    score_samples,
)
from longaeva_app.evaluation.origins import EvaluationOrigin, load_evaluation_origins
from longaeva_app.evaluation.targets import (
    DRIVER_TARGETS,
    LEVEL_TARGETS,
    annualized_to_quarterly,
    build_driver_history,
    forecast_driver_yoy,
    four_quarter_sum,
    has_four_quarter_actuals,
    load_actuals,
    load_four_quarter_actuals,
    q4_level_yoy,
)
from longaeva_app.hashing import content_hash, sha256_hex, utc_isoformat
from longaeva_app.runs.inputs import resolve_fixture
from longaeva_app.runs.service import submit_run
from longaeva_app.storage.local import LocalArtifactStore
from longaeva_app.worker.queue import execute_job

SUITE_VERSION = "lon31-v1"
MODEL_VARIANT = "full_model"
DEFAULT_N_PATHS = 5000
DEFAULT_N_QUARTERS = 4
DEFAULT_BASE_SEED = 27_000
_FLOAT_SIGFIGS = 10
_WORKER_ID = "evaluation"

CalibrateFn = Callable[[str], CalibrationResult]


@dataclass
class EvaluationConfig:
    suite_version: str = SUITE_VERSION
    model_variant: str = MODEL_VARIANT
    n_paths: int = DEFAULT_N_PATHS
    n_quarters: int = DEFAULT_N_QUARTERS
    base_seed: int = DEFAULT_BASE_SEED
    quantiles: tuple[float, ...] = DEFAULT_QUANTILES
    coverage_level: float = 0.8
    include_pandemic: bool = False
    switches: dict[str, bool] = field(default_factory=dict)
    origin_dates: list[str] = field(default_factory=list)
    code_version: str = ""
    observations_hash: str = ""
    manifest_hash: str = ""
    origins_hash: str = ""
    driver_method: str = "history_anchored_v1"
    scoring_bases: dict[str, str] = field(
        default_factory=lambda: {
            "net_revenue": "gaap",
            "operating_profit_ex_special_items": "ex_special_items",
            "payments_volume_growth_constant": "constant_dollar",
            "cross_border_ex_intra_europe_growth_constant": "constant_dollar",
            "processed_transactions_growth": "count",
        }
    )
    evaluation_code_hash: str = ""
    evaluation_inputs: dict[str, Any] = field(default_factory=dict)
    # Baseline method metadata also enters the config hash.
    baseline: dict[str, Any] = field(default_factory=dict)

    def to_hashable(self) -> dict[str, Any]:
        payload = {
            "suite_version": self.suite_version,
            "model_variant": self.model_variant,
            "n_paths": self.n_paths,
            "n_quarters": self.n_quarters,
            "base_seed": self.base_seed,
            "seed_policy": "base_seed + stable hash of origin_date",
            "quantiles": list(self.quantiles),
            "coverage_level": self.coverage_level,
            "include_pandemic": self.include_pandemic,
            "switches": dict(sorted(self.switches.items())),
            "origin_dates": list(self.origin_dates),
            "code_version": self.code_version,
            "observations_hash": self.observations_hash,
            "manifest_hash": self.manifest_hash,
            "origins_hash": self.origins_hash,
            "driver_method": self.driver_method,
            "scoring_bases": dict(sorted(self.scoring_bases.items())),
            "metrics": ["signed_error", "abs_error", "pct_error", "covered_80", "crps", "wis"],
            "crps": "empirical_sample_sorted",
            "wis": "median_plus_50_80_90_intervals_div_k_plus_1",
        }
        if self.evaluation_code_hash:
            payload["evaluation_code_hash"] = self.evaluation_code_hash
        if self.evaluation_inputs:
            payload["evaluation_inputs"] = self.evaluation_inputs
        if self.baseline:
            payload["baseline"] = self.baseline
        return payload


@dataclass
class OriginEvaluation:
    origin: EvaluationOrigin
    run_id: str | None
    rows: list[dict[str, Any]]
    skipped_drivers: dict[str, str]
    error: str | None = None
    input_details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationReport:
    config: EvaluationConfig
    config_hash: str
    origins: list[OriginEvaluation]
    exclusions: list[dict[str, str]]
    aggregates: dict[str, Any]
    four_quarter: dict[str, Any]
    n_scored: int
    n_excluded: int


def file_sha256(path: Path) -> str:
    return sha256_hex(path.read_bytes())


def build_config(
    origins: Sequence[EvaluationOrigin],
    *,
    n_paths: int = DEFAULT_N_PATHS,
    n_quarters: int = DEFAULT_N_QUARTERS,
    base_seed: int = DEFAULT_BASE_SEED,
    switches: Mapping[str, bool] | None = None,
    include_pandemic: bool = False,
    model_variant: str = MODEL_VARIANT,
    suite_version: str = SUITE_VERSION,
    driver_method: str = "history_anchored_v1",
    baseline: Mapping[str, Any] | None = None,
    evaluation_inputs: Mapping[str, Any] | None = None,
) -> EvaluationConfig:
    package = Path(__file__).resolve().parents[1]
    sources = sorted(path for folder in ("evaluation", "review") for path in (package / folder).rglob("*.py"))
    sources.extend([package / "extract" / "census_quarters.py", package / "runs" / "inputs.py"])
    evaluation_digest = content_hash({str(path.relative_to(package)): file_sha256(path) for path in sources})
    return EvaluationConfig(
        evaluation_code_hash=evaluation_digest,
        evaluation_inputs=dict(evaluation_inputs or {}),
        suite_version=suite_version,
        model_variant=model_variant,
        driver_method=driver_method,
        baseline=dict(baseline or {}),
        n_paths=n_paths,
        n_quarters=n_quarters,
        base_seed=base_seed,
        switches=dict(switches or {"service_lag": True, "pool_mix": False}),
        include_pandemic=include_pandemic,
        origin_dates=[o.origin_date for o in origins if o.scored],
        code_version=code_version(),
        observations_hash=file_sha256(OBSERVATIONS_CSV),
        manifest_hash=file_sha256(MANIFEST_JSON),
        origins_hash=file_sha256(ORIGINS_CSV),
    )


def config_hash(config: EvaluationConfig) -> str:
    return content_hash(config.to_hashable())


def origin_seed(base_seed: int, origin_date: str) -> int:
    digest = sha256_hex(f"{base_seed}:{origin_date}")
    return int(digest[:8], 16) % 2_147_483_647


def _round_tree(value: Any) -> Any:
    if isinstance(value, float):
        return round_sig(value, _FLOAT_SIGFIGS)
    if isinstance(value, dict):
        return {k: _round_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_tree(v) for v in value]
    return value


def _cache_key(origin_date: str, config: EvaluationConfig) -> str:
    payload = {
        "origin_date": origin_date,
        "include_pandemic": config.include_pandemic,
        "code_version": config.code_version,
        "observations_hash": config.observations_hash,
        "manifest_hash": config.manifest_hash,
        "origins_hash": config.origins_hash,
    }
    return content_hash(payload)[:24]


def _calibration_cache_path(store: LocalArtifactStore, key: str) -> Path:
    return store.resolve_key(f"evaluation/calibration/{key}.json")


def _write_calibration_cache(store: LocalArtifactStore, key: str, result: CalibrationResult) -> None:
    path = _calibration_cache_path(store, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = result_to_dict(
        origin_date=result.origin_date,
        origin_label=result.origin_label,
        cutoff_ts=result.cutoff_ts,
        members=result.members,
        weights=result.weights,
        pooled=result.pooled,
        evidence_index=result.evidence_index,
        exclusions=result.exclusions,
        pandemic_included=result.pandemic_included,
        sensitivity=result.sensitivity,
    )
    payload["result_hash"] = result.result_hash
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_calibration_artifact(path: Path) -> CalibrationResult:
    """Rehydrate a ``CalibrationResult`` from a committed or cached JSON artifact."""
    from longaeva_app.api.schemas import ParameterEvidence
    from longaeva_app.companies.visa.calibration import Exclusion
    from longaeva_app.runs.inputs import parse_aware_utc

    data = json.loads(path.read_text(encoding="utf-8"))
    members = [
        MemberFit(
            name=m["name"],
            window_start=m["window_start"],
            window_end=m["window_end"],
            values={k: float(v) for k, v in m["values"].items()},
            ranges={k: [float(a), float(b)] for k, (a, b) in m["ranges"].items()},
            evidence_ids={},
            assumption_flags=dict(m.get("assumption_flags") or {}),
            rationales={},
            residuals={},
            n_obs={k: int(v) for k, v in (m.get("n_obs") or {}).items()},
            mse=None,
        )
        for m in data["members"]
    ]
    pooled_raw = data["pooled"]
    evidence_links = {key: ParameterEvidence.model_validate(val) for key, val in pooled_raw["evidence_links"].items()}
    pooled = ParameterSetCreate(
        company=pooled_raw["company"],
        cutoff_ts=parse_aware_utc(pooled_raw["cutoff_ts"]),
        values={k: float(v) for k, v in pooled_raw["values"].items()},
        ranges=pooled_raw["ranges"],
        evidence_links=evidence_links,
        assumption_flags=pooled_raw.get("assumption_flags") or {},
    )
    exclusions = [Exclusion(e["period"], e["field"], e["reason"], e.get("value")) for e in data.get("exclusions", [])]
    return CalibrationResult(
        origin_date=data["origin_date"],
        origin_label=data["origin_label"],
        cutoff_ts=parse_aware_utc(data["cutoff_ts"]),
        members=members,
        weights={k: float(v) for k, v in data["weights"].items()},
        pooled=pooled,
        evidence_index=dict(data.get("evidence_index") or {}),
        exclusions=exclusions,
        pandemic_included=dict(data.get("pandemic_included") or {}),
        sensitivity=list(data.get("sensitivity") or []),
        result_hash=str(data["result_hash"]),
        panel_periods=[],
    )


def _calibrate_cached(
    origin_date: str,
    config: EvaluationConfig,
    store: LocalArtifactStore,
    *,
    use_cache: bool,
    calibrate_fn: CalibrateFn | None,
) -> CalibrationResult:
    if calibrate_fn is not None:
        return calibrate_fn(origin_date)
    key = _cache_key(origin_date, config)
    path = _calibration_cache_path(store, key)
    if use_cache and path.is_file():
        cached = load_calibration_artifact(path)
        payload = result_to_dict(
            origin_date=cached.origin_date,
            origin_label=cached.origin_label,
            cutoff_ts=cached.cutoff_ts,
            members=cached.members,
            weights=cached.weights,
            pooled=cached.pooled,
            evidence_index=cached.evidence_index,
            exclusions=cached.exclusions,
            pandemic_included=cached.pandemic_included,
            sensitivity=cached.sensitivity,
        )
        if content_hash(payload) == cached.result_hash:
            return cached
    result = calibrate(origin_date, include_pandemic=config.include_pandemic, run_sensitivity=False)
    if use_cache:
        _write_calibration_cache(store, key, result)
    return result


def _find_reusable_run(
    session: Session,
    *,
    scenario_id: UUID,
    cutoff_ts: datetime,
    seed: int,
    n_paths: int,
    n_quarters: int,
    switches: Mapping[str, bool],
    parameter_set_hash: str,
    starting_state_hash: str,
    source_manifest_hash: str,
    code_ver: str,
) -> Run | None:
    stmt = (
        select(Run)
        .where(Run.scenario_id == scenario_id)
        .where(Run.cutoff_ts == cutoff_ts)
        .where(Run.seed == seed)
        .where(Run.n_paths == n_paths)
        .where(Run.n_quarters == n_quarters)
        .where(Run.status == "succeeded")
        .where(Run.parameter_set_hash == parameter_set_hash)
        .where(Run.starting_state_hash == starting_state_hash)
        .where(Run.source_manifest_hash == source_manifest_hash)
        .where(Run.code_version == code_ver)
        .order_by(Run.created_at.desc())
    )
    for run in session.scalars(stmt):
        if dict(run.switches or {}) == dict(switches):
            return run
    return None


def _submit_and_execute(
    factory: sessionmaker[Session],
    *,
    scenario_id: UUID,
    cutoff_ts: datetime,
    seed: int,
    n_paths: int,
    n_quarters: int,
    switches: Mapping[str, bool],
    store: LocalArtifactStore,
) -> Run:
    with factory() as session:
        run = submit_run(
            session,
            scenario_id=scenario_id,
            cutoff_ts=cutoff_ts,
            seed=seed,
            n_paths=n_paths,
            n_quarters=n_quarters,
            switches=dict(switches),
        )
        job = session.get(Job, run.job_id)
        if job is None:
            raise RuntimeError("submit_run produced a run without a job")
        now = datetime.now(UTC)
        job.status = "running"
        job.worker_id = _WORKER_ID
        job.started_at = now
        job.attempts = max(int(job.attempts or 0), 1)
        run_id = run.id
        job_id = job.id
        session.commit()
    execute_job(factory, job_id, _WORKER_ID, artifact_store=store)
    with factory() as session:
        row = session.get(Run, run_id)
        if row is None:
            raise RuntimeError(f"run {run_id} missing after execute")
        if row.status != "succeeded":
            raise RuntimeError(f"run {run_id} failed: {row.error}")
        session.expunge(row)
        return row


def score_point(
    *,
    horizon: str,
    target: str,
    samples: np.ndarray,
    actual: float,
    percentage_error: bool,
    details_base: dict[str, Any],
) -> list[dict[str, Any]]:
    scores = score_samples(samples, actual, percentage_error=percentage_error)
    stats = {
        "mean": scores.mean,
        "median": scores.median,
        "signed_error": scores.signed_error,
        "abs_error": scores.abs_error,
        "pct_error": scores.pct_error,
        "covered_80": 1.0 if scores.covered_80 else 0.0,
        "crps": scores.crps,
        "wis": scores.wis,
    }
    rows: list[dict[str, Any]] = []
    forecast = {
        "mean": scores.mean,
        "median": scores.median,
        "quantiles": scores.quantiles,
    }
    for stat, value in stats.items():
        if value is None:
            continue
        rows.append(
            {
                "metric": f"{horizon}.{target}.{stat}",
                "value": float(value),
                "details": {
                    **details_base,
                    "target": target,
                    "horizon": horizon,
                    "statistic": stat,
                    "actual": actual,
                    "forecast": forecast,
                    "percentage_error": percentage_error,
                },
            }
        )
    return rows


def evaluate_origin(
    origin: EvaluationOrigin,
    config: EvaluationConfig,
    config_digest: str,
    factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    use_cache: bool = True,
    calibrate_fn: CalibrateFn | None = None,
    details_extra: Mapping[str, Any] | None = None,
    evidence_snapshot: EvidenceSnapshot | None = None,
    external_evidence: bool = True,
    sensitivity: Mapping[str, str] | None = None,
) -> OriginEvaluation:
    fixture = resolve_fixture(origin.cutoff_ts)
    calib = _calibrate_cached(
        origin.origin_date,
        config,
        store,
        use_cache=use_cache,
        calibrate_fn=calibrate_fn,
    )
    history = build_driver_history(origin, model_cb_growth_q_minus_3=None)
    assert_inputs_before_cutoff(
        origin.cutoff_ts,
        starting_state_sources=fixture.sources,
        calibration_evidence=calib.evidence_index,
        driver_history=history.publication_entries,
    )

    with factory() as session:
        from longaeva_app.evaluation.evidence import prepare_parameters

        if evidence_snapshot is None:
            raise ValueError("evaluation requires a frozen evidence snapshot")
        _param_set, prepared_scenario, input_details = prepare_parameters(
            session,
            calib,
            evidence_snapshot,
            origin.origin_date,
            external_evidence=external_evidence,
            sensitivity=dict(sensitivity or {}),
        )
        session.commit()
        scenario_id = prepared_scenario.id
        parameter_set_hash = _param_set.content_hash

    seed = origin_seed(config.base_seed, origin.origin_date)
    with factory() as session:
        from longaeva_app.db.models import Scenario
        from longaeva_app.runs.inputs import resolve_run_inputs

        scenario = session.get(Scenario, scenario_id)
        if scenario is None:
            raise RuntimeError("calibrated scenario missing")
        resolved = resolve_run_inputs(
            session,
            scenario=scenario,
            cutoff_ts=origin.cutoff_ts,
            switches=dict(config.switches),
        )
        assert_inputs_before_cutoff(
            origin.cutoff_ts,
            source_manifest=resolved.source_manifest,
        )
        reusable = _find_reusable_run(
            session,
            scenario_id=scenario_id,
            cutoff_ts=origin.cutoff_ts,
            seed=seed,
            n_paths=config.n_paths,
            n_quarters=config.n_quarters,
            switches=resolved.switches,
            parameter_set_hash=parameter_set_hash,
            starting_state_hash=resolved.starting_state_hash,
            source_manifest_hash=resolved.source_manifest_hash,
            code_ver=config.code_version,
        )
        if reusable is not None:
            run = reusable
            session.expunge(run)
        else:
            run = None
            resolved_switches = resolved.switches
            starting_state_hash = resolved.starting_state_hash
            source_manifest_hash = resolved.source_manifest_hash

    if run is None:
        run = _submit_and_execute(
            factory,
            scenario_id=scenario_id,
            cutoff_ts=origin.cutoff_ts,
            seed=seed,
            n_paths=config.n_paths,
            n_quarters=config.n_quarters,
            switches=resolved_switches,
            store=store,
        )
        # Re-check hashes for details.
        starting_state_hash = run.starting_state_hash
        source_manifest_hash = run.source_manifest_hash
    else:
        starting_state_hash = run.starting_state_hash
        source_manifest_hash = run.source_manifest_hash

    if not run.outputs_path:
        raise RuntimeError(f"run {run.id} has no outputs_path")
    metrics, states, _periods = load_npz_arrays(store.read_bytes(run.outputs_path))

    actuals = load_actuals(origin)
    details_base = {
        **input_details,
        "seed": seed,
        "switches": dict(resolved.switches),
        "origin_label": origin.label,
        "origin_date": origin.origin_date,
        "origin_window": origin.origin_window,
        "target_quarter": origin.target.label(),
        "run_id": str(run.id),
        "outputs_hash": run.outputs_hash,
        "parameter_set_hash": parameter_set_hash,
        "starting_state_hash": starting_state_hash,
        "source_manifest_hash": source_manifest_hash,
        "calibration_result_hash": calib.result_hash,
        "ensemble_members": [
            {"name": m.name, "window_start": m.window_start, "window_end": m.window_end} for m in calib.members
        ],
        "ensemble_weights": dict(calib.weights),
    }
    if details_extra:
        details_base = {**dict(details_extra), **details_base}

    rows: list[dict[str, Any]] = []
    for name in LEVEL_TARGETS:
        if name not in actuals:
            continue
        samples = metrics[name][:, 0]
        rows.extend(
            score_point(
                horizon="q1",
                target=name,
                samples=samples,
                actual=actuals[name].value,
                percentage_error=True,
                details_base={
                    **details_base,
                    "actual_source_id": actuals[name].source_id,
                    "actual_publication_ts": utc_isoformat(actuals[name].publication_ts),
                },
            )
        )

    driver_forecasts = forecast_driver_yoy(metrics, history, quarter_index=0)
    for name in DRIVER_TARGETS:
        driver_samples = driver_forecasts.get(name)
        if driver_samples is None:
            continue
        if name not in actuals:
            continue
        method_flags = {
            "driver_method": config.driver_method,
            "approximate": name == "cross_border_ex_intra_europe_growth_constant",
        }
        rows.extend(
            score_point(
                horizon="q1",
                target=name,
                samples=np.asarray(driver_samples, dtype=np.float64),
                actual=actuals[name].value,
                percentage_error=False,
                details_base={
                    **details_base,
                    "actual_source_id": actuals[name].source_id,
                    "actual_publication_ts": utc_isoformat(actuals[name].publication_ts),
                    "method_flags": method_flags,
                },
            )
        )

    # Four-quarter scoring when all four target quarters are released.
    if has_four_quarter_actuals(origin):
        totals = load_four_quarter_actuals(origin)
        for name in LEVEL_TARGETS:
            samples = four_quarter_sum(metrics[name])
            rows.extend(
                score_point(
                    horizon="4q",
                    target=f"{name}_sum",
                    samples=samples,
                    actual=totals[name],
                    percentage_error=True,
                    details_base=details_base,
                )
            )
        start_vals = to_starting_state(fixture)
        if "processed_transactions_count" in start_vals:
            txn_yoy = q4_level_yoy(
                metrics["processed_transactions_count"][:, 3], start_vals["processed_transactions_count"]
            )
            if "processed_transactions_growth" in totals:
                rows.extend(
                    score_point(
                        horizon="4q",
                        target="processed_transactions_growth",
                        samples=txn_yoy,
                        actual=totals["processed_transactions_growth"],
                        percentage_error=False,
                        details_base={**details_base, "method_flags": {"exact_from_levels": True}},
                    )
                )
        if "payments_volume_index_constant" in states:
            pv_yoy = q4_level_yoy(states["payments_volume_index_constant"][:, 3], 100.0)
            if "payments_volume_growth_constant" in totals:
                rows.extend(
                    score_point(
                        horizon="4q",
                        target="payments_volume_growth_constant",
                        samples=pv_yoy,
                        actual=totals["payments_volume_growth_constant"],
                        percentage_error=False,
                        details_base={
                            **details_base,
                            "method_flags": {"exact_from_index": True},
                        },
                    )
                )
        # CB: compound four quarterly rates recovered from annualized engine metrics.
        if "cross_border_ex_intra_europe_growth_constant" in metrics and (
            "cross_border_ex_intra_europe_growth_constant" in totals
        ):
            eng = metrics["cross_border_ex_intra_europe_growth_constant"][:, :4]
            g_q = annualized_to_quarterly(eng)
            compound = np.prod(1.0 + g_q, axis=1) - 1.0
            rows.extend(
                score_point(
                    horizon="4q",
                    target="cross_border_ex_intra_europe_growth_constant",
                    samples=compound,
                    actual=totals["cross_border_ex_intra_europe_growth_constant"],
                    percentage_error=False,
                    details_base={
                        **details_base,
                        "method_flags": {"approximate": True, "compounded_quarterly": True},
                    },
                )
            )

    # Persist rows for this origin (caller may batch); attach config hash.
    for row in rows:
        row["suite_version"] = config.suite_version
        row["model_variant"] = config.model_variant
        row["origin_ts"] = origin.cutoff_ts
        row["config_hash"] = config_digest

    return OriginEvaluation(
        origin=origin,
        run_id=str(run.id),
        rows=rows,
        skipped_drivers=dict(history.skip_reasons),
        input_details={**input_details, "seed": seed, "switches": dict(resolved.switches)},
    )


def persist_rows(session: Session, rows: Sequence[dict[str, Any]], config_digest: str, model_variant: str) -> None:
    if not rows:
        return
    session.execute(
        delete(EvaluationResult).where(
            EvaluationResult.config_hash == config_digest,
            EvaluationResult.model_variant == model_variant,
        )
    )
    for row in rows:
        session.add(
            EvaluationResult(
                suite_version=row["suite_version"],
                origin_ts=row["origin_ts"],
                model_variant=row["model_variant"],
                metric=row["metric"],
                value=float(row["value"]),
                config_hash=config_digest,
                details=row["details"],
            )
        )


def collect_aggregates(origin_evals: Sequence[OriginEvaluation]) -> dict[str, Any]:
    def gather(window: str | None, metric_suffix: str, horizon: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in origin_evals:
            if window is not None and item.origin.origin_window != window:
                continue
            # Rebuild a score row from abs_error / signed_error / etc.
            by_stat: dict[str, float] = {}
            for row in item.rows:
                parts = row["metric"].split(".")
                if len(parts) != 3:
                    continue
                h, target, stat = parts
                if h != horizon or target != metric_suffix:
                    continue
                by_stat[stat] = float(row["value"])
            if "abs_error" not in by_stat:
                continue
            out.append(
                {
                    "abs_error": by_stat.get("abs_error"),
                    "signed_error": by_stat.get("signed_error"),
                    "pct_error": by_stat.get("pct_error"),
                    "covered_80": bool(by_stat.get("covered_80", 0.0)),
                    "crps": by_stat.get("crps"),
                    "wis": by_stat.get("wis"),
                }
            )
        return out

    targets = list(LEVEL_TARGETS) + list(DRIVER_TARGETS)
    tables: dict[str, Any] = {}
    for window_key, window in (("overall", None), ("primary", "primary"), ("extension", "extension")):
        tables[window_key] = {}
        for target in targets:
            rows = gather(window, target, "q1")
            tables[window_key][target] = aggregate_to_dict(aggregate_scores(rows))
    return tables


def collect_four_quarter(origin_evals: Sequence[OriginEvaluation]) -> dict[str, Any]:
    targets = [f"{n}_sum" for n in LEVEL_TARGETS] + list(DRIVER_TARGETS)
    out: dict[str, Any] = {}
    for target in targets:
        rows: list[dict[str, Any]] = []
        for item in origin_evals:
            by_stat: dict[str, float] = {}
            for row in item.rows:
                parts = row["metric"].split(".")
                if len(parts) != 3:
                    continue
                h, t, stat = parts
                if h != "4q" or t != target:
                    continue
                by_stat[stat] = float(row["value"])
            if "abs_error" not in by_stat:
                continue
            rows.append(
                {
                    "abs_error": by_stat.get("abs_error"),
                    "signed_error": by_stat.get("signed_error"),
                    "pct_error": by_stat.get("pct_error"),
                    "covered_80": bool(by_stat.get("covered_80", 0.0)),
                    "crps": by_stat.get("crps"),
                    "wis": by_stat.get("wis"),
                }
            )
        out[target] = aggregate_to_dict(aggregate_scores(rows))
    return out


def run_evaluation(
    factory: sessionmaker[Session],
    *,
    window: str = "all",
    origin_dates: list[str] | None = None,
    n_paths: int = DEFAULT_N_PATHS,
    n_quarters: int = DEFAULT_N_QUARTERS,
    base_seed: int = DEFAULT_BASE_SEED,
    switches: Mapping[str, bool] | None = None,
    use_cache: bool = True,
    calibrate_fn: CalibrateFn | None = None,
    artifact_store: LocalArtifactStore | None = None,
    model_variant: str = MODEL_VARIANT,
    suite_version: str = SUITE_VERSION,
    driver_method: str = "history_anchored_v1",
    baseline: Mapping[str, Any] | None = None,
    details_extra: Mapping[str, Any] | None = None,
    external_evidence: bool = True,
    evidence_snapshot: EvidenceSnapshot | None = None,
    sensitivity: Mapping[str, str] | None = None,
) -> EvaluationReport:
    origins = load_evaluation_origins(window=window, origin_dates=origin_dates)
    scored = [o for o in origins if o.scored]
    excluded = [o for o in origins if o.status == "candidate" and o.exclusion_reason]
    from longaeva_app.evaluation.evidence import freeze_evidence

    snapshot = evidence_snapshot or freeze_evidence(factory, scored)
    evaluation_inputs = {
        **snapshot.policy,
        "external_evidence": external_evidence,
        "sensitivity": dict(sensitivity or {}),
    }
    config = build_config(
        scored,
        n_paths=n_paths,
        n_quarters=n_quarters,
        base_seed=base_seed,
        switches=switches,
        model_variant=model_variant,
        suite_version=suite_version,
        driver_method=driver_method,
        baseline=baseline,
        evaluation_inputs=evaluation_inputs,
    )
    digest = config_hash(config)
    store = artifact_store or LocalArtifactStore(get_settings().artifact_dir)

    origin_evals: list[OriginEvaluation] = []
    all_rows: list[dict[str, Any]] = []
    for origin in scored:
        try:
            result = evaluate_origin(
                origin,
                config,
                digest,
                factory,
                store,
                use_cache=use_cache,
                calibrate_fn=calibrate_fn,
                details_extra=details_extra,
                evidence_snapshot=snapshot,
                external_evidence=external_evidence,
                sensitivity=sensitivity,
            )
        except (LeakageError, Exception) as exc:  # noqa: BLE001 — record per-origin failures
            origin_evals.append(
                OriginEvaluation(
                    origin=origin,
                    run_id=None,
                    rows=[],
                    skipped_drivers={},
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        origin_evals.append(result)
        all_rows.extend(result.rows)

    with factory() as session:
        persist_rows(session, all_rows, digest, config.model_variant)
        session.commit()

    return EvaluationReport(
        config=config,
        config_hash=digest,
        origins=origin_evals,
        exclusions=[
            {"origin_date": o.origin_date, "label": o.label, "reason": o.exclusion_reason or ""} for o in excluded
        ],
        aggregates=collect_aggregates(origin_evals),
        four_quarter=collect_four_quarter(origin_evals),
        n_scored=sum(1 for o in origin_evals if o.error is None and o.rows),
        n_excluded=len(excluded),
    )


def report_to_dict(report: EvaluationReport) -> dict[str, Any]:
    per_origin = []
    for item in report.origins:
        per_origin.append(
            {
                "origin_date": item.origin.origin_date,
                "label": item.origin.label,
                "window": item.origin.origin_window,
                "run_id": item.run_id,
                "error": item.error,
                "skipped_drivers": item.skipped_drivers,
                "n_rows": len(item.rows),
                "inputs": item.input_details,
                "scores": {
                    row["metric"]: round_sig(float(row["value"]), _FLOAT_SIGFIGS)
                    for row in item.rows
                    if row["metric"].endswith((".abs_error", ".pct_error", ".crps", ".wis", ".covered_80", ".median"))
                },
            }
        )
    payload = {
        "config": report.config.to_hashable(),
        "config_hash": report.config_hash,
        "n_scored": report.n_scored,
        "n_excluded": report.n_excluded,
        "exclusions": report.exclusions,
        "aggregates": _round_tree(report.aggregates),
        "four_quarter": _round_tree(report.four_quarter),
        "origins": per_origin,
    }
    return payload


def write_report(report: EvaluationReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report_to_dict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def format_tables(report: EvaluationReport) -> str:
    lines: list[str] = []
    lines.append(f"config_hash={report.config_hash}")
    lines.append(f"scored={report.n_scored} excluded={report.n_excluded}")
    if report.exclusions:
        lines.append("exclusions:")
        for exclusion in report.exclusions:
            lines.append(f"  {exclusion['label']} ({exclusion['origin_date']}): {exclusion['reason']}")
    lines.append("")
    lines.append("Per-origin (q1 net_revenue abs_error / covered_80 / crps):")
    for origin_eval in report.origins:
        if origin_eval.error:
            lines.append(f"  {origin_eval.origin.label}: ERROR {origin_eval.error}")
            continue
        scores = {row["metric"]: row["value"] for row in origin_eval.rows}
        ae = scores.get("q1.net_revenue.abs_error")
        cov = scores.get("q1.net_revenue.covered_80")
        crps = scores.get("q1.net_revenue.crps")
        skip = ",".join(origin_eval.skipped_drivers) if origin_eval.skipped_drivers else "-"
        lines.append(
            f"  {origin_eval.origin.label} [{origin_eval.origin.origin_window}] "
            f"abs_err={ae if ae is None else f'{ae:.1f}'} "
            f"covered={int(cov) if cov is not None else '-'} "
            f"crps={crps if crps is None else f'{crps:.1f}'} "
            f"skip_drivers={skip}"
        )
    lines.append("")
    lines.append("Aggregates (q1):")
    for window, table in report.aggregates.items():
        lines.append(f"  [{window}]")
        for target, stats in table.items():
            n = stats.get("n", 0)
            if not n:
                continue
            lines.append(
                f"    {target}: n={n} mae={stats.get('mae')} "
                f"coverage={stats.get('coverage')} mean_crps={stats.get('mean_crps')}"
            )
    lines.append("")
    lines.append("Four-quarter:")
    for target, stats in report.four_quarter.items():
        n = stats.get("n", 0)
        if not n:
            continue
        lines.append(f"  {target}: n={n} mae={stats.get('mae')} coverage={stats.get('coverage')}")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_BASE_SEED",
    "DEFAULT_N_PATHS",
    "DEFAULT_N_QUARTERS",
    "EvaluationConfig",
    "EvaluationReport",
    "MODEL_VARIANT",
    "SUITE_VERSION",
    "build_config",
    "collect_aggregates",
    "collect_four_quarter",
    "config_hash",
    "evaluate_origin",
    "format_tables",
    "load_calibration_artifact",
    "origin_seed",
    "persist_rows",
    "report_to_dict",
    "run_evaluation",
    "score_point",
    "write_report",
]
