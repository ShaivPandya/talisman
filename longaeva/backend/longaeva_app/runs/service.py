"""Submit, execute, and replay Visa simulation runs (LON-23)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.companies import register_default_companies
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.config import get_settings
from longaeva_app.db.models import Job, ParameterSet, Run, Scenario
from longaeva_app.engine.outputs import (
    canonical_outputs_hash,
    load_npz_arrays,
    simulation_to_npz_bytes,
    summary_payload,
)
from longaeva_app.engine.provenance import code_version, lib_versions
from longaeva_app.engine.replay import ReplayComparison, compare_simulation
from longaeva_app.engine.runner import simulate
from longaeva_app.review.service import ReviewError, assert_evidence_reviewed
from longaeva_app.runs.errors import RunError
from longaeva_app.runs.inputs import (
    ResolvedRunInputs,
    parameter_set_from_row,
    resolve_run_inputs,
    starting_state_hash,
    verify_parameter_set,
)
from longaeva_app.storage.local import LocalArtifactStore

PENDING_CODE_VERSION = "pending"


def submit_run(
    session: Session,
    *,
    scenario_id: uuid.UUID,
    cutoff_ts: datetime,
    seed: int,
    n_paths: int,
    n_quarters: int,
    switches: dict[str, bool],
    baseline_run_id: uuid.UUID | None = None,
) -> Run:
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise RunError("Scenario not found", status_code=404)
    resolved = resolve_run_inputs(session, scenario=scenario, cutoff_ts=cutoff_ts, switches=switches)
    try:
        assert_evidence_reviewed(session, resolved.parameter_set)
    except ReviewError as exc:
        raise RunError(exc.message, status_code=exc.status_code) from exc
    for item in resolved.interventions:
        if int(item.start_quarter) > n_quarters:
            raise RunError(
                f"intervention start_quarter {item.start_quarter} is past the horizon of {n_quarters}",
                status_code=422,
            )
    if baseline_run_id is not None and session.get(Run, baseline_run_id) is None:
        raise RunError("Baseline run not found", status_code=422)
    job = Job(type="run", payload={}, status="queued")
    session.add(job)
    session.flush()
    run = Run(
        scenario_id=scenario.id,
        job_id=job.id,
        cutoff_ts=cutoff_ts,
        origin_label=resolved.origin_label,
        source_manifest=resolved.source_manifest,
        source_manifest_hash=resolved.source_manifest_hash,
        parameter_set_hash=resolved.parameter_set_hash,
        starting_state=resolved.starting_state,
        starting_state_hash=resolved.starting_state_hash,
        code_version=PENDING_CODE_VERSION,
        seed=seed,
        n_paths=n_paths,
        n_quarters=n_quarters,
        switches=resolved.switches,
        interventions=resolved.interventions_payload,
        interventions_hash=resolved.interventions_hash,
        baseline_run_id=baseline_run_id,
        lib_versions={},
        status="queued",
    )
    session.add(run)
    session.flush()
    job.payload = {"run_id": str(run.id)}
    session.flush()
    return run


def _mark_run_failed(session: Session, run: Run, message: str) -> None:
    run.status = "failed"
    run.error = message
    run.finished_at = datetime.now(UTC)


def execute_run(
    session_factory: sessionmaker[Session],
    run_id: uuid.UUID,
    *,
    job_id: uuid.UUID,
    artifact_store: LocalArtifactStore,
) -> dict[str, Any]:
    with session_factory() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise RunError(f"Run {run_id} not found", status_code=404)
        if run.job_id != job_id:
            raise RunError("Run job_id does not match the claimed job", status_code=409)
        if run.status != "queued":
            raise RunError(f"Run status is {run.status!r}, expected queued", status_code=409)
        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.error = None
        session.commit()

    try:
        result_payload = _simulate_and_store(session_factory, run_id, artifact_store)
    except Exception as exc:
        with session_factory() as session:
            run = session.get(Run, run_id)
            if run is not None and run.status == "running":
                _mark_run_failed(session, run, f"{type(exc).__name__}: {exc}")
                session.commit()
        raise
    return result_payload


def _simulate_and_store(
    session_factory: sessionmaker[Session],
    run_id: uuid.UUID,
    artifact_store: LocalArtifactStore,
) -> dict[str, Any]:
    register_default_companies()
    with session_factory() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise RunError(f"Run {run_id} not found", status_code=404)
        scenario = session.get(Scenario, run.scenario_id)
        if scenario is None:
            raise RunError("Scenario not found", status_code=422)
        resolved = resolve_run_inputs(
            session,
            scenario=scenario,
            cutoff_ts=run.cutoff_ts if run.cutoff_ts.tzinfo else run.cutoff_ts.replace(tzinfo=UTC),
            switches=dict(run.switches or {}),
        )
        _assert_pinned_inputs(run, resolved)
        model = VisaModel()
        params = {name: float(resolved.parameter_set.values[name]) for name in resolved.parameter_set.values}
        simulation = simulate(
            model,
            resolved.starting_state,
            params,
            origin=resolved.origin,
            seed=run.seed,
            n_paths=run.n_paths,
            n_quarters=run.n_quarters,
            switches=resolved.switches,
            interventions=resolved.interventions_payload,
        )
        outputs_key = f"runs/{run.id}/paths.npz"
        artifact_store.write_once(outputs_key, simulation_to_npz_bytes(simulation))
        digest = canonical_outputs_hash(simulation)
        summary = summary_payload(simulation)
        recorded_code = code_version()
        recorded_libs = lib_versions()
        run.status = "succeeded"
        run.outputs_path = outputs_key
        run.outputs_hash = digest
        run.summary = summary
        run.code_version = recorded_code
        run.lib_versions = recorded_libs
        run.switches = resolved.switches
        run.finished_at = datetime.now(UTC)
        run.error = None
        session.commit()
        return {
            "run_id": str(run.id),
            "outputs_hash": digest,
            "outputs_path": outputs_key,
            "n_summaries": len(summary),
        }


def _assert_pinned_inputs(run: Run, resolved: ResolvedRunInputs) -> None:
    if run.parameter_set_hash != resolved.parameter_set_hash:
        raise RunError("Pinned parameter-set hash does not match the scenario parameter set", status_code=409)
    if run.starting_state_hash != resolved.starting_state_hash:
        raise RunError("Pinned starting-state hash does not match the fixture", status_code=409)
    if run.source_manifest_hash != resolved.source_manifest_hash:
        raise RunError("Pinned source-manifest hash does not match the fixture documents", status_code=409)
    if run.interventions_hash != resolved.interventions_hash:
        raise RunError("Pinned intervention hash does not match the scenario interventions", status_code=409)


def replay_run(
    session: Session,
    run_id: uuid.UUID,
    *,
    artifact_store: LocalArtifactStore,
) -> dict[str, Any]:
    register_default_companies()
    settings = get_settings()
    run = session.get(Run, run_id)
    if run is None:
        raise RunError("Run not found", status_code=404)
    if run.status != "succeeded":
        raise RunError("Replay requires a succeeded run", status_code=409)
    scenario = session.get(Scenario, run.scenario_id)
    if scenario is None:
        raise RunError("Scenario not found", status_code=422)
    cutoff = run.cutoff_ts if run.cutoff_ts.tzinfo else run.cutoff_ts.replace(tzinfo=UTC)

    input_errors: list[str] = []
    resolved: ResolvedRunInputs | None = None
    try:
        resolved = resolve_run_inputs(session, scenario=scenario, cutoff_ts=cutoff, switches=dict(run.switches or {}))
        param_row = session.get(ParameterSet, scenario.parameter_set_id)
        if param_row is None:
            raise RunError("Parameter set not found", status_code=422)
        live_hash = parameter_set_from_row(param_row).computed_content_hash()
        if live_hash != run.parameter_set_hash:
            input_errors.append("parameter_set_hash")
        if starting_state_hash(resolved.starting_state) != run.starting_state_hash:
            input_errors.append("starting_state_hash")
        if resolved.source_manifest_hash != run.source_manifest_hash:
            input_errors.append("source_manifest_hash")
        if resolved.interventions_hash != run.interventions_hash:
            input_errors.append("interventions_hash")
        verify_parameter_set(param_row, run_cutoff=cutoff, company=scenario.company)
    except RunError as exc:
        input_errors.append(exc.message)

    recomputed_code = code_version()
    recomputed_libs = lib_versions()
    if input_errors:
        return _replay_payload(
            run,
            comparison=ReplayComparison(
                status="inputs_changed",
                recorded_hash=run.outputs_hash or "",
                recomputed_hash="",
                max_relative_difference=float("inf"),
                differences=input_errors,
            ),
            recomputed_code=recomputed_code,
            recomputed_libs=recomputed_libs,
            llm_provider=settings.llm_provider,
        )

    assert resolved is not None
    model = VisaModel()
    params = {name: float(resolved.parameter_set.values[name]) for name in resolved.parameter_set.values}
    simulation = simulate(
        model,
        resolved.starting_state,
        params,
        origin=resolved.origin,
        seed=run.seed,
        n_paths=run.n_paths,
        n_quarters=run.n_quarters,
        switches=resolved.switches,
        interventions=resolved.interventions_payload,
    )
    recorded_metrics = None
    recorded_states = None
    if run.outputs_path and artifact_store.exists(run.outputs_path):
        recorded_metrics, recorded_states, _periods = load_npz_arrays(artifact_store.read_bytes(run.outputs_path))
    recorded_summary = run.summary if isinstance(run.summary, list) else None
    comparison = compare_simulation(
        simulation,
        recorded_hash=run.outputs_hash or "",
        recorded_metrics=recorded_metrics,
        recorded_states=recorded_states,
        recorded_summary=recorded_summary,
        recomputed_summary=summary_payload(simulation),
        recorded_code_version=run.code_version,
        recomputed_code_version=recomputed_code,
        recorded_lib_versions=dict(run.lib_versions or {}),
        recomputed_lib_versions=recomputed_libs,
    )
    return _replay_payload(
        run,
        comparison=comparison,
        recomputed_code=recomputed_code,
        recomputed_libs=recomputed_libs,
        llm_provider=settings.llm_provider,
    )


def _replay_payload(
    run: Run,
    *,
    comparison: ReplayComparison,
    recomputed_code: str,
    recomputed_libs: dict[str, Any],
    llm_provider: str,
) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "status": comparison.status,
        "recorded_outputs_hash": comparison.recorded_hash,
        "recomputed_outputs_hash": comparison.recomputed_hash or None,
        "max_relative_difference": None
        if comparison.status == "inputs_changed"
        else comparison.max_relative_difference,
        "recorded_code_version": run.code_version,
        "recomputed_code_version": recomputed_code,
        "recorded_lib_versions": dict(run.lib_versions or {}),
        "recomputed_lib_versions": recomputed_libs,
        "differences": comparison.differences,
        "llm_provider": llm_provider or "",
    }


def fail_orphaned_running_runs(session_factory: sessionmaker[Session]) -> int:
    now = datetime.now(UTC)
    with session_factory() as session:
        result = session.execute(
            update(Run)
            .where(Run.status == "running")
            .values(status="failed", error="worker restarted", finished_at=now)
        )
        session.commit()
        return int(getattr(result, "rowcount", 0) or 0)
