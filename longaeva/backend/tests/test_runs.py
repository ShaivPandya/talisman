"""API → worker → result, replay, and forecast-archive integration tests."""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.api.schemas import ParameterEvidence, ParameterSetCreate
from longaeva_app.db.models import Job, ParameterSet, Run, Scenario
from longaeva_app.runs.inputs import (
    default_parameter_ranges,
    default_parameter_values,
    ensure_default_baseline,
    parse_aware_utc,
    resolve_fixture_by_origin_date,
)
from longaeva_app.storage.local import LocalArtifactStore
from longaeva_app.worker.queue import claim_next_job, execute_job, fail_orphaned_running_jobs

N_PATHS = 32
ORIGIN = "2024-07-23"


def _cutoff() -> datetime:
    return parse_aware_utc(resolve_fixture_by_origin_date(ORIGIN).cutoff_utc)


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _evidence_parameter_set(session: Session, cutoff: datetime, *, all_assumption: bool = False) -> ParameterSet:
    values = default_parameter_values()
    obs_id = uuid4()
    links: dict[str, ParameterEvidence] = {}
    flags: dict[str, Any] = {}
    first = True
    for name in values:
        if all_assumption or not first:
            links[name] = ParameterEvidence(assumption=True, rationale="fixture assumption")
            flags[name] = True
        else:
            links[name] = ParameterEvidence(observation_ids=[obs_id])
            flags[name] = False
            first = False
    create = ParameterSetCreate(
        company="visa",
        cutoff_ts=cutoff,
        values=values,
        ranges=default_parameter_ranges(),
        evidence_links=links,
        assumption_flags=flags,
    )
    row = ParameterSet(
        company="visa",
        cutoff_ts=cutoff,
        values=create.values,
        ranges=create.ranges,
        evidence_links={key: link.model_dump(mode="json") for key, link in create.evidence_links.items()},
        assumption_flags=create.assumption_flags,
        content_hash=create.computed_content_hash(),
    )
    session.add(row)
    session.flush()
    return row


def _scenario(
    session: Session, param_set: ParameterSet, *, interventions: list[dict[str, Any]] | None = None
) -> Scenario:
    row = Scenario(
        company="visa",
        name="test-baseline",
        parameter_set_id=param_set.id,
        interventions=interventions or [],
    )
    session.add(row)
    session.flush()
    return row


def _submit_and_execute(
    client: TestClient,
    test_engine: Engine,
    artifact_store: LocalArtifactStore,
    *,
    scenario_id: str,
    cutoff: datetime | None = None,
    n_paths: int = N_PATHS,
    switches: dict[str, bool] | None = None,
) -> dict[str, Any]:
    body = {
        "scenario_id": scenario_id,
        "cutoff_ts": (cutoff or _cutoff()).isoformat(),
        "seed": 7,
        "n_paths": n_paths,
        "n_quarters": 4,
        "switches": switches or {},
    }
    created = client.post("/runs", json=body)
    assert created.status_code == 202, created.text
    payload = created.json()
    factory = _factory(test_engine)
    claimed = claim_next_job(factory, "test-worker")
    assert claimed is not None
    assert str(claimed) == payload["job_id"]
    execute_job(factory, claimed, "test-worker", artifact_store=artifact_store)
    fetched = client.get(f"/runs/{payload['id']}")
    assert fetched.status_code == 200
    result: dict[str, Any] = fetched.json()
    return result


@pytest.mark.db
def test_api_worker_result_and_replay(
    client: TestClient,
    test_engine: Engine,
    db_session: Session,
    artifact_store: LocalArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "")
    cutoff = _cutoff()
    param_set = _evidence_parameter_set(db_session, cutoff)
    scenario = _scenario(db_session, param_set)
    db_session.commit()

    row = _submit_and_execute(client, test_engine, artifact_store, scenario_id=str(scenario.id))
    assert row["status"] == "succeeded"
    assert row["outputs_hash"]
    assert row["origin_label"] == "FY2024Q3"
    assert artifact_store.exists(row["outputs_path"])

    results = client.get(f"/runs/{row['id']}/results")
    assert results.status_code == 200
    summaries = results.json()
    assert len(summaries) == 17 * 4
    assert summaries[0]["period_label"]

    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise OSError("network forbidden")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    replay = client.post(f"/runs/{row['id']}/replay")
    assert replay.status_code == 200, replay.text
    report = replay.json()
    assert report["status"] == "exact_match"
    assert report["llm_provider"] == ""
    assert report["recorded_outputs_hash"] == row["outputs_hash"]

    from longaeva_app.cli import main

    assert main(["replay", row["id"]]) == 0


@pytest.mark.db
def test_replay_inputs_changed_and_numerically_equivalent(
    client: TestClient,
    test_engine: Engine,
    db_session: Session,
    artifact_store: LocalArtifactStore,
) -> None:
    cutoff = _cutoff()
    param_set = _evidence_parameter_set(db_session, cutoff)
    scenario = _scenario(db_session, param_set)
    db_session.commit()
    row = _submit_and_execute(client, test_engine, artifact_store, scenario_id=str(scenario.id))
    assert row["status"] == "succeeded"

    db_session.expire_all()
    stored = db_session.get(Run, row["id"])
    assert stored is not None
    stored.outputs_hash = "0" * 64
    db_session.commit()
    replay = client.post(f"/runs/{row['id']}/replay")
    assert replay.status_code == 200
    assert replay.json()["status"] == "numerically_equivalent"
    assert "outputs_hash" in replay.json()["differences"]

    ps = db_session.get(ParameterSet, param_set.id)
    assert ps is not None
    values = dict(ps.values)
    values["payments_volume_growth"] = float(values["payments_volume_growth"]) + 0.01
    ps.values = values
    db_session.commit()
    changed = client.post(f"/runs/{row['id']}/replay")
    assert changed.status_code == 200
    assert changed.json()["status"] == "inputs_changed"


@pytest.mark.db
def test_submit_rejects_interventions_incomplete_future_and_unknown_cutoff(
    client: TestClient,
    db_session: Session,
) -> None:
    cutoff = _cutoff()
    param_set = _evidence_parameter_set(db_session, cutoff)
    intervened = _scenario(db_session, param_set, interventions=[{"type": "mix_shift_conserving_total"}])
    db_session.commit()
    blocked = client.post(
        "/runs",
        json={
            "scenario_id": str(intervened.id),
            "cutoff_ts": cutoff.isoformat(),
            "seed": 1,
            "n_paths": N_PATHS,
        },
    )
    assert blocked.status_code == 422
    assert "invalid intervention" in blocked.json()["detail"]

    incomplete = ParameterSet(
        company="visa",
        cutoff_ts=cutoff,
        values={"payments_volume_growth": 0.08},
        ranges={},
        evidence_links={
            "payments_volume_growth": ParameterEvidence(assumption=True, rationale="x").model_dump(mode="json"),
        },
        assumption_flags={"payments_volume_growth": True},
        content_hash=f"incomplete-{uuid4().hex}",
    )
    db_session.add(incomplete)
    db_session.flush()
    incomplete_hash = ParameterSetCreate(
        company="visa",
        cutoff_ts=cutoff,
        values={"payments_volume_growth": 0.08},
        evidence_links={"payments_volume_growth": ParameterEvidence(assumption=True, rationale="x")},
    ).computed_content_hash()
    incomplete.content_hash = incomplete_hash
    scenario_incomplete = _scenario(db_session, incomplete)
    db_session.commit()
    bad = client.post(
        "/runs",
        json={
            "scenario_id": str(scenario_incomplete.id),
            "cutoff_ts": cutoff.isoformat(),
            "seed": 1,
            "n_paths": N_PATHS,
        },
    )
    assert bad.status_code == 422

    future = _evidence_parameter_set(db_session, cutoff + timedelta(days=1))
    future_scenario = _scenario(db_session, future)
    db_session.commit()
    later = client.post(
        "/runs",
        json={
            "scenario_id": str(future_scenario.id),
            "cutoff_ts": cutoff.isoformat(),
            "seed": 1,
            "n_paths": N_PATHS,
        },
    )
    assert later.status_code == 422
    assert "later" in later.json()["detail"]

    unknown = client.post(
        "/runs",
        json={
            "scenario_id": str(future_scenario.id),
            "cutoff_ts": datetime(2020, 1, 1, tzinfo=UTC).isoformat(),
            "seed": 1,
            "n_paths": N_PATHS,
        },
    )
    assert unknown.status_code == 422


@pytest.mark.db
def test_handler_error_and_orphan_recovery(
    client: TestClient,
    test_engine: Engine,
    db_session: Session,
    artifact_store: LocalArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cutoff = _cutoff()
    param_set = _evidence_parameter_set(db_session, cutoff)
    scenario = _scenario(db_session, param_set)
    db_session.commit()
    created = client.post(
        "/runs",
        json={
            "scenario_id": str(scenario.id),
            "cutoff_ts": cutoff.isoformat(),
            "seed": 1,
            "n_paths": N_PATHS,
        },
    )
    assert created.status_code == 202
    run_id = created.json()["id"]
    job_id = created.json()["job_id"]

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated failure")

    monkeypatch.setattr("longaeva_app.runs.service.simulate", _boom)
    factory = _factory(test_engine)
    claimed = claim_next_job(factory, "boom-worker")
    assert claimed is not None
    assert str(claimed) == job_id
    execute_job(factory, claimed, "boom-worker", artifact_store=artifact_store)
    failed_run = client.get(f"/runs/{run_id}")
    assert failed_run.json()["status"] == "failed"
    job = db_session.get(Job, job_id)
    db_session.expire_all()
    job = db_session.get(Job, job_id)
    assert job is not None
    assert job.status == "failed"

    orphan = Run(
        scenario_id=scenario.id,
        cutoff_ts=cutoff,
        source_manifest=[],
        source_manifest_hash="x",
        parameter_set_hash=param_set.content_hash,
        starting_state_hash="y",
        origin_label="FY2024Q3",
        code_version="pending",
        seed=0,
        n_paths=8,
        status="running",
        started_at=datetime.now(UTC),
    )
    db_session.add(orphan)
    db_session.commit()
    orphan_id = orphan.id
    fail_orphaned_running_jobs(factory, "new-worker")
    db_session.expire_all()
    row = db_session.get(Run, orphan_id)
    assert row is not None
    assert row.status == "failed"
    assert row.error == "worker restarted"


@pytest.mark.db
def test_forecast_archive_rules_and_immutability(
    client: TestClient,
    test_engine: Engine,
    db_session: Session,
    artifact_store: LocalArtifactStore,
) -> None:
    cutoff = _cutoff()
    defaults = ensure_default_baseline(db_session, cutoff_ts=cutoff)
    db_session.commit()
    default_run = _submit_and_execute(
        client,
        test_engine,
        artifact_store,
        scenario_id=str(defaults.id),
    )
    assert default_run["status"] == "succeeded"
    denied = client.post(f"/runs/{default_run['id']}/forecasts", json={"kind": "retrospective"})
    assert denied.status_code == 422
    assert "All-assumption" in denied.json()["detail"]

    param_set = _evidence_parameter_set(db_session, cutoff)
    scenario = _scenario(db_session, param_set)
    db_session.commit()
    row = _submit_and_execute(client, test_engine, artifact_store, scenario_id=str(scenario.id))
    wrong = client.post(f"/runs/{row['id']}/forecasts", json={"kind": "prospective"})
    assert wrong.status_code == 422

    archived = client.post(f"/runs/{row['id']}/forecasts", json={"kind": "retrospective"})
    assert archived.status_code == 201, archived.text
    body = archived.json()
    assert len(body) == 20
    assert {item["kind"] for item in body} == {"retrospective"}

    repeat = client.post(f"/runs/{row['id']}/forecasts", json={"kind": "retrospective"})
    assert repeat.status_code == 409

    forecast_id = body[0]["id"]
    assert client.put(f"/forecasts/{forecast_id}", json={"metric": "x"}).status_code == 405
    assert client.delete(f"/forecasts/{forecast_id}").status_code == 405
    with pytest.raises(Exception, match="immutable"):
        db_session.execute(text("UPDATE forecast SET metric = 'other' WHERE id = :id"), {"id": forecast_id})
        db_session.commit()
    db_session.rollback()


@pytest.mark.db
def test_jobs_reject_internal_run_type(client: TestClient) -> None:
    response = client.post("/jobs", json={"type": "run", "payload": {}})
    assert response.status_code == 400


@pytest.mark.db
def test_results_conflict_until_succeeded(client: TestClient, db_session: Session) -> None:
    cutoff = _cutoff()
    param_set = _evidence_parameter_set(db_session, cutoff)
    scenario = _scenario(db_session, param_set)
    db_session.commit()
    created = client.post(
        "/runs",
        json={
            "scenario_id": str(scenario.id),
            "cutoff_ts": cutoff.isoformat(),
            "seed": 1,
            "n_paths": N_PATHS,
        },
    )
    assert created.status_code == 202
    results = client.get(f"/runs/{created.json()['id']}/results")
    assert results.status_code == 409
