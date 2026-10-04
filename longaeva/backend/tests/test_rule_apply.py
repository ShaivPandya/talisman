"""Observation-to-parameter review using the Booking, Census and second-wave fixtures."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.db.models import (
    MappingRule,
    Observation,
    ParameterSet,
    ParameterSetContext,
    ParameterUpdate,
    Source,
)
from longaeva_app.review.gate_fixtures import load_gate_fixtures
from longaeva_app.review.service import record_decision
from longaeva_app.runs.inputs import (
    ensure_default_baseline,
    parameter_set_from_row,
    parse_aware_utc,
    resolve_fixture_by_origin_date,
)
from longaeva_app.storage.local import LocalArtifactStore
from longaeva_app.worker.queue import claim_next_job, execute_job

ORIGIN_A = "2024-07-23"
ORIGIN_B = "2025-10-28"
POST_CUTOFF_HASH = "7b7d16620b9f65842ed4269c8618eea54d275fd8d9fc9337fcfb9bb9e42959a7"
_BODY = {"decided_by": "lon-21-test", "rationale": "Reviewed gate observations."}


def _cutoff(origin: str) -> Any:
    return parse_aware_utc(resolve_fixture_by_origin_date(origin).cutoff_utc)


def _baseline(session: Session, origin: str) -> ParameterSet:
    scenario = ensure_default_baseline(session, cutoff_ts=_cutoff(origin))
    session.flush()
    row = session.get(ParameterSet, scenario.parameter_set_id)
    assert row is not None
    return row


def _apply(
    client: TestClient,
    parameter_set_id: Any,
    *,
    families: list[str] | None = None,
    observation_ids: list[str] | None = None,
) -> Any:
    body: dict[str, Any] = dict(_BODY)
    if families is not None:
        body["families"] = families
    if observation_ids is not None:
        body["observation_ids"] = observation_ids
    return client.post(f"/parameter-sets/{parameter_set_id}/apply-rules", json=body)


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _drain(engine: Engine, store: LocalArtifactStore) -> None:
    factory = _factory(engine)
    while True:
        claimed = claim_next_job(factory, "rule-apply-test")
        if claimed is None:
            return
        execute_job(factory, claimed, "rule-apply-test", artifact_store=store)


@pytest.mark.db
def test_booking_origin_a_room_nights_updates_cross_border_premium(
    client: TestClient,
    db_session: Session,
) -> None:
    base = _baseline(db_session, ORIGIN_A)
    loaded = load_gate_fixtures(db_session, accept=True, families={"booking"})
    db_session.commit()
    before = db_session.scalar(select(func.count()).select_from(ParameterSet))
    preview = client.post(
        f"/parameter-sets/{base.id}/rule-preview",
        json={**_BODY, "families": ["booking"]},
    )
    assert preview.status_code == 200, preview.text
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(ParameterSet)) == before
    assert db_session.scalar(select(func.count()).select_from(ParameterSetContext)) == 0

    applied = _apply(client, base.id, families=["booking"])
    assert applied.status_code == 201, applied.text
    body = applied.json()
    assert body["changed"] is True
    assert body["created"] is True
    assert body["result_parameter_set_id"] != str(base.id)
    update = next(item for item in body["updates"] if item["target_parameter"] == "cross_border_growth_premium")
    assert update["rule_key"] == "booking_room_nights_to_cross_border_premium"
    assert update["after_value"]["value"] == pytest.approx(0.023)
    assert update["after_value"]["fallback"] is True
    assert update["after_value"]["n_aligned"] < 12
    assert update["observation_id"] == str(loaded["bkng_2024q1_room_nights_yoy"].id)
    reasons = {item["observation_id"]: item["reason"] for item in body["context"]}
    assert reasons[str(loaded["bkng_2024q1_gross_bookings_yoy"].id)] == "no_adopted_rule"
    assert reasons[str(loaded["bkng_2024q1_ceo_qualitative"].id)] == "no_adopted_rule"

    db_session.expire_all()
    child = db_session.get(ParameterSet, body["result_parameter_set_id"])
    assert child is not None
    assert child.parent_id == base.id
    assert child.values["cross_border_growth_premium"] == pytest.approx(0.023)
    assert parameter_set_from_row(child).computed_content_hash() == child.content_hash
    for payload in child.evidence_links.values():
        assert payload["observation_ids"] or payload["assumption"] is True

    updates = client.get(f"/parameter-sets/{child.id}/updates")
    assert updates.status_code == 200, updates.text
    detail = updates.json()[0]
    assert detail["rule_key"] == "booking_room_nights_to_cross_border_premium"
    assert detail["observation_ids"] == [str(loaded["bkng_2024q1_room_nights_yoy"].id)]
    context = client.get(f"/parameter-sets/{child.id}/context")
    assert context.status_code == 200
    assert {item["reason"] for item in context.json()} == {"no_adopted_rule"}


@pytest.mark.db
def test_qualitative_only_input_leaves_the_set_unchanged(client: TestClient, db_session: Session) -> None:
    base = _baseline(db_session, ORIGIN_A)
    loaded = load_gate_fixtures(db_session, accept=True, families={"booking"})
    db_session.commit()
    qualitative = loaded["bkng_2024q1_ceo_qualitative"]
    applied = _apply(client, base.id, observation_ids=[str(qualitative.id)])
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["changed"] is False
    assert body["result_parameter_set_id"] == str(base.id)
    assert body["updates"] == []
    assert body["context"][0]["reason"] == "no_adopted_rule"
    db_session.expire_all()
    assert db_session.scalars(select(ParameterUpdate).where(ParameterUpdate.parameter_set_id == base.id)).all() == []
    stored = db_session.scalars(
        select(ParameterSetContext).where(ParameterSetContext.parameter_set_id == base.id)
    ).one()
    assert stored.observation_id == qualitative.id
    assert stored.reason == "no_adopted_rule"


@pytest.mark.db
def test_booking_origin_b_guidance_supersedes_measured_room_nights(client: TestClient, db_session: Session) -> None:
    base = _baseline(db_session, ORIGIN_B)
    loaded = load_gate_fixtures(db_session, accept=True, families={"booking"})
    db_session.commit()
    applied = _apply(client, base.id, families=["booking"])
    assert applied.status_code == 201, applied.text
    body = applied.json()
    update = next(item for item in body["updates"] if item["target_parameter"] == "cross_border_growth_premium")
    assert update["rule_key"] == "booking_guidance_to_cross_border_premium"
    assert update["after_value"]["value"] == pytest.approx(0.011)
    assert update["observation_id"] == str(loaded["bkng_2025q4_room_nights_guidance"].id)
    reasons = {item["observation_id"]: item["reason"] for item in body["context"]}
    assert reasons[str(loaded["bkng_2025q3_room_nights_yoy"].id)] == "superseded"


@pytest.mark.db
def test_census_adv2406_scales_payments_volume_by_us_share(client: TestClient, db_session: Session) -> None:
    base = _baseline(db_session, ORIGIN_A)
    loaded = load_gate_fixtures(db_session, accept=True, families={"census"})
    db_session.commit()
    applied = _apply(client, base.id, families=["census"])
    assert applied.status_code == 201, applied.text
    update = applied.json()["updates"][0]
    assert update["target_parameter"] == "payments_volume_growth"
    assert update["after_value"]["value"] == pytest.approx(0.078875)
    assert update["after_value"]["fallback"] is True
    assert update["observation_id"] == str(loaded["census:adv2406:retail_food_services_total:yoy_3m_pct"].id)
    assert "0.45" in update["rationale"]


@pytest.mark.db
def test_second_wave_observations_stay_context(client: TestClient, db_session: Session) -> None:
    base = _baseline(db_session, ORIGIN_A)
    load_gate_fixtures(db_session, accept=True, families={"airline", "retailer", "processor"})
    db_session.commit()
    applied = _apply(client, base.id, families=["airline", "retailer", "processor"])
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["changed"] is False
    assert body["updates"] == []
    assert body["context"]
    assert {item["reason"] for item in body["context"]} == {"context_only"}
    db_session.expire_all()
    assert db_session.scalars(select(ParameterUpdate)).all() == []


@pytest.mark.db
def test_pending_post_cutoff_and_non_visa_are_rejected(client: TestClient, db_session: Session) -> None:
    base = _baseline(db_session, ORIGIN_A)
    pending = load_gate_fixtures(db_session, accept=False, families={"booking"})
    db_session.commit()
    rejected = _apply(client, base.id, observation_ids=[str(pending["bkng_2024q1_room_nights_yoy"].id)])
    assert rejected.status_code == 422
    assert "reviewed" in rejected.json()["detail"]

    published = parse_aware_utc("2026-08-04T20:03:14Z")
    source = Source(
        provider="sec",
        company="booking",
        doc_type="8-K Ex. 99.1",
        url="https://www.sec.gov/Archives/edgar/data/1075531/000107553126000036/q2-26bkngearningsrelease.htm",
        publication_ts=published,
        retrieval_ts=published + timedelta(seconds=1),
        content_hash=POST_CUTOFF_HASH,
        original_path="data/fixtures/observations/booking_2026-08-04.json",
        attributes={"accession": "0001075531-26-000036", "document": "q2-26bkngearningsrelease.htm"},
    )
    db_session.add(source)
    db_session.flush()
    late = Observation(
        company="booking",
        source_id=source.id,
        statement_type="measured",
        activity_type="room_nights",
        geography="global",
        period_start=published.date().replace(month=4, day=1),
        period_end=published.date().replace(month=6, day=30),
        value=9.0,
        unit="percent",
        basis="units",
        source_family="booking",
        extractor_id="manual_gate",
        extractor_version="lon-21-test",
        review_status="pending",
        attributes={"fixture_observation_id": "bkng_2026q2_room_nights_yoy"},
    )
    db_session.add(late)
    db_session.flush()
    record_decision(
        db_session,
        observation_id=late.id,
        decision="accept",
        rationale="Accepted only to prove the cutoff gate.",
        decided_by="lon-21-test",
    )
    db_session.commit()
    late_response = _apply(client, base.id, observation_ids=[str(late.id)])
    assert late_response.status_code == 422
    assert "cutoff" in late_response.json()["detail"]

    other = ParameterSet(
        company="acme",
        cutoff_ts=_cutoff(ORIGIN_A),
        values={"payments_volume_growth": 0.08},
        ranges={},
        evidence_links={},
        assumption_flags={},
        content_hash=uuid4().hex,
    )
    db_session.add(other)
    db_session.commit()
    foreign = _apply(client, other.id, families=["booking"])
    assert foreign.status_code == 422
    assert "visa" in foreign.json()["detail"]


@pytest.mark.db
def test_reapply_is_idempotent_and_lineage_starts_at_the_root(client: TestClient, db_session: Session) -> None:
    base = _baseline(db_session, ORIGIN_A)
    load_gate_fixtures(db_session, accept=True, families={"booking"})
    db_session.commit()
    first = _apply(client, base.id, families=["booking"])
    assert first.status_code == 201, first.text
    child_id = first.json()["result_parameter_set_id"]
    second = _apply(client, base.id, families=["booking"])
    assert second.status_code == 200, second.text
    assert second.json()["created"] is False
    assert second.json()["result_parameter_set_id"] == child_id
    db_session.expire_all()
    updates = db_session.scalars(select(ParameterUpdate).where(ParameterUpdate.parameter_set_id == child_id)).all()
    assert len(updates) == 1
    context_rows = db_session.scalars(
        select(ParameterSetContext).where(ParameterSetContext.parameter_set_id == child_id)
    ).all()
    assert len(context_rows) == len({row.observation_id for row in context_rows})
    lineage = client.get(f"/parameter-sets/{child_id}/lineage")
    assert lineage.status_code == 200, lineage.text
    assert [item["id"] for item in lineage.json()] == [str(base.id), child_id]


@pytest.mark.db
def test_correction_uses_the_effective_value(client: TestClient, db_session: Session) -> None:
    base = _baseline(db_session, ORIGIN_A)
    loaded = load_gate_fixtures(db_session, accept=True, families={"booking"})
    room_nights = loaded["bkng_2024q1_room_nights_yoy"]
    record_decision(
        db_session,
        observation_id=room_nights.id,
        decision="correct",
        rationale="The print is 12 percent, not 9.",
        decided_by="lon-21-test",
        corrected_payload={"value": 12.0},
    )
    db_session.commit()
    applied = _apply(client, base.id, observation_ids=[str(room_nights.id)])
    assert applied.status_code == 201, applied.text
    update = applied.json()["updates"][0]
    assert update["after_value"]["value"] == pytest.approx(0.032)


@pytest.mark.db
def test_child_set_rule_is_cited_by_attribution(
    client: TestClient,
    db_session: Session,
    test_engine: Engine,
    artifact_store: LocalArtifactStore,
) -> None:
    base = _baseline(db_session, ORIGIN_A)
    load_gate_fixtures(db_session, accept=True, families={"booking"})
    db_session.commit()
    applied = _apply(client, base.id, families=["booking"])
    assert applied.status_code == 201, applied.text
    child_id = applied.json()["result_parameter_set_id"]
    db_session.expire_all()
    rule = db_session.scalars(
        select(MappingRule).where(MappingRule.rule_key == "booking_room_nights_to_cross_border_premium")
    ).one()
    group = str(uuid4())
    cutoff = _cutoff(ORIGIN_A)
    baseline = client.post(
        "/scenarios",
        json={"company": "visa", "name": "baseline", "parameter_set_id": str(base.id), "pair_group_id": group},
    )
    variant = client.post(
        "/scenarios",
        json={
            "company": "visa",
            "name": "mix",
            "parameter_set_id": child_id,
            "pair_group_id": group,
            "interventions": [{"type": "mix_shift_conserving_total", "cross_border_change": -0.10}],
        },
    )
    assert baseline.status_code == variant.status_code == 201
    paired = client.post(
        "/scenarios/pair-runs",
        json={
            "scenario_ids": [baseline.json()["id"], variant.json()["id"]],
            "baseline_scenario_id": baseline.json()["id"],
            "cutoff_ts": cutoff.isoformat(),
            "seed": 21,
            "n_paths": 8,
            "n_quarters": 4,
        },
    )
    assert paired.status_code == 202, paired.text
    _drain(test_engine, artifact_store)
    attribution = client.get(
        "/scenarios/attribution",
        params={"run_id": paired.json()[1]["id"], "metric": "net_revenue"},
    )
    assert attribution.status_code == 200, attribution.text
    growth = next(
        item for item in attribution.json()["sensitivity"] if item["parameter"] == "cross_border_growth_premium"
    )
    assert str(rule.id) in growth["rule_ids"]
