"""Offline bundle integrity and PostgreSQL seed/replay acceptance."""

from __future__ import annotations

import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.db import models as m
from longaeva_app.demo import MANIFEST_PATH, TABLES, DemoError, load_bundle, seed_demo
from longaeva_app.engine.outputs import load_npz_arrays
from longaeva_app.hashing import content_hash, sha256_hex
from longaeva_app.review.service import record_decision
from longaeva_app.runs.prospective import load_registration
from longaeva_app.runs.service import replay_run
from longaeva_app.storage.local import LocalArtifactStore


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def _assert_replay(report: dict[str, Any]) -> None:
    assert report["status"] in {"exact_match", "numerically_equivalent"}
    assert report["llm_provider"] == ""
    assert report["max_relative_difference"] <= 1e-9
    if report["status"] == "exact_match":
        assert report["recorded_outputs_hash"] == report["recomputed_outputs_hash"]
    else:
        assert "outputs_hash" in report["differences"]


def _manifest(tmp_path: Path, mutation: Any) -> Path:
    bundle = copy.deepcopy(load_bundle())
    mutation(bundle)
    bundle["content_hash"] = content_hash({k: v for k, v in bundle.items() if k != "content_hash"})
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(bundle))
    return path


def test_bundle_integrity_pairs_and_archive() -> None:
    bundle = load_bundle()
    runs = {r["id"]: r for r in bundle["tables"]["run"]}
    assert len(runs) == 7
    assert bundle["origins"] == ["2024-07-23", "2025-10-28"]
    files = {entry.get("artifact_key"): entry for entry in bundle["files"]}
    for run in runs.values():
        if not run["baseline_run_id"]:
            continue
        base = runs[run["baseline_run_id"]]
        assert (run["seed"], run["n_paths"], run["n_quarters"]) == (22, 5000, 4)
        assert base["seed"] == run["seed"] and base["cutoff_ts"] == run["cutoff_ts"]
        if run["interventions"][0]["type"] == "mix_shift_conserving_total":
            root = MANIFEST_PATH.parents[2]
            left, _, _ = load_npz_arrays((root / files[run["outputs_path"]]["path"]).read_bytes())
            right, _, _ = load_npz_arrays((root / files[base["outputs_path"]]["path"]).read_bytes())
            np.testing.assert_array_equal(left["payments_volume_nominal_us"], right["payments_volume_nominal_us"])
    registration = load_registration(MANIFEST_PATH.parent / "forecasts/prospective_fy2026q4.json")
    forecasts = bundle["tables"]["forecast"]
    assert len(forecasts) == 60
    assert {r["kind"] for r in forecasts if r["run_id"] == registration.run["id"]} == {"prospective"}
    assert {r["kind"] for r in forecasts if r["run_id"] != registration.run["id"]} == {"retrospective"}


def test_curator_uses_bundled_original_without_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from longaeva_app import demo_build

    original = MANIFEST_PATH.parent / "originals/adv2603.pdf"
    destination = tmp_path / "data/demo/originals/adv2603.pdf"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(original.read_bytes())
    monkeypatch.setattr(demo_build, "PACKAGE_ROOT", tmp_path)
    assert demo_build._original_index()[sha256_hex(original.read_bytes())] == destination


@pytest.mark.parametrize(
    "case",
    [
        "checksum",
        "reference",
        "artifact_path",
        "parameter",
        "late_input",
        "run_source",
        "evidence_span",
        "parameter_evidence",
    ],
)
def test_invalid_bundle_refused_before_writes(tmp_path: Path, case: str) -> None:
    def mutate(bundle: dict[str, Any]) -> None:
        if case == "checksum":
            bundle["files"][0]["sha256"] = "0" * 64
        elif case == "reference":
            bundle["tables"]["scenario"][0]["parameter_set_id"] = str(uuid.uuid4())
        elif case == "artifact_path":
            bundle["files"][0]["path"] = "../escape"
        elif case == "parameter":
            bundle["tables"]["parameter_set"][0]["values"]["payments_volume_growth"] += 1
        elif case == "run_source":
            bundle["tables"]["run"][0]["source_manifest"][0]["source_id"] = str(uuid.uuid4())
        elif case == "evidence_span":
            bundle["tables"]["observation"][0]["span_char_end"] = 99999999
        elif case == "parameter_evidence":
            next(iter(bundle["tables"]["parameter_set"][0]["evidence_links"].values()))["observation_ids"] = [
                str(uuid.uuid4())
            ]
        else:
            run = bundle["tables"]["run"][0]
            run["source_manifest"][0]["publication_ts"] = "2027-01-01T00:00:00Z"
            from longaeva_app.runs.inputs import manifest_hash

            run["source_manifest_hash"] = manifest_hash(run["source_manifest"])

    path = _manifest(tmp_path, mutate)
    with pytest.raises((DemoError, ValueError)):
        load_bundle(path)


def test_seed_repeat_review_preservation_and_replay(
    db_session: Session,
    artifact_store: LocalArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert db_session.bind is not None
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    first = seed_demo(factory, artifact_store)
    assert first["counts"]["run"]["imported"] == 7
    with factory.begin() as session:
        observation = session.scalar(select(m.Observation))
        assert observation is not None
        observation_id = observation.id
        record_decision(
            session,
            observation_id=observation_id,
            decision="reject",
            rationale="Local review after seed",
            decided_by="test-reviewer",
        )
        session.add(
            m.Scenario(
                company="visa",
                name="User scenario",
                parameter_set_id=session.scalar(select(m.ParameterSet.id)),
                interventions=[],
            )
        )
        # Original quarter-parser records predate stored PDF evidence spans.
        census = session.scalar(select(m.Observation).where(m.Observation.company == "census"))
        assert census is not None
        census_id = census.id
        census.document_text_id = census.span_page = census.span_char_start = census.span_char_end = None
    second = seed_demo(factory, artifact_store)
    assert all(count["imported"] == 0 for count in second["counts"].values())
    with factory() as session:
        assert session.get(m.Observation, observation_id).review_status == "rejected"  # type: ignore[union-attr]
        assert session.scalar(select(func.count()).select_from(m.ReviewDecision)) == 38
        assert session.scalar(select(func.count()).select_from(m.Scenario)) == 12
        assert session.get(m.Observation, census_id).document_text_id is not None  # type: ignore[union-attr]
        monkeypatch.setenv("LLM_PROVIDER", "")
        for run in session.scalars(select(m.Run)):
            _assert_replay(replay_run(session, run.id, artifact_store=artifact_store))


def test_concurrent_seed_once(db_session: Session, artifact_store: LocalArtifactStore) -> None:
    assert db_session.bind is not None
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda _: seed_demo(factory, artifact_store), range(2)))
    assert sorted(r["counts"]["run"]["imported"] for r in reports) == [0, 7]
    expected = load_bundle()["tables"]
    with factory() as session:
        for table, cls in TABLES.items():
            assert session.scalar(select(func.count()).select_from(cls)) == len(expected[table])


def test_seed_reuses_an_existing_workspace_and_gate_reviews(
    db_session: Session,
    artifact_store: LocalArtifactStore,
) -> None:
    from longaeva_app.review.gate_fixtures import load_gate_fixtures
    from longaeva_app.workspace import prepare_origin

    assert db_session.bind is not None
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    with factory() as session:
        existing_root = prepare_origin(session, "2024-07-23").id
        gates = load_gate_fixtures(session, accept=True, families={"booking"})
        observation = next(iter(gates.values()))
        observation_id = observation.id
        record_decision(
            session,
            observation_id=observation_id,
            decision="reject",
            rationale="Existing user decision",
            decided_by="test-reviewer",
        )
        session.commit()
    seed_demo(factory, artifact_store)
    again = seed_demo(factory, artifact_store)
    assert all(count["imported"] == 0 for count in again["counts"].values())
    with factory() as session:
        assert session.get(m.ParameterSet, existing_root) is not None
        kept = session.get(m.Observation, observation_id)
        assert kept is not None and kept.review_status == "rejected"
        for run in session.scalars(select(m.Run)):
            _assert_replay(replay_run(session, run.id, artifact_store=artifact_store))


def test_interrupted_artifact_copy_rolls_back_and_resumes(
    db_session: Session,
    artifact_store: LocalArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert db_session.bind is not None
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    original = artifact_store.write_bytes
    calls = 0

    def interrupted(key: str, data: bytes, *, overwrite: bool = False) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("Simulated interrupted import")
        return original(key, data, overwrite=overwrite)

    monkeypatch.setattr(artifact_store, "write_bytes", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        seed_demo(factory, artifact_store)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.Source)) == 0
    monkeypatch.setattr(artifact_store, "write_bytes", original)
    assert seed_demo(factory, artifact_store)["counts"]["run"]["imported"] == 7


def test_conflicting_artifact_and_immutable_row_refused(
    db_session: Session,
    artifact_store: LocalArtifactStore,
) -> None:
    assert db_session.bind is not None
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    seed_demo(factory, artifact_store)
    with factory.begin() as session:
        run = session.scalar(select(m.Run))
        assert run is not None and run.outputs_path
        key = run.outputs_path
        run.seed += 1
    with pytest.raises(DemoError, match="immutable"):
        seed_demo(factory, artifact_store)
    artifact_store.write_bytes(key, b"corrupt", overwrite=True)
    with pytest.raises(DemoError, match="artifact"):
        seed_demo(factory, artifact_store)


def test_seeded_browser_api_flows(client: TestClient, test_engine: Engine, artifact_store: LocalArtifactStore) -> None:
    seed_demo(_factory(test_engine), artifact_store)
    bundle = load_bundle()
    for origin in bundle["origins"]:
        state = client.get(f"/workspace/origins/{origin}").json()
        assert all(not value["unavailable_reason"] for value in state["evidence"].values())
    for link in bundle["links"][:-1]:
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(link["path"]).query)
        response = client.get("/scenarios/comparison", params={k: v[0] for k, v in query.items() if k != "origin"})
        assert response.status_code == 200, response.text
    for run in bundle["tables"]["run"]:
        response = client.post(f"/runs/{run['id']}/replay")
        assert response.status_code == 200, response.text
        _assert_replay(response.json())
    assert client.get("/evaluation/reports/full_model").json()["forecast"]["n_scored"] == 16
    assert client.get("/evaluation/reports/failure_case").json()["status"] == "available"
    observations = client.get("/observations", params={"company": "booking"}).json()
    for observation in observations:
        response = client.get(
            f"/observations/{observation['id']}/evidence", params={"cutoff_ts": "2026-07-28T20:05:26Z"}
        )
        assert response.status_code == 200
        assert not response.json()["unavailable_reason"]
