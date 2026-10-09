"""Leakage guard tests for evaluation."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from longaeva_app.companies.visa.calibration import as_of, load_observation_rows
from longaeva_app.companies.visa.state_builder import build_fixture_for_origin_date
from longaeva_app.evaluation.leakage import (
    LeakageError,
    assert_inputs_before_cutoff,
    assert_outcome_after_cutoff,
    input_fingerprint,
)
from longaeva_app.evaluation.origins import load_evaluation_origins
from longaeva_app.evaluation.targets import build_driver_history
from longaeva_app.hashing import utc_isoformat
from longaeva_app.runs.inputs import parse_aware_utc


def test_late_starting_state_source_raises() -> None:
    fixture = build_fixture_for_origin_date("2024-01-25")
    cutoff = parse_aware_utc(fixture.cutoff_utc)
    # Poison one input source one second past the cutoff.
    key = next(iter(fixture.sources))
    ref = fixture.sources[key]
    poisoned = ref.model_copy(update={"acceptance_utc": utc_isoformat(cutoff + timedelta(seconds=1))})
    sources = dict(fixture.sources)
    sources[key] = poisoned
    with pytest.raises(LeakageError, match="starting_state"):
        assert_inputs_before_cutoff(cutoff, starting_state_sources=sources)


def test_late_calibration_evidence_raises() -> None:
    cutoff = parse_aware_utc("2024-07-23T20:05:38Z")
    evidence = {
        "obs-1": {
            "publication_ts": utc_isoformat(cutoff + timedelta(seconds=1)),
            "field": "net_revenue",
        }
    }
    with pytest.raises(LeakageError, match="calibration evidence"):
        assert_inputs_before_cutoff(cutoff, calibration_evidence=evidence)


def test_late_driver_history_raises() -> None:
    cutoff = parse_aware_utc("2024-07-23T20:05:38Z")
    history = [
        {
            "label": "FY2023Q3:payments_volume_nominal_us",
            "publication_ts": utc_isoformat(cutoff + timedelta(seconds=1)),
        }
    ]
    with pytest.raises(LeakageError, match="driver history"):
        assert_inputs_before_cutoff(cutoff, driver_history=history)


def test_outcome_at_or_before_cutoff_raises() -> None:
    cutoff = parse_aware_utc("2024-07-23T20:05:38Z")
    with pytest.raises(LeakageError, match="outcome"):
        assert_outcome_after_cutoff(cutoff, publication_ts=cutoff, label="net_revenue")
    with pytest.raises(LeakageError, match="outcome"):
        assert_outcome_after_cutoff(
            cutoff,
            publication_ts=cutoff - timedelta(seconds=1),
            label="net_revenue",
        )


def test_poisoned_late_rows_leave_fingerprint_unchanged() -> None:
    origins = [o for o in load_evaluation_origins() if o.scored][:3]
    rows = load_observation_rows()
    for origin in origins:
        fixture = build_fixture_for_origin_date(origin.origin_date, rows=rows)
        history = build_driver_history(origin, rows=rows)
        asof = as_of(rows, origin.cutoff_ts)
        fingerprint = input_fingerprint(
            starting_state_source_ids=fixture.sources.keys(),
            evidence_ids=[r.observation_id.hex for r in asof[:5]],
            manifest_keys=[k for k, v in fixture.sources.items() if v.role == "input"],
            driver_labels=history.labels,
        )
        base = rows[0]
        late = replace(
            base,
            publication_ts=origin.cutoff_ts + timedelta(seconds=1),
            value=float(base.value) + 999.0,
            note="poison",
            observation_id=uuid4(),
            char_start=base.char_start + 99_991,
            char_end=base.char_end + 99_991,
        )
        poisoned = [*rows, late]
        fixture2 = build_fixture_for_origin_date(origin.origin_date, rows=poisoned)
        history2 = build_driver_history(origin, rows=poisoned)
        asof2 = as_of(poisoned, origin.cutoff_ts)
        fingerprint2 = input_fingerprint(
            starting_state_source_ids=fixture2.sources.keys(),
            evidence_ids=[r.observation_id.hex for r in asof2[:5]],
            manifest_keys=[k for k, v in fixture2.sources.items() if v.role == "input"],
            driver_labels=history2.labels,
        )
        assert fingerprint == fingerprint2
