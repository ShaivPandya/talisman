"""Mapping-rule registry, analyst ranges, and the estimated-rule fitter (LON-21)."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from longaeva_app.companies.visa.parameters import VISA_PARAMETERS
from longaeva_app.db.models import MappingRule
from longaeva_app.review.rules import (
    REGISTRY,
    AnalystRange,
    Estimated,
    RuleRegistryError,
    RuleSpec,
    aligned_pairs,
    apply_analyst_range,
    apply_transform,
    fit_coefficient,
    reject_probability_fields,
    sync_registry,
)
from longaeva_app.runs.inputs import parse_aware_utc

_FALLBACK = AnalystRange(anchor=0.08, scale=1.0, beta_low=0.2, beta_high=0.4, max_abs_shift=0.04)
_BOUNDS = (-0.2, 0.4)


def test_registry_targets_are_visa_parameters_and_hashes_are_stable() -> None:
    names = {spec.name for spec in VISA_PARAMETERS}
    keys = [(spec.rule_key, spec.version) for spec in REGISTRY]
    assert len(keys) == len(set(keys))
    for spec in REGISTRY:
        assert spec.definition_hash() == spec.definition_hash()
        assert "confidence" not in spec.transform_dict()
        assert "probability" not in spec.transform_dict()
        if spec.kind == "context":
            assert spec.target_parameter is None
            continue
        assert spec.target_parameter in names
        assert spec.kind in {"estimated", "analyst_range"}


def test_qualitative_input_cannot_be_estimated() -> None:
    with pytest.raises(ValueError, match="qualitative"):
        RuleSpec(
            rule_key="qualitative_estimated",
            version=1,
            kind="estimated",
            source_family="booking",
            input_type="qualitative",
            rationale="A qualitative statement is not a coefficient.",
            value_test="not_used",
            target_parameter="cross_border_growth_premium",
            estimated=Estimated(
                visa_field="cross_border_ex_intra_europe_growth_constant",
                alignment="next_visa_quarter",
                fallback=_FALLBACK,
            ),
        )


def test_probability_and_confidence_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="confidence"):
        reject_probability_fields({"op": "analyst_range", "confidence": 0.9})
    with pytest.raises(ValueError, match="probability"):
        reject_probability_fields({"fallback": {"probability": 0.5}})


def test_analyst_range_shift_cap_and_clamp() -> None:
    room_nights = apply_analyst_range(
        _FALLBACK,
        before=0.02,
        range_low=-0.2,
        range_high=0.4,
        observed=0.09,
        half_width=0.0,
        bounds=_BOUNDS,
    )
    assert room_nights.value == pytest.approx(0.023)
    assert room_nights.size == pytest.approx(0.003)
    assert room_nights.assumption is True
    assert room_nights.after_value["range_low"] == pytest.approx(0.022)
    assert room_nights.after_value["range_high"] == pytest.approx(0.024)

    capped = apply_analyst_range(
        _FALLBACK,
        before=0.02,
        range_low=-0.2,
        range_high=0.4,
        observed=0.50,
        half_width=0.0,
        bounds=_BOUNDS,
    )
    assert capped.value == pytest.approx(0.06)
    assert capped.size == pytest.approx(0.04)

    clamped = apply_analyst_range(
        _FALLBACK,
        before=0.39,
        range_low=-0.2,
        range_high=0.4,
        observed=0.50,
        half_width=0.0,
        bounds=_BOUNDS,
    )
    assert clamped.value == pytest.approx(0.4)


def test_guidance_midpoint_widens_the_recorded_range() -> None:
    spec = next(item for item in REGISTRY if item.rule_key == "booking_guidance_to_cross_border_premium")
    result = apply_transform(
        spec,
        before=0.02,
        range_low=-0.2,
        range_high=0.4,
        observed=0.05,
        half_width=0.01,
    )
    assert result.value == pytest.approx(0.011)
    assert result.after_value["range_low"] == pytest.approx(0.004)
    assert result.after_value["range_high"] == pytest.approx(0.018)
    assert result.assumption is True


def test_fitter_recovers_slope_at_twelve_quarters_and_falls_back_below() -> None:
    pairs = [(index / 10.0, 0.5 * (index / 10.0) + 0.02) for index in range(12)]
    fit = fit_coefficient(pairs)
    assert fit.sufficient is True
    assert fit.n == 12
    assert fit.slope == pytest.approx(0.5)
    assert fit.intercept == pytest.approx(0.02)
    assert fit.stderr == pytest.approx(0.0, abs=1e-12)

    short = fit_coefficient(pairs[:11])
    assert short.sufficient is False
    assert short.n == 11
    flat = fit_coefficient([(0.05, 0.1 + index * 0.001) for index in range(12)])
    assert flat.sufficient is False
    exact = fit_coefficient([(1.0, float(index)) for index in range(12)])
    assert exact.sufficient is False

    spec = next(item for item in REGISTRY if item.rule_key == "booking_room_nights_to_cross_border_premium")
    fitted = apply_transform(
        spec,
        before=0.02,
        range_low=-0.2,
        range_high=0.4,
        observed=0.065,
        half_width=0.0,
        pairs=[(index * 0.01, 0.5 * index * 0.01 + 0.02) for index in range(12)],
    )
    assert fitted.assumption is False
    assert fitted.after_value["fallback"] is False
    assert fitted.after_value["slope"] == pytest.approx(0.5)
    assert fitted.value == pytest.approx(0.025)

    fallback = apply_transform(
        spec,
        before=0.02,
        range_low=-0.2,
        range_high=0.4,
        observed=0.09,
        half_width=0.0,
        pairs=[(0.09, 0.1)],
    )
    assert fallback.assumption is True
    assert fallback.after_value["fallback"] is True
    assert fallback.after_value["n_aligned"] == 1
    assert fallback.value == pytest.approx(0.023)


def test_retained_history_threshold_counts_quarterly_census_and_sparse_booking() -> None:
    cutoff = parse_aware_utc("2024-07-23T20:05:38Z")
    assert isinstance(cutoff, datetime)
    for key in ("booking_room_nights_to_cross_border_premium", "census_retail_yoy_to_payments_volume_growth"):
        spec = next(item for item in REGISTRY if item.rule_key == key)
        pairs = aligned_pairs(spec, cutoff)
        if spec.source_family == "booking":
            assert len(pairs) < 12
        else:
            assert len(pairs) >= 12


@pytest.mark.db
def test_sync_is_idempotent_and_refuses_a_silent_edit(db_session: Session) -> None:
    first = sync_registry(db_session)
    db_session.commit()
    second = sync_registry(db_session)
    assert len(first) == len(second) == len(REGISTRY)
    assert {row.rule_key for row in second} == {spec.rule_key for spec in REGISTRY}

    stale = db_session.scalars(select(MappingRule).where(MappingRule.rule_key == "airline_context")).one()
    stale.definition_hash = "stale"
    db_session.commit()
    with pytest.raises(RuleRegistryError, match="version bump"):
        sync_registry(db_session)
