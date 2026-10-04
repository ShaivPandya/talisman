"""Visa interventions: conserved mix shift, spend reduction, and shared draws (LON-22)."""

from __future__ import annotations

import numpy as np
import pytest
from stub_company import StubCompany

from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.interventions import EMPTY_INTERVENTIONS_HASH, interventions_content_hash
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.companies.visa.starting_state import load_fixture, required_fixture_paths, to_starting_state
from longaeva_app.engine.outputs import canonical_outputs_hash
from longaeva_app.engine.runner import simulate

# No-intervention path, fixture visa_2024-07-23, defaults, seed 7, 32 paths, 4 quarters.
# The host digest matches the hash captured before the intervention hook existed.
# The container digest is the same run under OpenBLAS; bit identity is per BLAS,
# matching the replay note in docs/runs-and-replay.md.
PINNED_HASHES = frozenset(
    {
        "817b29e87c601a3224621f1623c4fa42fc301aec0cc24f6409bc2476650ad11d",
        "97ec2200af52bed47e54ec0a031d76002227bf776cd1032218534e48b1049bba",
    }
)


def _default_start() -> dict[str, float]:
    fixture = load_fixture(required_fixture_paths()[0])
    return dict(to_starting_state(fixture))


def test_empty_intervention_hash_matches_migration_backfill() -> None:
    assert interventions_content_hash(()) == EMPTY_INTERVENTIONS_HASH


def test_no_intervention_outputs_hash_is_unchanged() -> None:
    model = VisaModel()
    fixture = load_fixture(required_fixture_paths()[0])
    result = simulate(
        model,
        to_starting_state(fixture),
        model.default_parameters(),
        origin=FiscalPeriod(fixture.fiscal_year, fixture.fiscal_quarter),
        seed=7,
        n_paths=32,
        n_quarters=4,
    )
    empty = simulate(
        model,
        to_starting_state(fixture),
        model.default_parameters(),
        origin=FiscalPeriod(fixture.fiscal_year, fixture.fiscal_quarter),
        seed=7,
        n_paths=32,
        n_quarters=4,
        interventions=[],
    )
    assert canonical_outputs_hash(result) in PINNED_HASHES
    assert canonical_outputs_hash(empty) == canonical_outputs_hash(result)
    assert np.array_equal(empty.metrics["net_revenue"], result.metrics["net_revenue"])


def test_mix_shift_conserves_total_payments_volume() -> None:
    model = VisaModel()
    start = _default_start()
    params = model.default_parameters()
    origin = FiscalPeriod(2024, 3)
    baseline = simulate(model, start, params, origin=origin, seed=7, n_paths=64, n_quarters=4)
    shifted = simulate(
        model,
        start,
        params,
        origin=origin,
        seed=7,
        n_paths=64,
        n_quarters=4,
        interventions=[{"type": "mix_shift_conserving_total", "cross_border_change": -0.10}],
    )
    assert np.array_equal(
        shifted.metrics["payments_volume_nominal_us"],
        baseline.metrics["payments_volume_nominal_us"],
    )
    total = shifted.metrics["domestic_payments_volume"] + shifted.metrics["cross_border_ex_intra_europe_volume"]
    assert np.allclose(total, shifted.metrics["payments_volume_nominal_us"])
    assert not np.allclose(
        shifted.metrics["cross_border_ex_intra_europe_volume"],
        baseline.metrics["cross_border_ex_intra_europe_volume"],
    )
    assert np.array_equal(shifted.draws, baseline.draws)


def test_spend_reduction_scales_volume_and_lags_service_revenue() -> None:
    model = VisaModel()
    start = _default_start()
    params = model.default_parameters()
    origin = FiscalPeriod(2024, 3)
    reduction = 0.05
    baseline = simulate(model, start, params, origin=origin, seed=11, n_paths=32, n_quarters=4)
    reduced = simulate(
        model,
        start,
        params,
        origin=origin,
        seed=11,
        n_paths=32,
        n_quarters=4,
        interventions=[{"type": "total_spend_reduction", "reduction": reduction}],
    )
    ratio = reduced.metrics["payments_volume_nominal_us"] / baseline.metrics["payments_volume_nominal_us"]
    assert np.allclose(ratio, 1.0 - reduction, rtol=1e-12, atol=0.0)
    assert np.array_equal(reduced.metrics["service_revenue"][:, 0], baseline.metrics["service_revenue"][:, 0])
    assert np.all(reduced.metrics["service_revenue"][:, 1] < baseline.metrics["service_revenue"][:, 1])
    assert np.all(
        reduced.metrics["international_transaction_revenue"][:, 0]
        < baseline.metrics["international_transaction_revenue"][:, 0]
    )
    assert np.array_equal(reduced.draws, baseline.draws)

    immediate = simulate(
        model,
        start,
        params,
        origin=origin,
        seed=11,
        n_paths=32,
        n_quarters=4,
        switches={"service_lag": False},
        interventions=[{"type": "total_spend_reduction", "reduction": reduction}],
    )
    unlagged = simulate(
        model,
        start,
        params,
        origin=origin,
        seed=11,
        n_paths=32,
        n_quarters=4,
        switches={"service_lag": False},
    )
    assert np.all(immediate.metrics["service_revenue"][:, 0] < unlagged.metrics["service_revenue"][:, 0])


def test_shared_seed_baseline_paths_match() -> None:
    model = VisaModel()
    start = _default_start()
    params = model.default_parameters()
    origin = FiscalPeriod(2024, 3)
    first = simulate(model, start, params, origin=origin, seed=4, n_paths=16, n_quarters=4)
    second = simulate(model, start, params, origin=origin, seed=4, n_paths=16, n_quarters=4)
    assert np.array_equal(first.metrics["net_revenue"], second.metrics["net_revenue"])
    assert np.array_equal(first.draws, second.draws)


def test_invalid_interventions_and_horizon_are_rejected() -> None:
    model = VisaModel()
    start = _default_start()
    params = model.default_parameters()
    with pytest.raises(ValueError, match="invalid intervention"):
        simulate(
            model,
            start,
            params,
            origin=FiscalPeriod(2024, 3),
            seed=1,
            n_paths=4,
            n_quarters=2,
            interventions=[{"type": "mix_shift_conserving_total"}],
        )
    with pytest.raises(ValueError, match="start_quarter"):
        simulate(
            model,
            start,
            params,
            origin=FiscalPeriod(2024, 3),
            seed=1,
            n_paths=4,
            n_quarters=2,
            interventions=[{"type": "total_spend_reduction", "reduction": 0.05, "start_quarter": 3}],
        )
    params["cross_border_share_at_origin"] = 0.30
    with pytest.raises(ValueError, match="outside"):
        simulate(
            model,
            start,
            params,
            origin=FiscalPeriod(2024, 3),
            seed=1,
            n_paths=4,
            n_quarters=2,
            interventions=[{"type": "mix_shift_conserving_total", "cross_border_change": 3.0}],
        )


def test_stub_company_refuses_interventions() -> None:
    stub = StubCompany()
    with pytest.raises(ValueError, match="does not accept interventions"):
        stub.parse_interventions([{"type": "mix_shift_conserving_total", "cross_border_change": -0.1}])
