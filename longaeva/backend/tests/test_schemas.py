"""Pydantic schema validation tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from longaeva_app.api.schemas import ObservationCreate, ParameterEvidence, ParameterSetCreate, SourceCreate
from longaeva_app.hashing import content_hash


def test_observation_rejects_missing_unit() -> None:
    with pytest.raises(ValidationError):
        ObservationCreate(
            company="visa",
            source_id=uuid4(),
            statement_type="measured",
            period_start=date(2024, 4, 1),
            period_end=date(2024, 6, 30),
            value=1.0,
            unit="",
        )


def test_observation_rejects_missing_period() -> None:
    with pytest.raises(ValidationError):
        ObservationCreate(  # type: ignore[call-arg]
            company="visa",
            source_id=uuid4(),
            statement_type="measured",
            value=1.0,
            unit="usd_millions",
        )


@pytest.mark.parametrize(
    "statement_type,kwargs",
    [
        ("measured", {"value": 1.0, "source_id": uuid4()}),
        ("guidance", {"value": 2.0, "source_id": uuid4()}),
        ("qualitative", {"source_id": uuid4()}),
        ("analyst_assumption", {"value": 0.01, "source_id": None}),
        ("intervention", {"range_low": 0.0, "range_high": 0.1, "source_id": None}),
    ],
)
def test_observation_accepts_each_statement_type(statement_type: str, kwargs: dict[str, object]) -> None:
    obs = ObservationCreate(
        company="visa",
        statement_type=statement_type,  # type: ignore[arg-type]
        period_start=date(2024, 4, 1),
        period_end=date(2024, 6, 30),
        unit="ratio",
        **kwargs,  # type: ignore[arg-type]
    )
    assert obs.statement_type == statement_type


def test_observation_rejects_confidence_attribute() -> None:
    with pytest.raises(ValidationError):
        ObservationCreate(
            company="visa",
            source_id=uuid4(),
            statement_type="measured",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 3, 31),
            value=1.0,
            unit="usd_millions",
            attributes={"confidence": 0.9},
        )


def test_source_requires_publication_before_retrieval() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        SourceCreate(
            provider="sec",
            company="visa",
            doc_type="8-K",
            url="https://example.test",
            publication_ts=now,
            retrieval_ts=now,
            content_hash="abc",
            original_path="originals/ab/abc",
        )


def test_parameter_set_requires_evidence_or_assumption() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        ParameterSetCreate(
            company="visa",
            cutoff_ts=now,
            values={"yield": 0.01},
            evidence_links={},
        )


def test_parameter_evidence_assumption_needs_rationale() -> None:
    with pytest.raises(ValidationError):
        ParameterEvidence(assumption=True, rationale="")


def test_content_hash_stable_across_key_order_and_roundtrip() -> None:
    payload_a = {"b": 2, "a": {"z": 1, "y": [3, 1]}}
    payload_b = {"a": {"y": [3, 1], "z": 1}, "b": 2}
    assert content_hash(payload_a) == content_hash(payload_b)

    now = datetime(2024, 7, 23, 12, 0, 0, tzinfo=UTC)
    create = ParameterSetCreate(
        company="visa",
        cutoff_ts=now,
        values={"yield": 0.01, "drift": 0.02},
        ranges={"yield": [0.005, 0.02]},
        evidence_links={
            "yield": ParameterEvidence(assumption=True, rationale="history"),
            "drift": ParameterEvidence(observation_ids=[uuid4()], assumption=False),
        },
    )
    h1 = create.computed_content_hash()
    reloaded = ParameterSetCreate.model_validate(create.model_dump(mode="json"))
    assert reloaded.computed_content_hash() == h1


def test_parameter_set_hash_independent_of_dict_order() -> None:
    now = datetime.now(UTC) - timedelta(days=1)
    obs_id = uuid4()
    left = ParameterSetCreate(
        company="visa",
        cutoff_ts=now,
        values={"b": 2.0, "a": 1.0},
        evidence_links={
            "b": ParameterEvidence(assumption=True, rationale="b"),
            "a": ParameterEvidence(observation_ids=[obs_id]),
        },
    )
    right = ParameterSetCreate(
        company="visa",
        cutoff_ts=now,
        values={"a": 1.0, "b": 2.0},
        evidence_links={
            "a": ParameterEvidence(observation_ids=[obs_id]),
            "b": ParameterEvidence(assumption=True, rationale="b"),
        },
    )
    assert left.computed_content_hash() == right.computed_content_hash()


def test_parameter_set_hash_normalizes_cutoff_to_utc() -> None:
    eastern = timezone(timedelta(hours=-4))
    left = ParameterSetCreate(
        company="visa",
        cutoff_ts=datetime(2024, 7, 23, 16, 5, 38, tzinfo=eastern),
        values={"yield": 0.01},
        evidence_links={"yield": ParameterEvidence(assumption=True, rationale="x")},
    )
    right = ParameterSetCreate(
        company="visa",
        cutoff_ts=datetime(2024, 7, 23, 20, 5, 38, tzinfo=UTC),
        values={"yield": 0.01},
        evidence_links={"yield": ParameterEvidence(assumption=True, rationale="x")},
    )
    assert left.computed_content_hash() == right.computed_content_hash()
