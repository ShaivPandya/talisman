"""Visa quarterly transition rules (LON-19 / MR-02).

Numbered rule list (mirrored in ``docs/model-spec.md``):

1. Read the quarter's factor draws (company code never generates randomness).
2. Update activity (constant-dollar PV, nominal PV, transactions, cross-border share).
3. Update pricing, incentives and costs (yields, intensity, other revenue, opex).
4. Category revenue (service lag / current; DP; international; other).
5. Client incentives = intensity × gross categories.
6. Net revenue = Σ categories − incentives.
7. Operating profit (ex special items) = net revenue − recurring opex.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

from longaeva_app.companies.base import FiscalPeriod, PathArrays, StepResult
from longaeva_app.companies.visa.interventions import (
    InterventionError,
    MixShiftConservingTotal,
    TotalSpendReduction,
    apply_level_shifts,
)
from longaeva_app.companies.visa.revenue import category_revenues, client_incentives, net_from_categories

FloatArray = npt.NDArray[np.floating]

FACTORS: tuple[str, ...] = ("demand", "travel", "fx", "pricing", "incentives", "costs")

_EPS = 1e-12
_SHARE_LO = 1e-6
_SHARE_HI = 1.0 - 1e-6


def annual_to_quarterly(annual_rate: float) -> float:
    """Convert an annual growth/drift rate to an equivalent quarterly rate."""
    return float((1.0 + annual_rate) ** 0.25 - 1.0)


def _logit(x: FloatArray) -> FloatArray:
    clipped = np.clip(x, _SHARE_LO, _SHARE_HI)
    return np.log(clipped / (1.0 - clipped))


def _sigmoid(z: FloatArray) -> FloatArray:
    return 1.0 / (1.0 + np.exp(-z))


def _seasonal_ratio(params: Mapping[str, float], prefix: str, quarter: int) -> float:
    """Return the geo-mean-normalized seasonal ratio for ``prefix`` and fiscal quarter."""
    raw = np.array(
        [
            float(params[f"{prefix}_q1"]),
            float(params[f"{prefix}_q2"]),
            float(params[f"{prefix}_q3"]),
            float(params[f"{prefix}_q4"]),
        ],
        dtype=np.float64,
    )
    if np.any(raw <= 0.0):
        raise ValueError(f"{prefix} seasonal ratios must be positive")
    geo = float(np.exp(np.mean(np.log(raw))))
    normalized = raw / geo
    return float(normalized[quarter - 1])


def _arr(state: PathArrays, key: str) -> FloatArray:
    return np.asarray(state[key], dtype=np.float64)


def _shock(shocks: PathArrays, name: str, n_paths: int) -> FloatArray:
    if name not in shocks:
        raise KeyError(f"missing factor shock: {name}")
    values = np.asarray(shocks[name], dtype=np.float64)
    if values.shape != (n_paths,):
        raise ValueError(f"shock {name} shape {values.shape} != ({n_paths},)")
    return values


def transition_quarter(
    state: PathArrays,
    shocks: PathArrays,
    params: Mapping[str, float],
    switches: Mapping[str, bool],
    period: FiscalPeriod,
    interventions: Sequence[Any] | None = None,
) -> StepResult:
    """Advance one fiscal quarter. Does not mutate ``state`` or ``shocks``.

    ``interventions`` are applied once, after the activity step, and only when
    non-empty. The empty path is the unshifted transition.
    """
    # 1. Factor draws
    n_paths = int(_arr(state, "payments_volume_nominal_us").shape[0])
    demand = _shock(shocks, "demand", n_paths)
    travel = _shock(shocks, "travel", n_paths)
    fx = _shock(shocks, "fx", n_paths)
    pricing = _shock(shocks, "pricing", n_paths)
    incentives_shock = _shock(shocks, "incentives", n_paths)
    costs = _shock(shocks, "costs", n_paths)

    service_lag = bool(switches.get("service_lag", True))
    pool_mix = bool(switches.get("pool_mix", False))
    active = tuple(interventions or ())

    pv_prior = _arr(state, "payments_volume_nominal_us")
    index_cd = _arr(state, "payments_volume_index_constant")
    share = _arr(state, "cross_border_share")
    txn = _arr(state, "processed_transactions_count")
    y_svc = _arr(state, "effective_yield_service")
    y_svc_cur = _arr(state, "effective_yield_service_current")
    y_dp = _arr(state, "effective_yield_data_processing")
    y_intl = _arr(state, "effective_yield_international")
    intensity = _arr(state, "incentive_intensity")
    other = _arr(state, "other_revenue")
    opex = _arr(state, "operating_expenses_ex_special_items")

    # 2. Update activity
    activity_seasonal = _seasonal_ratio(params, "activity_seasonal", period.quarter)
    cb_seasonal = _seasonal_ratio(params, "cross_border_seasonal", period.quarter)
    opex_seasonal = _seasonal_ratio(params, "opex_seasonal", period.quarter)

    g_pv_q = annual_to_quarterly(float(params["payments_volume_growth"]))
    g_cd = (1.0 + g_pv_q) * activity_seasonal - 1.0 + float(params["demand_vol"]) * demand
    g_nom = g_cd + float(params["fx_vol"]) * fx
    # Floor growth so levels stay positive under extreme shocks.
    g_cd = np.maximum(g_cd, -0.9)
    g_nom = np.maximum(g_nom, -0.9)

    pv_current = pv_prior * (1.0 + g_nom)
    index_cd_new = index_cd * (1.0 + g_cd)

    g_txn_prem_q = annual_to_quarterly(float(params["transactions_growth_premium"]))
    g_txn = g_cd + g_txn_prem_q
    g_txn = np.maximum(g_txn, -0.9)
    txn_new = txn * (1.0 + g_txn)

    # Travel draws are always consumed (read above) so paired runs stay aligned.
    if pool_mix:
        share_new = share.copy()
        g_cb = g_cd
    else:
        prem_q = annual_to_quarterly(float(params["cross_border_growth_premium"]))
        # Seasonal ratio scales the premium; travel shock adds to CB growth.
        g_cb = g_cd + prem_q * cb_seasonal + float(params["travel_vol"]) * travel
        g_cb = np.maximum(g_cb, -0.9)
        # Multiplicative share update exact for CB_new/PV_new; logit keeps (0,1).
        # share' = share * (1+g_cb)/(1+g_total) with g_total = g_cd (constant-dollar basis).
        ratio = (1.0 + g_cb) / np.maximum(1.0 + g_cd, _EPS)
        share_new = _sigmoid(_logit(share) + np.log(np.maximum(ratio, _EPS)))

    # Level shifts (LON-22). Skipped entirely when this quarter has no intervention,
    # so the unshifted arithmetic below is unchanged.
    if active:
        typed: list[MixShiftConservingTotal | TotalSpendReduction] = []
        for item in active:
            if not isinstance(item, (MixShiftConservingTotal, TotalSpendReduction)):
                raise InterventionError(f"transition received an unparsed intervention: {type(item).__name__}")
            typed.append(item)
        pv_current, index_cd_new, share_new = apply_level_shifts(
            payments_volume=pv_current,
            index_constant=index_cd_new,
            cross_border_share=share_new,
            interventions=typed,
        )

    # 3. Update pricing, incentives and costs
    svc_drift_q = annual_to_quarterly(float(params["service_yield_drift"]))
    dp_drift_q = annual_to_quarterly(float(params["data_processing_yield_drift"]))
    intl_drift_q = annual_to_quarterly(float(params["international_yield_drift"]))
    inc_drift_q = annual_to_quarterly(float(params["incentive_intensity_drift"]))
    other_drift_q = annual_to_quarterly(float(params["other_revenue_growth"]))
    opex_drift_q = annual_to_quarterly(float(params["opex_growth"]))

    pricing_factor = 1.0 + float(params["pricing_vol"]) * pricing
    pricing_factor = np.maximum(pricing_factor, _EPS)

    y_svc_new = y_svc * (1.0 + svc_drift_q) * pricing_factor
    y_svc_cur_new = y_svc_cur * (1.0 + svc_drift_q) * pricing_factor
    y_dp_new = y_dp * (1.0 + dp_drift_q) * pricing_factor
    fx_sens = float(params["international_fx_sensitivity"])
    y_intl_new = y_intl * (1.0 + intl_drift_q) * pricing_factor * (1.0 + fx_sens * fx)
    y_intl_new = np.maximum(y_intl_new, _EPS)
    y_svc_new = np.maximum(y_svc_new, _EPS)
    y_svc_cur_new = np.maximum(y_svc_cur_new, _EPS)
    y_dp_new = np.maximum(y_dp_new, _EPS)

    intensity_new = _sigmoid(_logit(intensity) + inc_drift_q + float(params["incentive_vol"]) * incentives_shock)
    other_new = other * (1.0 + other_drift_q)
    other_new = np.maximum(other_new, _EPS)

    opex_factor = (1.0 + opex_drift_q) * opex_seasonal * (1.0 + float(params["cost_vol"]) * costs)
    opex_factor = np.maximum(opex_factor, _EPS)
    opex_new = opex * opex_factor

    # 4–7. Revenue, incentives, net, profit
    categories = category_revenues(
        payments_volume_prior_billions=pv_prior,
        payments_volume_current_billions=pv_current,
        cross_border_share=share_new,
        processed_transactions_count=txn_new,
        yield_service=y_svc_new,
        yield_service_current=y_svc_cur_new,
        yield_data_processing=y_dp_new,
        yield_international=y_intl_new,
        other_revenue=other_new,
        service_lag=service_lag,
    )
    gross = (
        categories["service_revenue"]
        + categories["data_processing_revenue"]
        + categories["international_transaction_revenue"]
        + categories["other_revenue"]
    )
    incentives = client_incentives(gross, intensity_new)
    net = net_from_categories(categories, incentives)
    profit = net - opex_new

    cross_border_vol = share_new * pv_current
    domestic_vol = pv_current - cross_border_vol

    # Annualized quarterly growth. With no intervention this is the modeled rate.
    # A level shift replaces the activity rates with the realized change versus
    # the incoming state so the start quarter shows the shift. Transactions are
    # not shifted, so their rate is always the modeled one.
    if active:
        g_cd_realized = index_cd_new / np.maximum(index_cd, _EPS) - 1.0
        prior_cb = share * pv_prior
        g_cb_realized = cross_border_vol / np.maximum(prior_cb, _EPS) - 1.0
        growth_cd_yoy = (1.0 + g_cd_realized) ** 4 - 1.0
        growth_cb_yoy = (1.0 + g_cb_realized) ** 4 - 1.0
    else:
        growth_cd_yoy = (1.0 + g_cd) ** 4 - 1.0
        growth_cb_yoy = (1.0 + g_cb) ** 4 - 1.0
    growth_txn_yoy = (1.0 + g_txn) ** 4 - 1.0

    new_state: PathArrays = {
        "payments_volume_nominal_us": pv_current,
        "payments_volume_index_constant": index_cd_new,
        "cross_border_share": share_new,
        "processed_transactions_count": txn_new,
        "effective_yield_service": y_svc_new,
        "effective_yield_service_current": y_svc_cur_new,
        "effective_yield_data_processing": y_dp_new,
        "effective_yield_international": y_intl_new,
        "incentive_intensity": intensity_new,
        "other_revenue": other_new,
        "operating_expenses_ex_special_items": opex_new,
    }
    metrics: PathArrays = {
        "service_revenue": categories["service_revenue"],
        "data_processing_revenue": categories["data_processing_revenue"],
        "international_transaction_revenue": categories["international_transaction_revenue"],
        "other_revenue": categories["other_revenue"],
        "client_incentives": incentives,
        "net_revenue": net,
        "operating_expenses_ex_special_items": opex_new,
        "operating_profit_ex_special_items": profit,
        "payments_volume_nominal_us": pv_current,
        "domestic_payments_volume": domestic_vol,
        "cross_border_ex_intra_europe_volume": cross_border_vol,
        "processed_transactions_count": txn_new,
        "payments_volume_growth_constant": growth_cd_yoy,
        "cross_border_ex_intra_europe_growth_constant": growth_cb_yoy,
        "processed_transactions_growth": growth_txn_yoy,
        "cross_border_share": share_new,
        "incentive_intensity": intensity_new,
    }
    return StepResult(state=new_state, metrics=metrics)


__all__ = [
    "FACTORS",
    "annual_to_quarterly",
    "transition_quarter",
]
