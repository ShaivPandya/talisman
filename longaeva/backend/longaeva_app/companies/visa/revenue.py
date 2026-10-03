"""Pure Visa category-revenue and incentive rules (LON-19 / MR-03)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from longaeva_app.companies.visa.state import BILLIONS_TO_MILLIONS

FloatArray = npt.NDArray[np.floating]


def category_revenues(
    *,
    payments_volume_prior_billions: FloatArray,
    payments_volume_current_billions: FloatArray,
    cross_border_share: FloatArray,
    processed_transactions_count: FloatArray,
    yield_service: FloatArray,
    yield_service_current: FloatArray,
    yield_data_processing: FloatArray,
    yield_international: FloatArray,
    other_revenue: FloatArray,
    service_lag: bool,
) -> dict[str, FloatArray]:
    """Compute the four revenue categories for one quarter.

    Yields for service and international are defined on million-USD activity units
    (PV billions × 1000). Data-processing yield is revenue per transaction-million.
    """
    pv_prior_m = payments_volume_prior_billions * BILLIONS_TO_MILLIONS
    pv_current_m = payments_volume_current_billions * BILLIONS_TO_MILLIONS
    cross_border_m = cross_border_share * pv_current_m

    if service_lag:
        service = yield_service * pv_prior_m
    else:
        service = yield_service_current * pv_current_m

    data_processing = yield_data_processing * processed_transactions_count
    international = yield_international * cross_border_m
    other = np.asarray(other_revenue, dtype=np.float64)

    return {
        "service_revenue": np.asarray(service, dtype=np.float64),
        "data_processing_revenue": np.asarray(data_processing, dtype=np.float64),
        "international_transaction_revenue": np.asarray(international, dtype=np.float64),
        "other_revenue": other,
    }


def client_incentives(gross_category_revenue: FloatArray, intensity: FloatArray) -> FloatArray:
    """Client incentives = intensity × Σ category revenue (positive magnitude)."""
    return np.asarray(intensity, dtype=np.float64) * np.asarray(gross_category_revenue, dtype=np.float64)


def net_from_categories(categories: dict[str, FloatArray], incentives: FloatArray) -> FloatArray:
    """Σ categories − incentives."""
    gross = (
        categories["service_revenue"]
        + categories["data_processing_revenue"]
        + categories["international_transaction_revenue"]
        + categories["other_revenue"]
    )
    return np.asarray(gross - incentives, dtype=np.float64)


__all__ = [
    "category_revenues",
    "client_incentives",
    "net_from_categories",
]
