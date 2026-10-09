"""Scenario creation, paired runs, comparison, attribution, and replay."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.db.models import MappingRule, Observation, ParameterSet, ParameterUpdate, Scenario, Source
from longaeva_app.runs.inputs import (
    default_parameter_ranges,
    default_parameter_values,
    parse_aware_utc,
    resolve_fixture_by_origin_date,
)
from longaeva_app.storage.local import LocalArtifactStore
from longaeva_app.worker.queue import claim_next_job, execute_job

ORIGIN = "2024-07-23"
N_PATHS = 8


def _cutoff() -> datetime:
    return parse_aware_utc(resolve_fixture_by_origin_date(ORIGIN).cutoff_utc)


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _drain(engine: Engine, store: LocalArtifactStore) -> None:
    factory = _factory(engine)
    while True:
        claimed = claim_next_job(factory, "scenario-test")
        if claimed is None:
            return
        execute_job(factory, claimed, "scenario-test", artifact_store=store)


def _parameter_set(session: Session, cutoff: datetime, *, observation_id: Any | None = None) -> ParameterSet:
    from longaeva_app.api.schemas import ParameterEvidence, ParameterSetCreate

    values = default_parameter_values()
    links: dict[str, ParameterEvidence] = {}
    flags: dict[str, Any] = {}
    for name in values:
        if observation_id is not None and name == "payments_volume_growth":
            links[name] = ParameterEvidence(observation_ids=[observation_id])
            flags[name] = False
        else:
            links[name] = ParameterEvidence(assumption=True, rationale="fixture assumption")
            flags[name] = True
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


def _accepted_observation(session: Session) -> tuple[Source, Observation]:
    published = datetime(2024, 7, 23, tzinfo=UTC)
    source = Source(
        provider="sec",
        company="visa",
        doc_type="10-Q",
        url="https://www.sec.gov/Archives/edgar/data/1403161/example.htm",
        publication_ts=published,
        retrieval_ts=published + timedelta(hours=1),
        content_hash=uuid4().hex,
        original_path="fixtures/visa/lon22",
        attributes={},
    )
    session.add(source)
    session.flush()
    observation = Observation(
        company="visa",
        source_id=source.id,
        statement_type="measured",
        activity_type="payments_volume",
        geography="global",
        period_start=date(2024, 4, 1),
        period_end=date(2024, 6, 30),
        value=1.0,
        unit="ratio",
        basis="constant_dollar",
        source_family="visa",
        extractor_id="visa_tables",
        extractor_version="lon-14",
        review_status="accepted",
        attributes={},
    )
    session.add(observation)
    session.flush()
    return source, observation


@pytest.mark.db
def test_create_scenario_override_and_invalid_intervention(
    client: TestClient,
    db_session: Session,
) -> None:
    cutoff = _cutoff()
    base = _parameter_set(db_session, cutoff)
    db_session.commit()
    group = str(uuid4())
    created = client.post(
        "/scenarios",
        json={
            "company": "visa",
            "name": "higher-volume",
            "parameter_set_id": str(base.id),
            "pair_group_id": group,
            "parameter_overrides": {
                "payments_volume_growth": {"value": 0.12, "rationale": "illustrative volume increase"}
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["parameter_set_id"] != str(base.id)
    assert body["interventions"] == []
    db_session.expire_all()
    child = db_session.get(ParameterSet, body["parameter_set_id"])
    assert child is not None
    assert child.parent_id == base.id
    assert child.values["payments_volume_growth"] == pytest.approx(0.12)
    update = db_session.scalars(select(ParameterUpdate).where(ParameterUpdate.parameter_set_id == child.id)).one()
    assert update.target_parameter == "payments_volume_growth"
    assert update.rule_id is None
    assert update.size == pytest.approx(0.12 - float(base.values["payments_volume_growth"]))

    rejected = client.post(
        "/scenarios",
        json={
            "company": "visa",
            "name": "bad",
            "parameter_set_id": str(base.id),
            "interventions": [{"type": "not_a_shift"}],
        },
    )
    assert rejected.status_code == 422


@pytest.mark.db
def test_pair_comparison_attribution_replay_and_archive(
    client: TestClient,
    test_engine: Engine,
    db_session: Session,
    artifact_store: LocalArtifactStore,
) -> None:
    cutoff = _cutoff()
    _source, observation = _accepted_observation(db_session)
    param_set = _parameter_set(db_session, cutoff, observation_id=observation.id)
    rule = MappingRule(
        rule_key="volume_growth_from_release",
        version=1,
        input_type="measured",
        target_parameter="payments_volume_growth",
        transform={"op": "identity"},
        rationale="Map the measured volume growth onto the free parameter.",
    )
    db_session.add(rule)
    db_session.flush()
    db_session.add(
        ParameterUpdate(
            rule_id=rule.id,
            parameter_set_id=param_set.id,
            target_parameter="payments_volume_growth",
            before_value={"value": 0.08},
            after_value={"value": float(param_set.values["payments_volume_growth"])},
            size=0.0,
            rationale="Linked for attribution.",
        )
    )
    db_session.commit()
    group = str(uuid4())
    baseline = client.post(
        "/scenarios",
        json={
            "company": "visa",
            "name": "baseline",
            "parameter_set_id": str(param_set.id),
            "pair_group_id": group,
        },
    )
    variant = client.post(
        "/scenarios",
        json={
            "company": "visa",
            "name": "mix",
            "parameter_set_id": str(param_set.id),
            "pair_group_id": group,
            "interventions": [{"type": "mix_shift_conserving_total", "cross_border_change": -0.10}],
        },
    )
    spend = client.post(
        "/scenarios",
        json={
            "company": "visa",
            "name": "spend",
            "parameter_set_id": str(param_set.id),
            "pair_group_id": group,
            "interventions": [{"type": "total_spend_reduction", "reduction": 0.05}],
        },
    )
    assert baseline.status_code == variant.status_code == spend.status_code == 201
    paired = client.post(
        "/scenarios/pair-runs",
        json={
            "scenario_ids": [baseline.json()["id"], variant.json()["id"], spend.json()["id"]],
            "baseline_scenario_id": baseline.json()["id"],
            "cutoff_ts": cutoff.isoformat(),
            "seed": 22,
            "n_paths": N_PATHS,
            "n_quarters": 4,
        },
    )
    assert paired.status_code == 202, paired.text
    runs = paired.json()
    assert len(runs) == 3
    assert runs[0]["seed"] == runs[1]["seed"] == runs[2]["seed"] == 22
    assert runs[1]["baseline_run_id"] == runs[0]["id"]
    assert runs[2]["baseline_run_id"] == runs[0]["id"]
    assert runs[0]["baseline_run_id"] is None
    assert runs[1]["interventions"][0]["type"] == "mix_shift_conserving_total"
    _drain(test_engine, artifact_store)

    comparison = client.get("/scenarios/comparison", params={"run_id": runs[1]["id"]})
    assert comparison.status_code == 200, comparison.text
    pv = [item for item in comparison.json()["items"] if item["metric"] == "payments_volume_nominal_us"]
    assert pv
    assert all(item["difference_mean"] == pytest.approx(0.0, abs=1e-9) for item in pv)

    spend_cmp = client.get(
        "/scenarios/comparison",
        params={"run_id": runs[2]["id"], "baseline_run_id": runs[0]["id"]},
    )
    assert spend_cmp.status_code == 200, spend_cmp.text
    service = [item for item in spend_cmp.json()["items"] if item["metric"] == "service_revenue"]
    service.sort(key=lambda item: item["quarter_index"])
    assert service[0]["difference_mean"] == pytest.approx(0.0, abs=1e-6)
    assert service[1]["difference_mean"] < 0.0

    other_seed = client.post(
        "/runs",
        json={
            "scenario_id": baseline.json()["id"],
            "cutoff_ts": cutoff.isoformat(),
            "seed": 99,
            "n_paths": N_PATHS,
        },
    )
    assert other_seed.status_code == 202, other_seed.text
    _drain(test_engine, artifact_store)
    mismatched = client.get(
        "/scenarios/comparison",
        params={"run_id": other_seed.json()["id"], "baseline_run_id": runs[0]["id"]},
    )
    assert mismatched.status_code == 422
    assert "seed" in mismatched.json()["detail"]

    attribution = client.get("/scenarios/attribution", params={"run_id": runs[1]["id"], "metric": "net_revenue"})
    assert attribution.status_code == 200, attribution.text
    payload = attribution.json()
    assert payload["conditional_on_model"] is True
    assert "caus" not in payload["order_note"]
    assert payload["verification"]
    assert set(payload["verification"]) <= {"exact_match", "numerically_equivalent"}
    assert payload["metrics"][0]["metric"] == "net_revenue"
    growth = next(item for item in payload["sensitivity"] if item["parameter"] == "payments_volume_growth")
    assert str(rule.id) in growth["rule_ids"]
    assert str(_source.id) in growth["source_ids"]
    assert str(observation.id) in growth["observation_ids"]
    labels = " ".join(item["label"] for item in payload["contributions"])
    assert "caus" not in labels
    assert payload["contributions"][0]["kind"] == "intervention"

    replay = client.post(f"/runs/{runs[1]['id']}/replay")
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] in {"exact_match", "numerically_equivalent"}

    db_session.expire_all()
    stored = db_session.get(Scenario, runs[1]["scenario_id"])
    assert stored is not None
    stored.interventions = [{"type": "total_spend_reduction", "reduction": 0.05, "start_quarter": 1}]
    db_session.commit()
    changed = client.post(f"/runs/{runs[1]['id']}/replay")
    assert changed.status_code == 200, changed.text
    assert changed.json()["status"] == "inputs_changed"
    assert "interventions_hash" in changed.json()["differences"]

    archived = client.post(f"/runs/{runs[1]['id']}/forecasts", json={"kind": "retrospective"})
    assert archived.status_code == 422
    assert "ntervention" in archived.json()["detail"]


@pytest.mark.db
def test_pair_requires_a_shared_group(client: TestClient, db_session: Session) -> None:
    cutoff = _cutoff()
    param_set = _parameter_set(db_session, cutoff)
    db_session.commit()
    first = client.post(
        "/scenarios",
        json={"company": "visa", "name": "a", "parameter_set_id": str(param_set.id)},
    )
    second = client.post(
        "/scenarios",
        json={"company": "visa", "name": "b", "parameter_set_id": str(param_set.id)},
    )
    assert first.status_code == second.status_code == 201
    paired = client.post(
        "/scenarios/pair-runs",
        json={
            "scenario_ids": [first.json()["id"], second.json()["id"]],
            "baseline_scenario_id": first.json()["id"],
            "cutoff_ts": cutoff.isoformat(),
            "seed": 1,
            "n_paths": 4,
        },
    )
    assert paired.status_code == 422
    assert "pair_group_id" in paired.json()["detail"]
