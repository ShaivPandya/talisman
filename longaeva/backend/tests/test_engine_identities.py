"""Visa engine identity, lag, ablation and teaching-fee tests."""

from __future__ import annotations

import ast
import time
from pathlib import Path

import numpy as np
import pytest

from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.companies.visa.parameters import FREE_PARAMETER_NAMES, VISA_PARAMETERS
from longaeva_app.companies.visa.starting_state import load_fixture, required_fixture_paths, to_starting_state
from longaeva_app.companies.visa.state import BILLIONS_TO_MILLIONS, synthetic_starting_state
from longaeva_app.companies.visa.transitions import annual_to_quarterly, transition_quarter
from longaeva_app.engine.runner import simulate
from longaeva_app.engine.sampler import correlate_draws, draw_factors, factor_root

PACKAGE_BACKEND = Path(__file__).resolve().parents[1]
VISA_DIR = PACKAGE_BACKEND / "longaeva_app" / "companies" / "visa"
ENGINE_DIR = PACKAGE_BACKEND / "longaeva_app" / "engine"

TEACHING_CONSTANTS = {0.01, 0.03}


def _random_params(rng: np.random.Generator, model: VisaModel) -> dict[str, float] | None:
    """Draw a parameter set inside ranges; return None if the macro block is not PSD."""
    values: dict[str, float] = {}
    for spec in model.parameters:
        values[spec.name] = float(rng.uniform(spec.lower, spec.upper))
    # Retry correlations a few times for PSD.
    for _ in range(20):
        values["corr_demand_travel"] = float(rng.uniform(-0.8, 0.8))
        values["corr_demand_fx"] = float(rng.uniform(-0.8, 0.8))
        values["corr_travel_fx"] = float(rng.uniform(-0.8, 0.8))
        if not model.validate_parameters(values):
            return values
    return None


SWITCH_COMBOS = (
    {"service_lag": True, "pool_mix": False},
    {"service_lag": True, "pool_mix": True},
    {"service_lag": False, "pool_mix": False},
    {"service_lag": False, "pool_mix": True},
)


@pytest.mark.parametrize("switches", SWITCH_COMBOS)
def test_randomized_identities_and_bounds(switches: dict[str, bool]) -> None:
    model = VisaModel()
    rng = np.random.default_rng(20261002)
    successes = 0
    for _ in range(200):
        params = _random_params(rng, model)
        if params is None:
            continue
        start = synthetic_starting_state(
            payments_volume_nominal_us=float(rng.uniform(2000.0, 5000.0)),
            service_revenue=float(rng.uniform(2000.0, 6000.0)),
            data_processing_revenue=float(rng.uniform(2000.0, 6000.0)),
            international_transaction_revenue=float(rng.uniform(1000.0, 5000.0)),
            other_revenue=float(rng.uniform(200.0, 2000.0)),
            processed_transactions_count=float(rng.uniform(40000.0, 80000.0)),
            incentive_intensity=float(rng.uniform(0.15, 0.4)),
            operating_expenses_ex_special_items=float(rng.uniform(1500.0, 5000.0)),
        )
        seed = int(rng.integers(0, 10_000))
        result = simulate(
            model,
            start,
            params,
            origin=FiscalPeriod(2024, 3),
            seed=seed,
            n_paths=32,
            n_quarters=4,
            switches=switches,
        )
        for name, arr in result.metrics.items():
            assert np.all(np.isfinite(arr)), name
        assert np.all(result.metrics["net_revenue"] > 0.0)
        assert np.all(result.metrics["payments_volume_nominal_us"] > 0.0)
        assert np.all(result.states["cross_border_share"] > 0.0)
        assert np.all(result.states["cross_border_share"] < 1.0)
        assert np.all(result.states["incentive_intensity"] > 0.0)
        assert np.all(result.states["incentive_intensity"] < 1.0)
        successes += 1
    assert successes >= 150


def test_service_lag_timing() -> None:
    model = VisaModel()
    params = model.default_parameters()
    # Kill all vols except demand so the injected demand shock is unambiguous.
    for key in ("travel_vol", "fx_vol", "pricing_vol", "incentive_vol", "cost_vol"):
        params[key] = 0.0
    params["demand_vol"] = 0.05
    start = synthetic_starting_state()
    n_paths = 8
    n_quarters = 4
    n_factors = len(model.factors)
    raw = np.zeros((n_paths, n_quarters, n_factors), dtype=np.float64)
    # Inject a demand shock in quarter index 1 (second simulated quarter).
    demand_idx = model.factors.index("demand")
    raw[:, 1, demand_idx] = 3.0
    draws = correlate_draws(raw, factor_root(model.factor_correlation(params)))

    lag_on = simulate(
        model,
        start,
        params,
        origin=FiscalPeriod(2024, 3),
        seed=0,
        n_paths=n_paths,
        n_quarters=n_quarters,
        switches={"service_lag": True, "pool_mix": False},
        draws=draws,
    )
    # Baseline with zero shocks.
    zero = simulate(
        model,
        start,
        params,
        origin=FiscalPeriod(2024, 3),
        seed=0,
        n_paths=n_paths,
        n_quarters=n_quarters,
        switches={"service_lag": True, "pool_mix": False},
        draws=np.zeros_like(draws),
    )
    # Quarter index 1 (2nd simulated): service unchanged under lag; PV moved.
    assert np.allclose(lag_on.metrics["service_revenue"][:, 1], zero.metrics["service_revenue"][:, 1])
    assert not np.allclose(
        lag_on.metrics["payments_volume_nominal_us"][:, 1],
        zero.metrics["payments_volume_nominal_us"][:, 1],
    )
    # Quarter index 2: service moves with the lagged PV shock.
    assert not np.allclose(lag_on.metrics["service_revenue"][:, 2], zero.metrics["service_revenue"][:, 2])

    lag_off = simulate(
        model,
        start,
        params,
        origin=FiscalPeriod(2024, 3),
        seed=0,
        n_paths=n_paths,
        n_quarters=n_quarters,
        switches={"service_lag": False, "pool_mix": False},
        draws=draws,
    )
    # Without lag, service in quarter index 1 moves immediately.
    assert not np.allclose(lag_off.metrics["service_revenue"][:, 1], zero.metrics["service_revenue"][:, 1])


def test_mr05_travel_conserves_total_pv() -> None:
    model = VisaModel()
    params = model.default_parameters()
    for key in ("demand_vol", "fx_vol", "pricing_vol", "incentive_vol", "cost_vol"):
        params[key] = 0.0
    params["travel_vol"] = 0.08
    start = synthetic_starting_state()
    n_paths, n_quarters = 16, 4
    raw_a = draw_factors(n_paths=n_paths, n_quarters=n_quarters, n_factors=len(model.factors), seed=21)
    raw_b = raw_a.copy()
    travel_idx = model.factors.index("travel")
    raw_b[:, :, travel_idx] = -raw_a[:, :, travel_idx]
    root = factor_root(model.factor_correlation(params))
    a = simulate(
        model,
        start,
        params,
        origin=FiscalPeriod(2024, 3),
        seed=0,
        n_paths=n_paths,
        n_quarters=n_quarters,
        draws=correlate_draws(raw_a, root),
    )
    b = simulate(
        model,
        start,
        params,
        origin=FiscalPeriod(2024, 3),
        seed=0,
        n_paths=n_paths,
        n_quarters=n_quarters,
        draws=correlate_draws(raw_b, root),
    )
    assert np.array_equal(a.metrics["payments_volume_nominal_us"], b.metrics["payments_volume_nominal_us"])
    # Cross-border and domestic move in opposite directions somewhere.
    assert not np.allclose(
        a.metrics["cross_border_ex_intra_europe_volume"],
        b.metrics["cross_border_ex_intra_europe_volume"],
    )
    assert not np.allclose(a.metrics["domestic_payments_volume"], b.metrics["domestic_payments_volume"])


def test_pool_mix_freezes_share_and_ignores_travel() -> None:
    model = VisaModel()
    params = model.default_parameters()
    for key in ("demand_vol", "fx_vol", "pricing_vol", "incentive_vol", "cost_vol"):
        params[key] = 0.0
    params["travel_vol"] = 0.1
    start = synthetic_starting_state()
    n_paths, n_quarters = 16, 4
    raw = draw_factors(n_paths=n_paths, n_quarters=n_quarters, n_factors=len(model.factors), seed=33)
    travel_idx = model.factors.index("travel")
    raw[:, :, travel_idx] = 2.5
    draws = correlate_draws(raw, factor_root(model.factor_correlation(params)))
    pooled = simulate(
        model,
        start,
        params,
        origin=FiscalPeriod(2024, 3),
        seed=0,
        n_paths=n_paths,
        n_quarters=n_quarters,
        switches={"service_lag": True, "pool_mix": True},
        draws=draws,
    )
    share0 = float(params["cross_border_share_at_origin"])
    assert np.allclose(pooled.states["cross_border_share"], share0)
    zero = simulate(
        model,
        start,
        params,
        origin=FiscalPeriod(2024, 3),
        seed=0,
        n_paths=n_paths,
        n_quarters=n_quarters,
        switches={"service_lag": True, "pool_mix": True},
        draws=np.zeros_like(draws),
    )
    for name in pooled.metrics:
        assert np.allclose(pooled.metrics[name], zero.metrics[name]), name


def test_hand_walked_quarter() -> None:
    """One quarter with chosen shocks, checked against written arithmetic."""
    model = VisaModel()
    params = model.default_parameters()
    # Neutralize seasons and most dynamics.
    for q in (1, 2, 3, 4):
        params[f"activity_seasonal_q{q}"] = 1.0
        params[f"cross_border_seasonal_q{q}"] = 1.0
        params[f"opex_seasonal_q{q}"] = 1.0
    params["payments_volume_growth"] = 0.0
    params["cross_border_growth_premium"] = 0.0
    params["transactions_growth_premium"] = 0.0
    params["service_yield_drift"] = 0.0
    params["data_processing_yield_drift"] = 0.0
    params["international_yield_drift"] = 0.0
    params["incentive_intensity_drift"] = 0.0
    params["opex_growth"] = 0.0
    params["other_revenue_growth"] = 0.0
    params["demand_vol"] = 0.04
    params["travel_vol"] = 0.0
    params["fx_vol"] = 0.02
    params["pricing_vol"] = 0.0
    params["incentive_vol"] = 0.0
    params["cost_vol"] = 0.0
    params["cross_border_share_at_origin"] = 0.2
    params["international_fx_sensitivity"] = 0.0

    start = synthetic_starting_state(
        payments_volume_nominal_us=1000.0,
        service_revenue=1250.0,
        data_processing_revenue=750.0,
        international_transaction_revenue=400.0,
        other_revenue=100.0,
        processed_transactions_count=50000.0,
        incentive_intensity=0.25,
        operating_expenses_ex_special_items=500.0,
        prior_quarter_pv_billions=1000.0,
    )
    state = model.initial_state(start, params, n_paths=1)
    # demand=1, fx=1 → g_cd = 0.04, g_nom = 0.06
    shocks = {
        "demand": np.array([1.0]),
        "travel": np.array([0.0]),
        "fx": np.array([1.0]),
        "pricing": np.array([0.0]),
        "incentives": np.array([0.0]),
        "costs": np.array([0.0]),
    }
    step = transition_quarter(state, shocks, params, {"service_lag": True, "pool_mix": False}, FiscalPeriod(2024, 4))

    g_cd = 0.04
    g_nom = 0.06
    pv_new = 1000.0 * (1.0 + g_nom)
    assert float(step.state["payments_volume_nominal_us"][0]) == pytest.approx(pv_new)
    assert float(step.state["payments_volume_index_constant"][0]) == pytest.approx(100.0 * (1.0 + g_cd))
    assert float(step.state["cross_border_share"][0]) == pytest.approx(0.2)  # premium 0, travel 0

    yield_service = 1250.0 / (1000.0 * BILLIONS_TO_MILLIONS)
    service = yield_service * 1000.0 * BILLIONS_TO_MILLIONS
    assert float(step.metrics["service_revenue"][0]) == pytest.approx(service)
    assert float(step.metrics["service_revenue"][0]) == pytest.approx(1250.0)

    txn_new = 50000.0 * (1.0 + g_cd)
    yield_dp = 750.0 / 50000.0
    assert float(step.metrics["data_processing_revenue"][0]) == pytest.approx(yield_dp * txn_new)

    yield_intl = 400.0 / (0.2 * 1000.0 * BILLIONS_TO_MILLIONS)
    intl = yield_intl * (0.2 * pv_new * BILLIONS_TO_MILLIONS)
    assert float(step.metrics["international_transaction_revenue"][0]) == pytest.approx(intl)

    other = 100.0
    gross = service + yield_dp * txn_new + intl + other
    incentives = 0.25 * gross
    net = gross - incentives
    assert float(step.metrics["net_revenue"][0]) == pytest.approx(net)
    assert float(step.metrics["operating_profit_ex_special_items"][0]) == pytest.approx(net - 500.0)
    assert float(step.metrics["domestic_payments_volume"][0]) + float(
        step.metrics["cross_border_ex_intra_europe_volume"][0]
    ) == pytest.approx(pv_new)


def test_lon3_fixture_smoke_service_lag() -> None:
    model = VisaModel()
    params = model.default_parameters()
    for key in (
        "payments_volume_growth",
        "cross_border_growth_premium",
        "transactions_growth_premium",
        "service_yield_drift",
        "data_processing_yield_drift",
        "international_yield_drift",
        "incentive_intensity_drift",
        "opex_growth",
        "other_revenue_growth",
        "demand_vol",
        "travel_vol",
        "fx_vol",
        "pricing_vol",
        "incentive_vol",
        "cost_vol",
    ):
        params[key] = 0.0
    fixture = load_fixture(required_fixture_paths()[0])
    start = to_starting_state(fixture)
    result = simulate(
        model,
        start,
        params,
        origin=FiscalPeriod(fixture.fiscal_year, fixture.fiscal_quarter),
        seed=0,
        n_paths=4,
        n_quarters=1,
        switches={"service_lag": True, "pool_mix": False},
        draws=np.zeros((4, 1, len(model.factors)), dtype=np.float64),
    )
    expected = (
        float(start["effective_yield_service"]) * float(start["payments_volume_nominal_us"]) * BILLIONS_TO_MILLIONS
    )
    assert np.allclose(result.metrics["service_revenue"][:, 0], expected)


def test_share_insensitivity_of_international_revenue() -> None:
    model = VisaModel()
    base = model.default_parameters()
    for key in (
        "cross_border_growth_premium",
        "demand_vol",
        "travel_vol",
        "fx_vol",
        "pricing_vol",
        "incentive_vol",
        "cost_vol",
        "international_fx_sensitivity",
    ):
        base[key] = 0.0
    start = synthetic_starting_state()
    means: list[float] = []
    for share in (0.05, 0.2, 0.35):
        params = dict(base)
        params["cross_border_share_at_origin"] = share
        result = simulate(
            model,
            start,
            params,
            origin=FiscalPeriod(2024, 3),
            seed=0,
            n_paths=64,
            n_quarters=1,
            draws=np.zeros((64, 1, len(model.factors)), dtype=np.float64),
        )
        means.append(float(np.mean(result.metrics["international_transaction_revenue"][:, 0])))
    mid = means[1]
    for value in means:
        assert abs(value - mid) / mid < 0.01


def test_teaching_fee_ast_scan() -> None:
    offenders: list[str] = []
    for root in (VISA_DIR, ENGINE_DIR):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, float)
                    and node.value in TEACHING_CONSTANTS
                ):
                    offenders.append(f"{path.relative_to(PACKAGE_BACKEND)}:{node.lineno}:{node.value}")
    assert not offenders, offenders
    # No yield-level / fee parameter names.
    forbidden_names = {"domestic_fee", "cross_border_fee", "teaching_fee", "fee_per_100"}
    param_names = {p.name for p in VISA_PARAMETERS}
    assert not (param_names & forbidden_names)
    assert len(FREE_PARAMETER_NAMES) == 8


def test_timing_5000_paths_under_60s() -> None:
    model = VisaModel()
    start = synthetic_starting_state()
    params = model.default_parameters()
    t0 = time.perf_counter()
    simulate(model, start, params, origin=FiscalPeriod(2024, 3), seed=1, n_paths=5000, n_quarters=4)
    elapsed = time.perf_counter() - t0
    assert elapsed <= 60.0, f"5000×4 took {elapsed:.2f}s"


def test_annual_to_quarterly_identity() -> None:
    assert annual_to_quarterly(0.0) == pytest.approx(0.0)
    q = annual_to_quarterly(0.08)
    assert (1.0 + q) ** 4 == pytest.approx(1.08)
