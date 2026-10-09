"""Visa path-state construction from starting-state maps."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from longaeva_app.companies.base import PathArrays, StartingState, VariableSpec

# Convert usd_billions → usd_millions for yield application (SR millions / PV millions).
BILLIONS_TO_MILLIONS = 1000.0

STATE_VARIABLES: tuple[VariableSpec, ...] = (
    VariableSpec("payments_volume_nominal_us", unit="usd_billions", description="Nominal payments volume (USD bn)"),
    VariableSpec(
        "payments_volume_index_constant",
        unit="index",
        description="Constant-dollar PV index (100 at origin)",
    ),
    VariableSpec("cross_border_share", unit="ratio", description="Cross-border ex-intra-Europe share of PV"),
    VariableSpec(
        "processed_transactions_count",
        unit="transactions_millions",
        description="Processed transactions (millions)",
    ),
    VariableSpec(
        "effective_yield_service",
        unit="ratio",
        description="Lag-basis service yield: SR(t)/PV(t-1) in million-USD units",
    ),
    VariableSpec(
        "effective_yield_service_current",
        unit="ratio",
        description="Current-basis service yield: SR(t)/PV(t); used when service_lag=False",
    ),
    VariableSpec(
        "effective_yield_data_processing",
        unit="ratio",
        description="Data-processing yield: DPR / transactions",
    ),
    VariableSpec(
        "effective_yield_international",
        unit="ratio",
        description="International yield on cross-border volume (million-USD units)",
    ),
    VariableSpec("incentive_intensity", unit="ratio", description="Client incentives / gross category revenue"),
    VariableSpec("other_revenue", unit="usd_millions", description="Other-revenue run-rate"),
    VariableSpec(
        "operating_expenses_ex_special_items",
        unit="usd_millions",
        description="Recurring opex baseline (ex special items)",
    ),
)


def _require(start: StartingState, name: str) -> float:
    if name not in start:
        raise KeyError(f"starting state missing required field: {name}")
    value = float(start[name])
    if not np.isfinite(value):
        raise ValueError(f"starting state {name} is not finite: {value}")
    return value


def build_initial_state(
    start: StartingState,
    params: Mapping[str, float],
    n_paths: int,
) -> PathArrays:
    """Broadcast a starting-state map to ``n_paths`` arrays keyed by state variable."""
    if n_paths < 1:
        raise ValueError("n_paths must be >= 1")

    pv = _require(start, "payments_volume_nominal_us")
    if pv <= 0.0:
        raise ValueError(f"payments_volume_nominal_us must be positive, got {pv}")

    share = float(params["cross_border_share_at_origin"])
    if not (0.0 < share < 1.0):
        raise ValueError(f"cross_border_share_at_origin must be in (0,1), got {share}")

    service_rev = _require(start, "service_revenue")
    intl = _require(start, "international_transaction_revenue")
    other = _require(start, "other_revenue")
    txn = _require(start, "processed_transactions_count")
    intensity = _require(start, "incentive_intensity")
    opex = _require(start, "operating_expenses_ex_special_items")
    yield_service = _require(start, "effective_yield_service")
    yield_dp = _require(start, "effective_yield_data_processing")
    # data_processing_revenue is not required here: the yield is the state input.

    # Current-basis service yield: SR(q) / PV(q) in million-USD units.
    yield_service_current = service_rev / (pv * BILLIONS_TO_MILLIONS)
    # International yield scaled by the assumed share so intl ≈ yield * share * PV.
    yield_intl = intl / (share * pv * BILLIONS_TO_MILLIONS)

    if txn <= 0.0:
        raise ValueError(f"processed_transactions_count must be positive, got {txn}")
    if not (0.0 < intensity < 1.0):
        raise ValueError(f"incentive_intensity must be in (0,1), got {intensity}")

    def full(value: float) -> np.ndarray:
        return np.full(n_paths, value, dtype=np.float64)

    return {
        "payments_volume_nominal_us": full(pv),
        "payments_volume_index_constant": full(100.0),
        "cross_border_share": full(share),
        "processed_transactions_count": full(txn),
        "effective_yield_service": full(yield_service),
        "effective_yield_service_current": full(yield_service_current),
        "effective_yield_data_processing": full(yield_dp),
        "effective_yield_international": full(yield_intl),
        "incentive_intensity": full(intensity),
        "other_revenue": full(other),
        "operating_expenses_ex_special_items": full(opex),
    }


def synthetic_starting_state(
    *,
    payments_volume_nominal_us: float = 3300.0,
    service_revenue: float = 4000.0,
    data_processing_revenue: float = 4500.0,
    international_transaction_revenue: float = 3200.0,
    other_revenue: float = 800.0,
    processed_transactions_count: float = 60000.0,
    incentive_intensity: float = 0.28,
    operating_expenses_ex_special_items: float = 3000.0,
    prior_quarter_pv_billions: float | None = None,
) -> dict[str, float]:
    """Build a minimal starting-state map for property tests (not a starting-state reconstruction fixture)."""
    prior = prior_quarter_pv_billions if prior_quarter_pv_billions is not None else payments_volume_nominal_us / 1.05
    yield_service = service_revenue / (prior * BILLIONS_TO_MILLIONS)
    yield_dp = data_processing_revenue / processed_transactions_count
    return {
        "payments_volume_nominal_us": payments_volume_nominal_us,
        "service_revenue": service_revenue,
        "data_processing_revenue": data_processing_revenue,
        "international_transaction_revenue": international_transaction_revenue,
        "other_revenue": other_revenue,
        "processed_transactions_count": processed_transactions_count,
        "incentive_intensity": incentive_intensity,
        "operating_expenses_ex_special_items": operating_expenses_ex_special_items,
        "effective_yield_service": yield_service,
        "effective_yield_data_processing": yield_dp,
    }


__all__ = [
    "BILLIONS_TO_MILLIONS",
    "STATE_VARIABLES",
    "build_initial_state",
    "synthetic_starting_state",
]
