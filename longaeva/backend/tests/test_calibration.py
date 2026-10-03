"""Visa chronological calibration structure and golden artifacts (LON-20)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
import pytest
from sqlalchemy.orm import Session

from longaeva_app.api.schemas import ParameterEvidence, ParameterSetCreate
from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.calibration import (
    CalibrationResult,
    MemberFit,
    _geo_mean_normalize,
    is_pandemic_quarter,
    nearest_psd,
    parse_aware_utc,
    persist_calibrated,
    qoq_estimation_weight,
    yoy_estimation_weight,
)
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.companies.visa.parameters import VISA_PARAMETERS
from longaeva_app.companies.visa.starting_state import load_fixture, required_fixture_paths, to_starting_state
from longaeva_app.engine.runner import simulate
from longaeva_app.hashing import content_hash
from longaeva_app.runs.inputs import verify_parameter_set

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CALIBRATION_DIR = PACKAGE_ROOT / "data" / "calibration"
ARTIFACTS = (
    CALIBRATION_DIR / "visa_2024-07-23.json",
    CALIBRATION_DIR / "visa_2025-10-28.json",
)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_golden_weights_sum_to_one(path: Path) -> None:
    payload = _load(path)
    weights = payload["weights"]
    assert weights
    assert all(v >= 0.0 for v in weights.values())
    assert abs(sum(weights.values()) - 1.0) < 1e-9


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_golden_pooled_parameter_set(path: Path) -> None:
    payload = _load(path)
    pooled = payload["pooled"]
    create = ParameterSetCreate.model_validate(
        {
            "company": pooled["company"],
            "cutoff_ts": pooled["cutoff_ts"],
            "values": pooled["values"],
            "ranges": pooled["ranges"],
            "evidence_links": pooled["evidence_links"],
            "assumption_flags": pooled["assumption_flags"],
        }
    )
    assert set(create.values) == {spec.name for spec in VISA_PARAMETERS}
    for name, value in create.values.items():
        spec = next(s for s in VISA_PARAMETERS if s.name == name)
        assert spec.lower <= value <= spec.upper, name
        lo, hi = create.ranges[name]
        assert lo <= value <= hi or abs(value - lo) < 1e-12 or abs(value - hi) < 1e-12
        link = create.evidence_links[name]
        assert link.observation_ids or (link.assumption and link.rationale)
    assert VisaModel().validate_parameters(create.values) == []
    assert create.computed_content_hash() == pooled["content_hash"]


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_golden_seasonals_and_correlations(path: Path) -> None:
    values = _load(path)["pooled"]["values"]
    for prefix in ("activity_seasonal", "opex_seasonal", "cross_border_seasonal"):
        ratios = [values[f"{prefix}_q{q}"] for q in range(1, 5)]
        geo = math.exp(sum(math.log(r) for r in ratios) / 4.0)
        assert abs(geo - 1.0) < 1e-8
    corr = np.array(
        [
            [1.0, values["corr_demand_travel"], values["corr_demand_fx"]],
            [values["corr_demand_travel"], 1.0, values["corr_travel_fx"]],
            [values["corr_demand_fx"], values["corr_travel_fx"], 1.0],
        ]
    )
    assert float(np.min(np.linalg.eigvalsh(corr))) >= -1e-10


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_golden_sensitivity_finite(path: Path) -> None:
    rows = _load(path)["sensitivity"]
    assert len(rows) >= 10
    labels = {row["label"] for row in rows}
    assert "baseline_pooled" in labels
    assert "pandemic_included" in labels
    assert "service_yield_drift_low" in labels
    assert "cross_border_share_at_origin_high" in labels
    for row in rows:
        for key in (
            "next_quarter_mean_net_revenue",
            "next_quarter_mean_operating_profit_ex_special_items",
            "four_quarter_mean_net_revenue",
        ):
            assert math.isfinite(row[key])


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_golden_result_hash_self_consistent(path: Path) -> None:
    payload = _load(path)
    body = {k: v for k, v in payload.items() if k != "result_hash"}
    assert content_hash(body) == payload["result_hash"]


def test_pandemic_exclusion_windows() -> None:
    assert is_pandemic_quarter(FiscalPeriod(2020, 2))
    assert is_pandemic_quarter(FiscalPeriod(2021, 4))
    assert not is_pandemic_quarter(FiscalPeriod(2020, 1))
    assert not is_pandemic_quarter(FiscalPeriod(2022, 1))
    # YoY against pandemic bases through FY2022Q4.
    assert yoy_estimation_weight(FiscalPeriod(2022, 4), include_pandemic=False) == 0.0
    assert yoy_estimation_weight(FiscalPeriod(2023, 1), include_pandemic=False) == 1.0
    # QoQ touching pandemic through FY2022Q1.
    assert qoq_estimation_weight(FiscalPeriod(2022, 1), include_pandemic=False) == 0.0
    assert qoq_estimation_weight(FiscalPeriod(2022, 2), include_pandemic=False) == 1.0


def test_geo_mean_normalize_and_psd() -> None:
    norms = _geo_mean_normalize([0.9, 1.1, 1.0, 1.0])
    geo = math.exp(sum(math.log(v) for v in norms) / 4.0)
    assert abs(geo - 1.0) < 1e-12
    bad = np.array([[1.0, 0.9, 0.9], [0.9, 1.0, 0.9], [0.9, 0.9, 1.0]])
    # Make non-PSD by pushing an off-diagonal.
    bad[0, 1] = bad[1, 0] = 0.99
    bad[0, 2] = bad[2, 0] = 0.99
    bad[1, 2] = bad[2, 1] = 0.99
    psd = nearest_psd(bad)
    assert float(np.min(np.linalg.eigvalsh(psd))) >= -1e-10


def test_shock_scales_round_trip_simulate() -> None:
    payload = _load(ARTIFACTS[0])
    params = {k: float(v) for k, v in payload["pooled"]["values"].items()}
    fixture = load_fixture(required_fixture_paths()[0])
    result = simulate(
        VisaModel(),
        to_starting_state(fixture),
        params,
        origin=FiscalPeriod(fixture.fiscal_year, fixture.fiscal_quarter),
        seed=7,
        n_paths=64,
        n_quarters=4,
    )
    assert result.metrics["net_revenue"].shape == (64, 4)
    assert np.all(np.isfinite(result.metrics["net_revenue"]))


def test_synthetic_growth_recovery() -> None:
    """Closed-form: with unit seasonals, model YoY CD growth equals the annual parameter."""
    from longaeva_app.companies.visa.calibration import _run_four_quarters, _synthetic_unit_state

    params = {spec.name: float(spec.default) for spec in VISA_PARAMETERS}
    params["payments_volume_growth"] = 0.08
    for q in range(1, 5):
        params[f"activity_seasonal_q{q}"] = 1.0
    implied = _run_four_quarters(_synthetic_unit_state(params), params, FiscalPeriod(2023, 1))
    assert abs(implied["pv_cd_yoy"] - 0.08) < 1e-9


@pytest.mark.db
def test_persist_calibrated_verifies(db_session: Session) -> None:
    payload = _load(ARTIFACTS[0])
    pooled = payload["pooled"]
    create = ParameterSetCreate.model_validate(
        {
            "company": pooled["company"],
            "cutoff_ts": pooled["cutoff_ts"],
            "values": pooled["values"],
            "ranges": pooled["ranges"],
            "evidence_links": pooled["evidence_links"],
            "assumption_flags": pooled["assumption_flags"],
        }
    )
    member = MemberFit(
        name="full_history",
        window_start="FY2018Q2",
        window_end="FY2024Q3",
        values=dict(create.values),
        ranges={k: list(v) for k, v in create.ranges.items()},
        evidence_ids={k: [str(x) for x in create.evidence_links[k].observation_ids] for k in create.values},
        assumption_flags={k: bool(v) for k, v in create.assumption_flags.items()},
        rationales={},
        residuals={},
        n_obs={},
    )
    result = CalibrationResult(
        origin_date="2024-07-23",
        origin_label="FY2024Q3",
        cutoff_ts=parse_aware_utc(pooled["cutoff_ts"]),
        members=[member],
        weights={"full_history": 1.0},
        pooled=create,
        evidence_index={},
        exclusions=[],
        pandemic_included={},
        sensitivity=[],
        result_hash=payload["result_hash"],
    )
    param_set, scenario = persist_calibrated(result, db_session)
    db_session.commit()
    verified = verify_parameter_set(param_set, run_cutoff=result.cutoff_ts, company="visa")
    assert verified.computed_content_hash() == create.computed_content_hash()
    assert scenario.name == "calibrated"
    # Evidence links round-trip.
    link = ParameterEvidence.model_validate(param_set.evidence_links["payments_volume_growth"])
    assert all(isinstance(UUID(str(x)), UUID) for x in link.observation_ids)
