"""Matched inputs, cutoff safety, numerical removal and persistence (LON-31)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.companies.visa.calibration import CalibrationResult, artifact_path
from longaeva_app.db.models import EvaluationResult, Observation, ParameterSet, Run
from longaeva_app.evaluation.ablations import (
    ABLATION_VARIANTS,
    compare_reports,
    run_ablation,
    run_ablations,
    sensitivity_profiles,
)
from longaeva_app.evaluation.baselines.financial_only import run_financial_only
from longaeva_app.evaluation.evidence import EvidenceSnapshot, freeze_evidence
from longaeva_app.evaluation.harness import build_config, config_hash, load_calibration_artifact
from longaeva_app.evaluation.origins import load_evaluation_origins
from longaeva_app.extract.census_quarters import quarter_prints
from longaeva_app.review.rules import REGISTRY, aligned_pairs
from longaeva_app.review.service import record_decision
from longaeva_app.runs.service import replay_run
from longaeva_app.storage.local import LocalArtifactStore

ORIGINS = ["2024-07-23", "2025-10-28"]
CUTOFF = datetime(2024, 7, 23, 23, tzinfo=UTC)


def _calibrate(origin_date: str) -> CalibrationResult:
    return load_calibration_artifact(artifact_path(origin_date))


def test_census_quarter_selector_rejects_late_suspect_monthly_and_duplicate_prints() -> None:
    retained = quarter_prints(CUTOFF)
    assert retained
    assert len({row.period_end for row in retained}) == len(retained)
    assert all(row.integrity_flag == "ok" and row.period_end[5:7] in {"03", "06", "09", "12"} for row in retained)
    row = retained[-1]
    older = replace(row, release_id="older", publication_ts="2024-07-01T00:00:00Z", value="1")
    late = replace(row, release_id="late", publication_ts="2024-08-01T00:00:00Z", value="99")
    suspect = replace(
        row, release_id="suspect", publication_ts="2024-07-22T00:00:00Z", integrity_flag="possibly_replaced"
    )
    monthly = replace(row, period_end="2024-05-31", release_id="monthly")
    flagged = replace(row, period_end="2024-03-31", value_flag="S", release_id="flagged")
    nonfinite = replace(row, period_end="2024-03-31", value="nan", release_id="nonfinite")
    assert quarter_prints(CUTOFF, [older, row, late, suspect, monthly, flagged, nonfinite]) == [row]


def test_census_fit_counts_unique_quarters_and_uses_version_two() -> None:
    spec = next(item for item in REGISTRY if item.source_family == "census")
    assert spec.version == 2
    pairs = aligned_pairs(spec, CUTOFF)
    assert len(pairs) >= 12
    assert len(pairs) <= len(quarter_prints(CUTOFF))
    assert len(pairs) < 40


def test_hash_covers_evidence_rules_switches_and_sensitivity() -> None:
    origins = [item for item in load_evaluation_origins(origin_dates=ORIGINS) if item.scored]
    inputs: dict[str, Any] = {"snapshots": {"toy": {"value": 1}}, "rules": {"census:v2": "hash"}, "sensitivity": {}}
    digest = config_hash(build_config(origins, evaluation_inputs=inputs))
    for key, value in (
        ("snapshots", {"toy": {"value": 2}}),
        ("rules", {"census:v2": "new-hash"}),
        ("sensitivity", {"parameter": "payments_volume_growth", "endpoint": "low"}),
    ):
        changed = deepcopy(inputs)
        changed[key] = value
        assert config_hash(build_config(origins, evaluation_inputs=changed)) != digest
    assert config_hash(build_config(origins, evaluation_inputs=inputs, switches={"service_lag": False})) != digest
    assert len(sensitivity_profiles()) == 13


@pytest.mark.db
def test_matched_variants_numerical_removal_replay_and_idempotency(
    db_session: Session, artifact_store: LocalArtifactStore
) -> None:
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    reports = [
        run_ablation(
            name, factory, origin_dates=ORIGINS, n_paths=64, calibrate_fn=_calibrate, artifact_store=artifact_store
        )
        for name in ("full_model", *ABLATION_VARIANTS)
    ]
    assert all(report.n_scored == 2 for report in reports), [
        item.error for report in reports for item in report.origins
    ]
    assert compare_reports(reports)["comparisons"]
    full, removed, pooled, lag = reports
    for original, ablated in zip(full.origins, removed.origins, strict=True):
        assert original.input_details["external_numeric_changes"]
        assert original.input_details["sensitivity_parent_hash"] == ablated.input_details["sensitivity_parent_hash"]
        assert not ablated.input_details["external_updates"]
        assert original.input_details["seed"] == ablated.input_details["seed"]
    assert all(item.input_details["switches"]["pool_mix"] for item in pooled.origins)
    assert all(not item.input_details["switches"]["service_lag"] for item in lag.origins)
    financial = run_financial_only(
        factory, origin_dates=ORIGINS, n_paths=64, calibrate_fn=_calibrate, artifact_store=artifact_store
    )
    assert financial.aggregates == removed.aggregates
    assert [item.run_id for item in financial.origins] == [item.run_id for item in removed.origins]
    with factory() as session:
        n_rows = session.scalar(select(func.count()).select_from(EvaluationResult))
        n_runs = session.scalar(select(func.count()).select_from(Run))
        for item in full.origins:
            assert item.run_id is not None
            run = session.get(Run, item.run_id)
            assert run is not None
            parameter = session.scalar(select(ParameterSet).where(ParameterSet.content_hash == run.parameter_set_hash))
            assert parameter is not None and parameter.parent_id is not None
            assert any(entry["document_key"].startswith("reviewed:") for entry in run.source_manifest)
            assert replay_run(session, run.id, artifact_store=artifact_store)["status"] == "exact_match"
    again = run_ablation(
        "full_model", factory, origin_dates=ORIGINS, n_paths=64, calibrate_fn=_calibrate, artifact_store=artifact_store
    )
    assert again.config_hash == full.config_hash
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationResult)) == n_rows
        assert session.scalar(select(func.count()).select_from(Run)) == n_runs
    with pytest.raises(ValueError, match="incomplete"):
        compare_reports([full, replace(removed, n_scored=1), pooled, lag])
    mismatched = replace(removed, config=replace(removed.config, observations_hash="poison"))
    with pytest.raises(ValueError, match="matched code and data"):
        compare_reports([full, mismatched, pooled, lag])
    changed_state = deepcopy(removed)
    changed_state.origins[0].rows[0]["details"]["starting_state_hash"] = "poison"
    with pytest.raises(ValueError, match="matched starting states"):
        compare_reports([full, changed_state, pooled, lag])


@pytest.mark.db
def test_review_snapshot_preserves_rejection_and_detects_changed_corrections(db_session: Session) -> None:
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    origins = [item for item in load_evaluation_origins(origin_dates=ORIGINS[:1]) if item.scored]
    snapshot = freeze_evidence(factory, origins)
    with factory() as session:
        census_id = next(
            row_id
            for row_id in snapshot.ids_by_origin[ORIGINS[0]]
            if (row := session.get(Observation, row_id)) is not None and row.source_family == "census"
        )
        record_decision(
            session, observation_id=census_id, decision="reject", rationale="test rejection", decided_by="test"
        )
        session.commit()
    with factory() as session, pytest.raises(ValueError, match="changed"):
        snapshot.assert_unchanged(session, ORIGINS[0])
    rejected = freeze_evidence(factory, origins)
    assert census_id not in rejected.reviewed_ids(ORIGINS[0])
    with factory() as session:
        record_decision(
            session,
            observation_id=census_id,
            decision="correct",
            rationale="test correction",
            decided_by="test",
            corrected_payload={"value": 7.0},
        )
        session.commit()
    corrected = freeze_evidence(factory, origins)
    assert census_id in corrected.reviewed_ids(ORIGINS[0])
    assert corrected.policy["snapshot_hash"] != rejected.policy["snapshot_hash"]
    assert all(
        parse["publication_ts"] <= origins[0].cutoff_ts.isoformat().replace("+00:00", "Z")
        for parse in corrected.by_origin[ORIGINS[0]]
    )


@pytest.mark.db
def test_no_evidence_is_a_scored_no_effect_case(db_session: Session, artifact_store: LocalArtifactStore) -> None:
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    snapshot = EvidenceSnapshot({ORIGINS[0]: []}, {ORIGINS[0]: []}, {"snapshots": {ORIGINS[0]: []}})
    full = run_ablation(
        "full_model",
        factory,
        origin_dates=ORIGINS[:1],
        n_paths=64,
        evidence_snapshot=snapshot,
        calibrate_fn=_calibrate,
        artifact_store=artifact_store,
    )
    removed = run_ablation(
        "no_external_commentary",
        factory,
        origin_dates=ORIGINS[:1],
        n_paths=64,
        evidence_snapshot=snapshot,
        calibrate_fn=_calibrate,
        artifact_store=artifact_store,
    )
    assert full.n_scored == removed.n_scored == 1
    assert full.aggregates == removed.aggregates
    assert full.origins[0].input_details["external_no_effect"] is True


@pytest.mark.db
def test_all_predefined_profiles_share_upstream_settings(
    db_session: Session, artifact_store: LocalArtifactStore
) -> None:
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    suite = run_ablations(
        factory, origin_dates=ORIGINS[:1], n_paths=32, calibrate_fn=_calibrate, artifact_store=artifact_store
    )
    assert len(suite.profiles) == 13
    for profile, reports in suite.profiles.items():
        assert all(report.n_scored == 1 for report in reports)
        settings = [report.origins[0].input_details["sensitivity"] for report in reports]
        assert all(setting == settings[0] for setting in settings)
        assert len({report.origins[0].input_details["sensitivity_parent_hash"] for report in reports}) == 1
        assert all(setting["profile"] == profile for setting in settings)
    assert all(value["profiles"] == 13 for value in suite.persistence["robustness"].values())
