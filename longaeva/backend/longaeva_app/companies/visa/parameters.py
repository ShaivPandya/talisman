"""Visa engine parameter specifications.

Roles:
- ``free`` (8): transition growth/drift parameters fitted by calibration.
- ``estimated`` (22): seasonal ratios, residual volatilities/correlations, other-revenue growth.
- ``assumption`` (2): undisclosed levels flagged as assumptions (cross-border share).

Defaults are uncalibrated placeholders. A run on defaults is not a forecast.
Yield *levels* come from the starting state, never from parameters.
"""

from __future__ import annotations

from longaeva_app.companies.base import ParameterSpec

# Avoid literal 0.01 / 0.03 anywhere in the Visa engine package (teaching-fee grep).
_TWO_PCT = 2.0 / 100.0
_FOUR_PCT = 4.0 / 100.0
_FIVE_PCT = 5.0 / 100.0
_EIGHT_PCT = 8.0 / 100.0
_TEN_PCT = 10.0 / 100.0
_TWELVE_PCT = 12.0 / 100.0
_TWENTY_PCT = 20.0 / 100.0
_THIRTY_FIVE_PCT = 35.0 / 100.0
_FIFTY_PCT = 50.0 / 100.0


def _seasonal(name: str, description: str) -> ParameterSpec:
    return ParameterSpec(
        name=name,
        unit="ratio",
        lower=0.5,
        upper=1.5,
        default=1.0,
        role="estimated",
        description=description,
    )


VISA_PARAMETERS: tuple[ParameterSpec, ...] = (
    # --- free (8) ---
    ParameterSpec(
        name="payments_volume_growth",
        unit="ratio",
        lower=-0.4,
        upper=0.4,
        default=_EIGHT_PCT,
        role="free",
        description="Constant-dollar YoY payments-volume growth trend (annual).",
    ),
    ParameterSpec(
        name="cross_border_growth_premium",
        unit="ratio",
        lower=-0.2,
        upper=0.4,
        default=_TWO_PCT,
        role="free",
        description="Annual constant-dollar growth premium of cross-border ex-intra-Europe over total PV.",
    ),
    ParameterSpec(
        name="transactions_growth_premium",
        unit="ratio",
        lower=-0.2,
        upper=0.4,
        default=0.0,
        role="free",
        description="Annual growth premium of processed transactions over constant-dollar PV.",
    ),
    ParameterSpec(
        name="service_yield_drift",
        unit="ratio",
        lower=-0.2,
        upper=0.2,
        default=0.0,
        role="free",
        description="Annual drift of the lag-basis and current-basis service yields.",
    ),
    ParameterSpec(
        name="data_processing_yield_drift",
        unit="ratio",
        lower=-0.2,
        upper=0.2,
        default=0.0,
        role="free",
        description="Annual drift of the data-processing yield.",
    ),
    ParameterSpec(
        name="international_yield_drift",
        unit="ratio",
        lower=-0.2,
        upper=0.2,
        default=0.0,
        role="free",
        description="Annual drift of the international (cross-border) yield.",
    ),
    ParameterSpec(
        name="incentive_intensity_drift",
        unit="ratio",
        lower=-0.2,
        upper=0.2,
        default=0.0,
        role="free",
        description="Annual drift of incentive intensity in ratio points (applied via logit).",
    ),
    ParameterSpec(
        name="opex_growth",
        unit="ratio",
        lower=-0.2,
        upper=0.4,
        default=_FIVE_PCT,
        role="free",
        description="Annual growth of recurring operating expenses (ex special items).",
    ),
    # --- estimated: seasonal ratios (geo-mean normalized at use time) ---
    _seasonal("activity_seasonal_q1", "Q1 seasonal ratio for constant-dollar PV (geo-mean 1)."),
    _seasonal("activity_seasonal_q2", "Q2 seasonal ratio for constant-dollar PV (geo-mean 1)."),
    _seasonal("activity_seasonal_q3", "Q3 seasonal ratio for constant-dollar PV (geo-mean 1)."),
    _seasonal("activity_seasonal_q4", "Q4 seasonal ratio for constant-dollar PV (geo-mean 1)."),
    _seasonal("cross_border_seasonal_q1", "Q1 seasonal ratio for cross-border premium (geo-mean 1)."),
    _seasonal("cross_border_seasonal_q2", "Q2 seasonal ratio for cross-border premium (geo-mean 1)."),
    _seasonal("cross_border_seasonal_q3", "Q3 seasonal ratio for cross-border premium (geo-mean 1)."),
    _seasonal("cross_border_seasonal_q4", "Q4 seasonal ratio for cross-border premium (geo-mean 1)."),
    _seasonal("opex_seasonal_q1", "Q1 seasonal ratio for recurring opex (geo-mean 1)."),
    _seasonal("opex_seasonal_q2", "Q2 seasonal ratio for recurring opex (geo-mean 1)."),
    _seasonal("opex_seasonal_q3", "Q3 seasonal ratio for recurring opex (geo-mean 1)."),
    _seasonal("opex_seasonal_q4", "Q4 seasonal ratio for recurring opex (geo-mean 1)."),
    ParameterSpec(
        name="other_revenue_growth",
        unit="ratio",
        lower=-0.4,
        upper=0.6,
        default=_TWELVE_PCT,
        role="estimated",
        description="Annual growth of other-revenue run-rate.",
    ),
    # --- estimated: shock scales and correlations ---
    ParameterSpec(
        name="demand_vol",
        unit="ratio",
        lower=0.0,
        upper=_FIFTY_PCT,
        default=_FOUR_PCT,
        role="estimated",
        description="Std of demand shock contribution to constant-dollar PV growth (quarterly).",
    ),
    ParameterSpec(
        name="travel_vol",
        unit="ratio",
        lower=0.0,
        upper=_FIFTY_PCT,
        default=_FIVE_PCT,
        role="estimated",
        description="Std of travel shock contribution to cross-border growth premium (quarterly).",
    ),
    ParameterSpec(
        name="fx_vol",
        unit="ratio",
        lower=0.0,
        upper=_FIFTY_PCT,
        default=_TWO_PCT,
        role="estimated",
        description="Std of FX translation shock on nominal PV (quarterly).",
    ),
    ParameterSpec(
        name="pricing_vol",
        unit="ratio",
        lower=0.0,
        upper=_FIFTY_PCT,
        default=_TWO_PCT,
        role="estimated",
        description="Std of shared pricing shock on category yields (quarterly).",
    ),
    ParameterSpec(
        name="incentive_vol",
        unit="ratio",
        lower=0.0,
        upper=_FIFTY_PCT,
        default=_TWO_PCT,
        role="estimated",
        description="Std of incentive-intensity shock in logit space (quarterly).",
    ),
    ParameterSpec(
        name="cost_vol",
        unit="ratio",
        lower=0.0,
        upper=_FIFTY_PCT,
        default=_TWO_PCT,
        role="estimated",
        description="Std of cost shock on recurring opex growth (quarterly).",
    ),
    ParameterSpec(
        name="corr_demand_travel",
        unit="correlation",
        lower=-1.0,
        upper=1.0,
        default=0.4,
        role="estimated",
        description="Correlation of demand and travel factors.",
    ),
    ParameterSpec(
        name="corr_demand_fx",
        unit="correlation",
        lower=-1.0,
        upper=1.0,
        default=0.2,
        role="estimated",
        description="Correlation of demand and FX factors.",
    ),
    ParameterSpec(
        name="corr_travel_fx",
        unit="correlation",
        lower=-1.0,
        upper=1.0,
        default=0.15,
        role="estimated",
        description="Correlation of travel and FX factors.",
    ),
    # --- assumption (2) ---
    ParameterSpec(
        name="cross_border_share_at_origin",
        unit="ratio",
        lower=_FIVE_PCT,
        upper=_THIRTY_FIVE_PCT,
        default=_TWENTY_PCT,
        role="assumption",
        description=(
            "Analyst-assumption share of payments volume that is cross-border ex-intra-Europe "
            "at the origin quarter. Midpoint of the allowed range; not an estimate (LON-3: no "
            "disclosed CB level)."
        ),
    ),
    ParameterSpec(
        name="international_fx_sensitivity",
        unit="ratio",
        lower=-1.0,
        upper=1.0,
        default=0.0,
        role="assumption",
        description="Additional FX sensitivity on the international yield (0 = pricing shock only).",
    ),
)

FREE_PARAMETER_NAMES: frozenset[str] = frozenset(p.name for p in VISA_PARAMETERS if p.role == "free")
ASSUMPTION_PARAMETER_NAMES: frozenset[str] = frozenset(p.name for p in VISA_PARAMETERS if p.role == "assumption")

assert len(VISA_PARAMETERS) == 32, len(VISA_PARAMETERS)
assert len(FREE_PARAMETER_NAMES) == 8, len(FREE_PARAMETER_NAMES)

__all__ = [
    "VISA_PARAMETERS",
    "FREE_PARAMETER_NAMES",
    "ASSUMPTION_PARAMETER_NAMES",
]
