"""Database tests for the evaluation harness."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.companies.visa.calibration import CalibrationResult, artifact_path
from longaeva_app.db.models import EvaluationResult, Job, Run
from longaeva_app.evaluation.harness import (
    build_config,
    config_hash,
    load_calibration_artifact,
    run_evaluation,
)
from longaeva_app.evaluation.origins import load_evaluation_origins
from longaeva_app.runs.service import replay_run
from longaeva_app.storage.local import LocalArtifactStore

N_PATHS = 256
ORIGINS = ["2024-07-23", "2025-10-28"]


def _calibrate_fn(origin_date: str) -> CalibrationResult:
    path = artifact_path(origin_date)
    assert path.is_file(), path
    return load_calibration_artifact(path)


@pytest.mark.db
def test_harness_two_fixture_origins(
    db_session: Session,
    artifact_store: LocalArtifactStore,
) -> None:
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    report = run_evaluation(
        factory,
        origin_dates=ORIGINS,
        n_paths=N_PATHS,
        use_cache=False,
        calibrate_fn=_calibrate_fn,
        artifact_store=artifact_store,
    )
    assert report.n_scored == 2
    assert report.n_excluded == 0
    assert all(item.error is None for item in report.origins)
    assert len({item.run_id for item in report.origins}) == 2

    # All rows share one config hash.
    with factory() as session:
        rows = list(session.scalars(select(EvaluationResult)))
    assert rows
    assert {r.config_hash for r in rows} == {report.config_hash}
    assert all(r.model_variant == "full_model" for r in rows)

    # details hold run_id, members, weights.
    sample = rows[0].details
    assert "run_id" in sample
    assert "ensemble_members" in sample
    assert "ensemble_weights" in sample
    assert sample["ensemble_weights"]

    # Aggregates show n.
    nr = report.aggregates["overall"]["net_revenue"]
    assert nr["n"] == 2
    assert "coverage" in nr

    # Jobs were never left queued (claimed before commit).
    with factory() as session:
        jobs = list(session.scalars(select(Job)))
    assert jobs
    assert all(job.status != "queued" for job in jobs)
    assert all(job.worker_id == "evaluation" or job.status == "succeeded" for job in jobs)

    # Replay exact_match.
    with factory() as session:
        runs = list(session.scalars(select(Run).where(Run.status == "succeeded")))
        assert runs
        for run in runs:
            result = replay_run(session, run.id, artifact_store=artifact_store)
            assert result["status"] == "exact_match"

    # Idempotent rerun.
    report2 = run_evaluation(
        factory,
        origin_dates=ORIGINS,
        n_paths=N_PATHS,
        use_cache=False,
        calibrate_fn=_calibrate_fn,
        artifact_store=artifact_store,
    )
    assert report2.config_hash == report.config_hash
    with factory() as session:
        rows2 = list(session.scalars(select(EvaluationResult)))
    assert len(rows2) == len(rows)

    # Config hash changes with n_paths.
    other = build_config(
        [o for o in load_evaluation_origins(origin_dates=ORIGINS) if o.scored],
        n_paths=N_PATHS + 1,
    )
    assert config_hash(other) != report.config_hash


@pytest.mark.db
def test_committed_results_file_when_present() -> None:
    path = Path(__file__).resolve().parents[2] / "data" / "evaluation" / "visa_full_model.json"
    if not path.is_file():
        pytest.skip("committed evaluation results not written yet")
    import json

    from longaeva_app.evaluation.harness import EvaluationConfig, config_hash

    data = json.loads(path.read_text(encoding="utf-8"))
    rebuilt = EvaluationConfig(
        evaluation_code_hash=data["config"].get("evaluation_code_hash", ""),
        evaluation_inputs=data["config"].get("evaluation_inputs", {}),
        suite_version=data["config"]["suite_version"],
        model_variant=data["config"]["model_variant"],
        n_paths=data["config"]["n_paths"],
        n_quarters=data["config"]["n_quarters"],
        base_seed=data["config"]["base_seed"],
        quantiles=tuple(data["config"]["quantiles"]),
        coverage_level=data["config"]["coverage_level"],
        include_pandemic=data["config"]["include_pandemic"],
        switches=data["config"]["switches"],
        origin_dates=data["config"]["origin_dates"],
        code_version=data["config"]["code_version"],
        observations_hash=data["config"]["observations_hash"],
        manifest_hash=data["config"]["manifest_hash"],
        origins_hash=data["config"]["origins_hash"],
        driver_method=data["config"]["driver_method"],
        scoring_bases=data["config"]["scoring_bases"],
    )
    assert config_hash(rebuilt) == data["config_hash"]
    assert data["n_scored"] == 16
    assert data["n_excluded"] == 2
