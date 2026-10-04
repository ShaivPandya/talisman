"""Driver transforms and actuals loader tests (LON-27)."""

from __future__ import annotations

import numpy as np

from longaeva_app.evaluation.origins import load_evaluation_origins
from longaeva_app.evaluation.targets import (
    DriverHistory,
    annualized_to_quarterly,
    build_driver_history,
    forecast_driver_yoy,
    load_actuals,
    q4_level_yoy,
)


def test_annualized_to_quarterly_roundtrip() -> None:
    g_q = 0.02
    ann = (1.0 + g_q) ** 4 - 1.0
    assert abs(float(annualized_to_quarterly(ann)) - g_q) < 1e-12


def test_transactions_exact() -> None:
    history = DriverHistory(txn_year_ago=50_000.0)
    paths = {
        "processed_transactions_count": np.array([[55_000.0], [60_000.0]], dtype=np.float64),
        "payments_volume_growth_constant": np.zeros((2, 1)),
        "cross_border_ex_intra_europe_growth_constant": np.zeros((2, 1)),
    }
    out = forecast_driver_yoy(paths, history)
    samples = out["processed_transactions_growth"]
    assert samples is not None
    assert abs(float(samples[0]) - 0.1) < 1e-12
    assert abs(float(samples[1]) - 0.2) < 1e-12


def test_payments_volume_chain_hand_computation() -> None:
    # g_q = 0.05, g_q1 quarterly = 0.01, g_ym3 = 0.04 → (1.05*1.01/1.04)-1
    history = DriverHistory(
        pv_growth_q=0.05,
        pv_growth_q_minus_3_nominal=0.04,
        pv_fx_gap_q_minus_3=0.0,
        txn_year_ago=1.0,
    )
    eng_ann = (1.01) ** 4 - 1.0
    paths = {
        "processed_transactions_count": np.ones((1, 1)),
        "payments_volume_growth_constant": np.array([[eng_ann]], dtype=np.float64),
        "cross_border_ex_intra_europe_growth_constant": np.zeros((1, 1)),
    }
    out = forecast_driver_yoy(paths, history)
    samples = out["payments_volume_growth_constant"]
    assert samples is not None
    expected = (1.05 * 1.01 / 1.04) - 1.0
    assert abs(float(samples[0]) - expected) < 1e-12


def test_cross_border_zero_shock_equals_last_reported() -> None:
    # Persistence: model QoQ(q-3) and simulated QoQ(q+1) both equal the quarterly
    # rate implied by the last reported YoY → forecast YoY equals that last print.
    last = 0.11
    g_q = float(annualized_to_quarterly(last))
    history = DriverHistory(
        cb_growth_q=last,
        cb_growth_q_minus_3_model=g_q,
        txn_year_ago=1.0,
        pv_growth_q=0.05,
        pv_growth_q_minus_3_nominal=0.05,
        pv_fx_gap_q_minus_3=0.0,
    )
    eng_ann = (1.0 + g_q) ** 4 - 1.0
    paths = {
        "processed_transactions_count": np.ones((1, 1)),
        "payments_volume_growth_constant": np.array([[eng_ann]], dtype=np.float64),
        "cross_border_ex_intra_europe_growth_constant": np.array([[eng_ann]], dtype=np.float64),
    }
    out = forecast_driver_yoy(paths, history)
    samples = out["cross_border_ex_intra_europe_growth_constant"]
    assert samples is not None
    assert abs(float(samples[0]) - last) < 1e-9


def test_q4_level_yoy_exact() -> None:
    samples = q4_level_yoy(np.array([110.0, 120.0]), 100.0)
    assert abs(float(samples[0]) - 0.1) < 1e-12
    assert abs(float(samples[1]) - 0.2) < 1e-12


def test_actuals_loader_first_print_after_cutoff() -> None:
    origin = next(o for o in load_evaluation_origins() if o.origin_date == "2024-07-23")
    actuals = load_actuals(origin)
    assert "net_revenue" in actuals
    assert "operating_profit_ex_special_items" in actuals
    assert actuals["net_revenue"].publication_ts > origin.cutoff_ts
    assert actuals["net_revenue"].accession == origin.target_release_accession


def test_fy2022q2_skips_pv_driver() -> None:
    origin = next(o for o in load_evaluation_origins() if o.label == "FY2022Q2")
    history = build_driver_history(origin)
    assert "payments_volume_growth_constant" in history.skip_reasons
