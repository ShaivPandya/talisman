"""Engine sampler, runner and summary tests."""

from __future__ import annotations

import numpy as np
import pytest
from stub_company import StubCompany

from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.companies.visa.state import synthetic_starting_state
from longaeva_app.engine.runner import simulate
from longaeva_app.engine.sampler import correlate_draws, draw_factors, factor_root
from longaeva_app.engine.summary import summarize_metric, summarize_paths


def test_draw_factors_prefix_property() -> None:
    a = draw_factors(n_paths=8, n_quarters=4, n_factors=6, seed=7)
    b = draw_factors(n_paths=32, n_quarters=4, n_factors=6, seed=7)
    assert np.array_equal(a, b[:8])


def test_draw_factors_different_seeds_differ() -> None:
    a = draw_factors(n_paths=16, n_quarters=2, n_factors=3, seed=1)
    b = draw_factors(n_paths=16, n_quarters=2, n_factors=3, seed=2)
    assert not np.array_equal(a, b)


def test_factor_root_rejects_non_psd() -> None:
    bad = np.array([[1.0, 0.9, 0.9], [0.9, 1.0, 0.9], [0.9, 0.9, 1.0]], dtype=np.float64)
    # Make it non-PSD by setting an impossible correlation pattern.
    bad[0, 1] = bad[1, 0] = 0.99
    bad[0, 2] = bad[2, 0] = -0.99
    bad[1, 2] = bad[2, 1] = 0.99
    with pytest.raises(ValueError, match="positive-semidefinite"):
        factor_root(bad)


def test_factor_root_singular_psd() -> None:
    # Rank-1 PSD correlation (all factors identical).
    corr = np.ones((3, 3), dtype=np.float64)
    root = factor_root(corr)
    reconstructed = root @ root.T
    assert np.allclose(reconstructed, corr, atol=1e-10)


def test_correlate_recovers_correlation_at_large_n() -> None:
    corr = np.array([[1.0, 0.4, 0.2], [0.4, 1.0, 0.15], [0.2, 0.15, 1.0]], dtype=np.float64)
    root = factor_root(corr)
    raw = draw_factors(n_paths=20000, n_quarters=1, n_factors=3, seed=99)
    z = correlate_draws(raw, root)[:, 0, :]
    sample = np.corrcoef(z.T)
    assert np.allclose(sample, corr, atol=0.03)


def test_simulate_same_seed_bit_identical() -> None:
    model = VisaModel()
    params = model.default_parameters()
    start = synthetic_starting_state()
    a = simulate(model, start, params, origin=FiscalPeriod(2024, 3), seed=42, n_paths=128, n_quarters=4)
    b = simulate(model, start, params, origin=FiscalPeriod(2024, 3), seed=42, n_paths=128, n_quarters=4)
    for key in a.metrics:
        assert np.array_equal(a.metrics[key], b.metrics[key])
    assert np.array_equal(a.draws, b.draws)


def test_simulate_prefix_property() -> None:
    model = VisaModel()
    params = model.default_parameters()
    start = synthetic_starting_state()
    small = simulate(model, start, params, origin=FiscalPeriod(2024, 3), seed=11, n_paths=16, n_quarters=4)
    large = simulate(model, start, params, origin=FiscalPeriod(2024, 3), seed=11, n_paths=64, n_quarters=4)
    for key in small.metrics:
        assert np.allclose(small.metrics[key], large.metrics[key][:16], rtol=0, atol=0)


def test_simulate_rejects_unknown_switch() -> None:
    model = VisaModel()
    with pytest.raises(ValueError, match="unknown switches"):
        simulate(
            model,
            synthetic_starting_state(),
            model.default_parameters(),
            origin=FiscalPeriod(2024, 3),
            seed=0,
            n_paths=4,
            switches={"not_a_switch": True},
        )


def test_simulate_rejects_bad_params() -> None:
    model = VisaModel()
    params = model.default_parameters()
    params["payments_volume_growth"] = 99.0
    with pytest.raises(ValueError, match="invalid parameters"):
        simulate(
            model,
            synthetic_starting_state(),
            params,
            origin=FiscalPeriod(2024, 3),
            seed=0,
            n_paths=4,
        )


def test_simulate_rejects_non_psd_correlation() -> None:
    model = VisaModel()
    params = model.default_parameters()
    params["corr_demand_travel"] = 0.99
    params["corr_demand_fx"] = -0.99
    params["corr_travel_fx"] = 0.99
    with pytest.raises(ValueError, match="positive-semidefinite|invalid parameters"):
        simulate(
            model,
            synthetic_starting_state(),
            params,
            origin=FiscalPeriod(2024, 3),
            seed=0,
            n_paths=4,
        )


def test_stub_company_through_runner() -> None:
    model = StubCompany()
    params = model.default_parameters()
    start = {"activity": 100.0, "opex": 10.0}
    result = simulate(model, start, params, origin=FiscalPeriod(2024, 1), seed=3, n_paths=32, n_quarters=4)
    assert result.metrics["net_revenue"].shape == (32, 4)
    assert len(result.periods) == 4


def test_summary_keys_monotone_and_se() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(loc=100.0, scale=10.0, size=5000)
    summary = summarize_metric(x, metric="net_revenue", quarter_index=0)
    assert summary.std_error == pytest.approx(summary.std / np.sqrt(5000))
    keys = ["0.05", "0.1", "0.25", "0.5", "0.75", "0.9", "0.95"]
    assert list(summary.quantiles) == keys
    values = [summary.quantiles[k] for k in keys]
    assert values == sorted(values)


def test_summarize_paths_covers_quarters() -> None:
    model = VisaModel()
    result = simulate(
        model,
        synthetic_starting_state(),
        model.default_parameters(),
        origin=FiscalPeriod(2024, 3),
        seed=5,
        n_paths=64,
        n_quarters=4,
    )
    summaries = summarize_paths(result, metrics=("net_revenue",))
    assert len(summaries) == 4
    assert {s.quarter_index for s in summaries} == {0, 1, 2, 3}
