"""Attribution decomposition, support flags, and provenance."""

from __future__ import annotations

import json

import pytest

from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.calibration import artifact_path
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.companies.visa.state import synthetic_starting_state
from longaeva_app.engine.attribution import (
    FLAG_NAME,
    ORDER_NOTE,
    annotate_support,
    attribute_changes,
    support_score,
    weak_support_flag,
)
from longaeva_app.scenarios.provenance import (
    ObservationView,
    RuleView,
    UpdateView,
    provenance_for_parameter,
)


def _texts(result: object) -> str:
    return json.dumps(result, default=lambda item: getattr(item, "__dict__", str(item)))


def test_sequential_sums_and_single_change_residual_is_zero() -> None:
    model = VisaModel()
    params = model.default_parameters()
    variant = dict(params)
    variant["payments_volume_growth"] = params["payments_volume_growth"] + 0.02
    start = synthetic_starting_state()
    origin = FiscalPeriod(2024, 3)
    both = attribute_changes(
        model,
        start,
        baseline_params=params,
        variant_params=variant,
        variant_interventions=[{"type": "total_spend_reduction", "reduction": 0.05}],
        origin=origin,
        seed=3,
        n_paths=24,
        n_quarters=4,
        include_sensitivity=False,
    )
    for metric, total in both.horizon_totals.items():
        sequential = sum(item.effects[metric].sequential_horizon for item in both.contributions)
        assert sequential == pytest.approx(total)
        assert abs(both.joint_residual_horizon[metric]) > 1.0
    assert both.sequential_order[0].startswith("parameter:")
    assert both.sequential_order[-1].startswith("intervention:")

    single = attribute_changes(
        model,
        start,
        baseline_params=params,
        variant_params=params,
        variant_interventions=[{"type": "mix_shift_conserving_total", "cross_border_change": -0.1}],
        origin=origin,
        seed=3,
        n_paths=16,
        n_quarters=2,
        include_sensitivity=False,
    )
    for metric, residual in single.joint_residual_horizon.items():
        assert residual == pytest.approx(0.0)
        assert len(single.contributions) == 1
        assert single.contributions[0].effects[metric].one_at_a_time_horizon == pytest.approx(
            single.horizon_totals[metric]
        )


def test_support_score_and_flag_rule() -> None:
    assert support_score([], assumption=True, review_statuses={}) == 0.0
    assert support_score(["obs"], assumption=False, review_statuses={"obs": "accepted"}) == 1.0
    assert support_score(["obs"], assumption=True, review_statuses={"obs": "corrected"}) == 0.5
    assert support_score(["obs"], assumption=False, review_statuses={"obs": "pending"}) == 0.0
    assert support_score(["obs"], assumption=True, review_statuses={"obs": "rejected"}) == 0.0
    assert support_score(["calibrated"], assumption=False, review_statuses={}) == 1.0
    assert weak_support_flag(1.0, 0.0) == FLAG_NAME
    assert weak_support_flag(0.24, 0.0) is None
    assert weak_support_flag(0.5, 0.5) == FLAG_NAME
    assert weak_support_flag(0.4, 0.5) is None


def test_default_ranking_is_ordered_and_labels_are_not_causal() -> None:
    model = VisaModel()
    params = model.default_parameters()
    result = attribute_changes(
        model,
        synthetic_starting_state(),
        baseline_params=params,
        variant_params=params,
        variant_interventions=[{"type": "mix_shift_conserving_total", "cross_border_change": -0.10}],
        origin=FiscalPeriod(2024, 3),
        seed=5,
        n_paths=16,
        n_quarters=4,
        include_sensitivity=True,
    )
    evidence: dict[str, tuple[tuple[str, ...], bool]] = {spec.name: ((), True) for spec in model.parameters}
    ranked = annotate_support(result.sensitivity, evidence=evidence)
    sensitivities = [item.normalized_sensitivity for item in ranked]
    assert sensitivities == sorted(sensitivities, reverse=True)
    flagged = [item.parameter for item in ranked if item.flag == FLAG_NAME]
    assert flagged
    assert all(item.normalized_sensitivity * (1.0 - item.support_score) >= 0.25 for item in ranked if item.flag)
    share = next(item for item in ranked if item.parameter == "cross_border_share_at_origin")
    # Spec-bound seasonals move the horizon mean far more than the share assumption,
    # so the share is weakly supported but not flagged.
    assert share.support_score == 0.0
    assert share.flag is None
    blob = ORDER_NOTE + " ".join(item.label for item in result.contributions)
    assert "caus" not in blob


def test_provenance_lists_rule_and_source_ids_and_calibration_fallback() -> None:
    observation = ObservationView(
        observation_id="obs-1",
        source_id="source-1",
        document_text_id="passage-1",
        span_page=2,
        span_char_start=10,
        span_char_end=40,
        review_status="accepted",
    )
    rule = RuleView(rule_id="rule-1", rule_key="travel_to_share", version=1)
    bundle = provenance_for_parameter(
        "cross_border_share_at_origin",
        ["obs-1"],
        observations={"obs-1": observation},
        evidence_index={},
        updates=(UpdateView(target_parameter="cross_border_share_at_origin", rule_id="rule-1"),),
        rules={"rule-1": rule},
    )
    assert bundle.rule_ids == ("rule-1",)
    assert "source-1" in bundle.source_ids
    assert "obs-1" in bundle.observation_ids
    assert any(ref.rule_key == "travel_to_share" and ref.rule_version == 1 for ref in bundle.refs)

    artifact = json.loads(artifact_path("2024-07-23").read_text(encoding="utf-8"))
    obs_id, indexed = next(iter(artifact["evidence_index"].items()))
    fallback = provenance_for_parameter(
        "payments_volume_growth",
        [obs_id],
        observations={},
        evidence_index=artifact["evidence_index"],
        updates=(),
        rules={},
    )
    assert fallback.source_ids == (indexed["source_id"],)
    assert fallback.refs[0].span_char_start == indexed["char_start"]
    assert fallback.refs[0].span_char_end == indexed["char_end"]
