"""Versioned review decisions and the run guard (LON-16 / FR-05)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ParameterEvidence, ParameterSetCreate
from longaeva_app.db.models import Observation, ParameterSet, Scenario, Source
from longaeva_app.review.service import ReviewError, effective_observation, record_decision, require_reviewed
from longaeva_app.runs.inputs import (
    default_parameter_ranges,
    default_parameter_values,
    parse_aware_utc,
    resolve_fixture_by_origin_date,
)

ORIGIN = "2024-07-23"


def _cutoff() -> datetime:
    return parse_aware_utc(resolve_fixture_by_origin_date(ORIGIN).cutoff_utc)


def _source(session: Session) -> Source:
    published = datetime(2025, 10, 28, tzinfo=UTC)
    row = Source(
        provider="sec",
        company="booking",
        doc_type="8-K Ex. 99.1",
        url="https://www.sec.gov/Archives/edgar/data/1075531/example.htm",
        publication_ts=published,
        retrieval_ts=published + timedelta(hours=1),
        content_hash=uuid4().hex,
        original_path="fixtures/booking/review",
        attributes={},
    )
    session.add(row)
    session.flush()
    return row


def _observation(session: Session, source: Source, *, value: float = 8.0) -> Observation:
    row = Observation(
        company="booking",
        source_id=source.id,
        statement_type="measured",
        activity_type="room_nights",
        geography="global",
        period_start=date(2025, 7, 1),
        period_end=date(2025, 9, 30),
        value=value,
        unit="percent",
        basis="units",
        source_family="booking",
        extractor_id="llm_extract",
        extractor_version="lon-16-v1",
        review_status="pending",
        attributes={"quote": "Room nights grew 8%"},
    )
    session.add(row)
    session.flush()
    return row


def _parameter_set(session: Session, observation_id: Any, cutoff: datetime) -> ParameterSet:
    values = default_parameter_values()
    links: dict[str, ParameterEvidence] = {}
    flags: dict[str, Any] = {}
    first = True
    for name in values:
        if first:
            links[name] = ParameterEvidence(observation_ids=[observation_id])
            flags[name] = False
            first = False
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


@pytest.mark.db
def test_decisions_are_versioned_and_effective_values_follow_the_latest_correction(
    client: TestClient,
    db_session: Session,
) -> None:
    source = _source(db_session)
    observation = _observation(db_session, source)
    observation_id = str(observation.id)
    db_session.commit()

    empty = client.get(f"/observations/{observation_id}/review")
    assert empty.status_code == 200, empty.text
    assert empty.json()["effective"] is None
    assert empty.json()["decisions"] == []

    accepted = client.post(
        "/review-decisions",
        json={
            "observation_id": observation_id,
            "decision": "accept",
            "rationale": "quote matches the passage",
            "decided_by": "tester",
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["version"] == 1
    assert accepted.json()["decision"] == "accept"

    reviewed = client.get(f"/observations/{observation_id}/review")
    assert reviewed.status_code == 200
    body = reviewed.json()
    assert body["observation"]["review_status"] == "accepted"
    assert body["observation"]["value"] == 8.0
    assert body["effective"]["value"] == 8.0
    assert body["effective"]["review_status"] == "accepted"

    corrected = client.post(
        "/review-decisions",
        json={
            "observation_id": observation_id,
            "decision": "correct",
            "corrected_payload": {"value": 9.0},
            "rationale": "the stated figure is 9",
            "decided_by": "tester",
        },
    )
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["version"] == 2
    after_correct = client.get(f"/observations/{observation_id}/review").json()
    assert after_correct["observation"]["value"] == 8.0
    assert after_correct["observation"]["review_status"] == "corrected"
    assert after_correct["effective"]["value"] == 9.0

    rejected = client.post(
        "/review-decisions",
        json={
            "observation_id": observation_id,
            "decision": "reject",
            "rationale": "not supported",
            "decided_by": "tester",
        },
    )
    assert rejected.status_code == 201, rejected.text
    assert rejected.json()["version"] == 3
    after_reject = client.get(f"/observations/{observation_id}/review").json()
    assert after_reject["observation"]["review_status"] == "rejected"
    assert after_reject["effective"] is None
    assert [item["version"] for item in after_reject["decisions"]] == [1, 2, 3]

    listed = client.get("/review-decisions", params={"observation_id": observation_id})
    assert listed.status_code == 200
    assert [item["version"] for item in listed.json()] == [1, 2, 3]

    confidence = client.post(
        "/review-decisions",
        json={
            "observation_id": observation_id,
            "decision": "correct",
            "corrected_payload": {"confidence": 0.9},
            "rationale": "no",
            "decided_by": "tester",
        },
    )
    assert confidence.status_code == 422
    unknown = client.post(
        "/review-decisions",
        json={
            "observation_id": observation_id,
            "decision": "correct",
            "corrected_payload": {"not_a_field": 1},
            "rationale": "no",
            "decided_by": "tester",
        },
    )
    assert unknown.status_code == 422
    inverted = client.post(
        "/review-decisions",
        json={
            "observation_id": observation_id,
            "decision": "correct",
            "corrected_payload": {"value": None, "range_low": 12, "range_high": 4},
            "rationale": "no",
            "decided_by": "tester",
        },
    )
    assert inverted.status_code == 422
    extra = client.post(
        "/review-decisions",
        json={
            "observation_id": observation_id,
            "decision": "accept",
            "corrected_payload": {"value": 1},
            "rationale": "no",
            "decided_by": "tester",
        },
    )
    assert extra.status_code == 422
    missing = client.post(
        "/review-decisions",
        json={
            "observation_id": str(uuid4()),
            "decision": "accept",
            "rationale": "missing",
            "decided_by": "tester",
        },
    )
    assert missing.status_code == 404


@pytest.mark.db
def test_require_reviewed_and_effective_observation(db_session: Session) -> None:
    source = _source(db_session)
    observation = _observation(db_session, source)
    assert effective_observation(db_session, observation) is None
    with pytest.raises(ReviewError, match="not reviewed"):
        require_reviewed(db_session, [observation.id])
    record_decision(
        db_session,
        observation_id=observation.id,
        decision="accept",
        rationale="ok",
        decided_by="tester",
    )
    reviewed = require_reviewed(db_session, [observation.id])
    assert reviewed[0].review_status == "accepted"
    effective = effective_observation(db_session, observation)
    assert effective is not None
    assert effective["value"] == 8.0


@pytest.mark.db
def test_submit_run_refuses_a_pending_observation_until_it_is_reviewed(
    client: TestClient,
    db_session: Session,
) -> None:
    source = _source(db_session)
    observation = _observation(db_session, source)
    cutoff = _cutoff()
    # Keep publication eligibility valid while exercising the independent review guard.
    source.publication_ts = cutoff - timedelta(days=1)
    source.retrieval_ts = cutoff - timedelta(hours=1)
    observation.period_start = date(2024, 4, 1)
    observation.period_end = date(2024, 6, 30)
    param_set = _parameter_set(db_session, observation.id, cutoff)
    scenario = Scenario(
        company="visa",
        name="review-guard",
        parameter_set_id=param_set.id,
        interventions=[],
    )
    db_session.add(scenario)
    db_session.commit()

    body = {
        "scenario_id": str(scenario.id),
        "cutoff_ts": cutoff.isoformat(),
        "seed": 7,
        "n_paths": 32,
        "n_quarters": 4,
        "switches": {},
    }
    refused = client.post("/runs", json=body)
    assert refused.status_code == 422, refused.text
    assert "not reviewed" in refused.json()["detail"]

    accepted = client.post(
        "/review-decisions",
        json={
            "observation_id": str(observation.id),
            "decision": "accept",
            "rationale": "reviewed",
            "decided_by": "tester",
        },
    )
    assert accepted.status_code == 201, accepted.text
    allowed = client.post("/runs", json=body)
    assert allowed.status_code == 202, allowed.text
    # A reviewed observation still cannot use a document published after the cutoff.
    source.publication_ts = cutoff + timedelta(seconds=1)
    source.retrieval_ts = cutoff + timedelta(seconds=2)
    db_session.commit()
    late = client.post("/runs", json=body)
    assert late.status_code == 422
    assert "published after" in late.json()["detail"]
