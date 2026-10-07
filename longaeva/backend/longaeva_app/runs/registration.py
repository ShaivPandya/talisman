"""Register the July 28 prospective baseline once in Postgres and on disk."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.companies.visa.calibration import calibrate
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.config import get_settings
from longaeva_app.db.models import Forecast, Job, Run, Scenario
from longaeva_app.evaluation.evidence import freeze_evidence, prepare_parameters
from longaeva_app.evaluation.harness import origin_seed
from longaeva_app.evaluation.leakage import assert_inputs_before_cutoff
from longaeva_app.evaluation.origins import load_evaluation_origins
from longaeva_app.evaluation.targets import build_driver_history
from longaeva_app.hashing import content_hash, utc_isoformat
from longaeva_app.runs.forecasts import ARCHIVE_METRICS, archive_forecasts, expected_forecast_kind
from longaeva_app.runs.inputs import parameter_set_from_row, resolve_fixture
from longaeva_app.runs.prospective import (
    CUTOFF,
    ORIGIN_DATE,
    REGISTRATION_FILE,
    REGISTRATION_NAME,
    TARGET,
    PublicationCheck,
    RegistrationBundle,
    load_registration,
    write_json_once,
)
from longaeva_app.runs.service import replay_run, submit_run
from longaeva_app.storage.local import LocalArtifactStore
from longaeva_app.worker.queue import execute_job

CHECKPOINT_PATH = "reports/prospective-fy2026q4-inputs.json"


def register_prospective(
    factory: sessionmaker[Session],
    store: LocalArtifactStore,
    destination: Path,
    publication: PublicationCheck | None,
    *,
    n_paths: int = 5000,
) -> RegistrationBundle:
    """Serialize competing registrations; resume the same run after an interrupted export."""
    if get_settings().llm_provider:
        raise ValueError("Run registration with LLM_PROVIDER disabled")
    # Session lock stays on this connection while execution uses separate sessions.
    with factory() as lock:
        lock.execute(text("SELECT pg_advisory_lock(:key)"), {"key": 32_20260728})
        try:
            return _register(factory, store, destination, publication, n_paths=n_paths)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": 32_20260728})


def _register(
    factory: sessionmaker[Session],
    store: LocalArtifactStore,
    destination: Path,
    publication: PublicationCheck | None,
    *,
    n_paths: int,
) -> RegistrationBundle:
    path = destination / REGISTRATION_FILE
    if path.exists():
        bundle = load_registration(path)
        with factory() as session:
            run = session.get(Run, bundle.run["id"])
            rows = list(session.scalars(select(Forecast).where(Forecast.run_id == bundle.run["id"])))
            if run is None or run.outputs_hash != bundle.run["outputs_hash"]:
                raise ValueError("Packaged registration has no matching database run; use offline replay instead")
            if {str(row.id) for row in rows} != {row["id"] for row in bundle.forecasts}:
                raise ValueError("Database archive differs from the frozen registration")
            _require_exact(replay_run(session, run.id, artifact_store=store))
        return bundle

    with factory() as session:
        run = session.scalar(select(Run).join(Scenario).where(Scenario.name == REGISTRATION_NAME))
        run_id = run.id if run is not None else None
    if run_id is None:
        if publication is None:
            raise ValueError("A fresh --publication-check capture is required for a new registration")
        publication.assert_unpublished(datetime.now(UTC))
        if expected_forecast_kind(fiscal_year=2026, fiscal_quarter=3) != "prospective":
            raise ValueError("Q4 FY2026 results are already published in the origin inventory")
        origins = load_evaluation_origins(origin_dates=[ORIGIN_DATE], include_prospective=True)
        if len(origins) != 1 or origins[0].cutoff_ts != CUTOFF:
            raise ValueError("July 28 prospective origin is missing or has changed")
        calibration = calibrate(ORIGIN_DATE, include_pandemic=False, run_sensitivity=False)
        fixture = resolve_fixture(CUTOFF)
        history = build_driver_history(origins[0], model_cb_growth_q_minus_3=None)
        assert_inputs_before_cutoff(
            CUTOFF,
            starting_state_sources=fixture.sources,
            calibration_evidence=calibration.evidence_index,
            driver_history=history.publication_entries,
        )
        snapshot = freeze_evidence(factory, origins)
        with factory() as session:
            parameters, _scenario, details = prepare_parameters(
                session,
                calibration,
                snapshot,
                ORIGIN_DATE,
                external_evidence=True,
                sensitivity={},
            )
            checkpoint = {
                "publication_check": publication.model_dump(mode="json"),
                "parameters": parameter_set_from_row(parameters).model_dump(mode="json"),
                "evidence": {
                    "calibration_result_hash": calibration.result_hash,
                    "calibration_evidence": calibration.evidence_index,
                    "reviewed_snapshot": snapshot.by_origin[ORIGIN_DATE],
                    "policy": snapshot.policy,
                    "mapping": details,
                    "driver_history": {
                        "labels": history.labels,
                        "publication_entries": history.publication_entries,
                        "txn_year_ago": history.txn_year_ago,
                        "pv_growth_q": history.pv_growth_q,
                        "pv_growth_q_minus_3_nominal": history.pv_growth_q_minus_3_nominal,
                        "pv_fx_gap_q_minus_3": history.pv_fx_gap_q_minus_3,
                        "cb_growth_q": history.cb_growth_q,
                        "cb_growth_q_minus_3_model": history.cb_growth_q_minus_3_model,
                        "skip_reasons": history.skip_reasons,
                    },
                },
            }
            checkpoint_path = store.resolve_key(CHECKPOINT_PATH)
            write_json_once(checkpoint_path, checkpoint)
            scenario = Scenario(
                company="visa", name=REGISTRATION_NAME, parameter_set_id=parameters.id, interventions=[]
            )
            session.add(scenario)
            session.flush()
            run = submit_run(
                session,
                scenario_id=scenario.id,
                cutoff_ts=CUTOFF,
                seed=origin_seed(27_000, ORIGIN_DATE),
                n_paths=n_paths,
                n_quarters=4,
                switches={"service_lag": True, "pool_mix": False},
            )
            # Claim this job specifically before exposing it to a polling worker.
            job = session.get(Job, run.job_id)
            assert job is not None
            job.status, job.worker_id, job.started_at, job.attempts = "running", "prospective", datetime.now(UTC), 1
            session.commit()
            run_id = run.id
    checkpoint = json.loads(store.read_bytes(CHECKPOINT_PATH))
    with factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        if run.status == "queued":
            assert run.job_id is not None
            execute_job(factory, run.job_id, "prospective", artifact_store=store)
            session.expire_all()
        if run.status != "succeeded":
            raise ValueError(f"Registration run is {run.status}: {run.error}; cannot create a replacement")
        replay = replay_run(session, run.id, artifact_store=store)
        _require_exact(replay)
        forecasts = list(session.scalars(select(Forecast).where(Forecast.run_id == run.id)))
        if not forecasts:
            check = PublicationCheck.model_validate(checkpoint["publication_check"])
            check.assert_unpublished(datetime.now(UTC))
            forecasts = archive_forecasts(session, run.id, kind="prospective")
            session.commit()
        if not isinstance(run.summary, list) or run.finished_at is None:
            raise ValueError("Succeeded registration is missing its summary or completion time")
        by_period = {item["quarter_index"]: item["period_label"] for item in run.summary}
        period_labels = dict(
            zip(sorted({row.target_period_start for row in forecasts}), [by_period[i] for i in range(4)], strict=True)
        )
        run_payload = {
            key: getattr(run, key)
            for key in (
                "id",
                "seed",
                "n_paths",
                "n_quarters",
                "switches",
                "interventions",
                "source_manifest",
                "source_manifest_hash",
                "parameter_set_hash",
                "starting_state",
                "starting_state_hash",
                "code_version",
                "lib_versions",
                "outputs_hash",
                "summary",
            )
        }
        run_payload.update(created_at=utc_isoformat(run.created_at), finished_at=utc_isoformat(run.finished_at))
        assert run.outputs_path is not None
        data = store.read_bytes(run.outputs_path)
        paths_file = "prospective_fy2026q4.paths.npz"
        destination.mkdir(parents=True, exist_ok=True)
        outputs_path = destination / paths_file
        if outputs_path.exists():
            if outputs_path.read_bytes() != data:
                raise ValueError("Refusing to replace frozen simulation paths")
        else:
            with outputs_path.open("xb") as handle:
                handle.write(data)
        specs = {spec.name: spec for spec in VisaModel.metrics}
        from longaeva_app.hashing import sha256_hex

        payload = {
            "version": "lon32-v1",
            "kind": "prospective",
            "target": TARGET,
            "registered_at": utc_isoformat(min(row.created_at for row in forecasts)),
            "cutoff_ts": utc_isoformat(CUTOFF),
            **checkpoint,
            "run": run_payload,
            "forecasts": [
                {
                    "id": str(row.id),
                    "run_id": str(row.run_id),
                    "kind": row.kind,
                    "metric": row.metric,
                    "period_label": period_labels[row.target_period_start],
                    "target_period_start": row.target_period_start.isoformat(),
                    "target_period_end": row.target_period_end.isoformat(),
                    "quantiles": row.quantiles,
                    "created_at": utc_isoformat(row.created_at),
                }
                for row in sorted(forecasts, key=lambda row: (row.target_period_start, row.metric))
            ],
            "metric_definitions": {
                name: {
                    "unit": specs[name].unit,
                    "basis": specs[name].basis or "",
                    "growth_convention": "annualized_qoq" if specs[name].unit == "ratio" else "quarterly_level",
                }
                for name in ARCHIVE_METRICS
            },
            "paths_file": paths_file,
            "paths_sha256": sha256_hex(data),
            "replay": replay,
        }
        # Normalize UUIDs/datetimes before hashing and validation.
        payload = json.loads(json.dumps(payload, default=str))
        payload["content_hash"] = content_hash(payload)
        bundle = RegistrationBundle.model_validate(payload)
        write_json_once(path, bundle.model_dump(mode="json"))
    return load_registration(path)


def _require_exact(report: dict[str, Any]) -> None:
    if report["status"] != "exact_match" or report["llm_provider"]:
        raise ValueError("Registration requires exact replay with LLM_PROVIDER disabled")
