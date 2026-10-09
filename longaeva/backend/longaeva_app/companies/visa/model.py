"""Visa ``CompanyModel`` implementation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from longaeva_app.companies.base import (
    CompanyModel,
    FiscalPeriod,
    FloatArray,
    IdentitySpec,
    IdentityTerm,
    MetricSpec,
    PathArrays,
    StartingState,
    StepResult,
    SwitchSpec,
)
from longaeva_app.companies.visa.definitions import VISA_FISCAL_CALENDAR
from longaeva_app.companies.visa.interventions import INTERVENTION_TYPES, parse_visa_interventions
from longaeva_app.companies.visa.parameters import VISA_PARAMETERS
from longaeva_app.companies.visa.state import STATE_VARIABLES, build_initial_state
from longaeva_app.companies.visa.transitions import FACTORS, transition_quarter

_MACRO_FACTORS = ("demand", "travel", "fx")


class VisaModel(CompanyModel):
    """Visa quarterly operating model with service-revenue lag and mix switches."""

    key = "visa"
    calendar = VISA_FISCAL_CALENDAR
    state_variables = STATE_VARIABLES
    metrics = (
        MetricSpec("service_revenue", unit="usd_millions", basis="gaap"),
        MetricSpec("data_processing_revenue", unit="usd_millions", basis="gaap"),
        MetricSpec("international_transaction_revenue", unit="usd_millions", basis="gaap"),
        MetricSpec("other_revenue", unit="usd_millions", basis="gaap"),
        MetricSpec("client_incentives", unit="usd_millions", basis="gaap"),
        MetricSpec("net_revenue", unit="usd_millions", basis="gaap"),
        MetricSpec("operating_expenses_ex_special_items", unit="usd_millions", basis="ex_special_items"),
        MetricSpec("operating_profit_ex_special_items", unit="usd_millions", basis="ex_special_items"),
        MetricSpec("payments_volume_nominal_us", unit="usd_billions", basis="nominal"),
        MetricSpec("domestic_payments_volume", unit="usd_billions", basis="nominal"),
        MetricSpec("cross_border_ex_intra_europe_volume", unit="usd_billions", basis="nominal"),
        MetricSpec("processed_transactions_count", unit="transactions_millions", basis="count"),
        MetricSpec("payments_volume_growth_constant", unit="ratio", basis="constant_dollar"),
        MetricSpec("cross_border_ex_intra_europe_growth_constant", unit="ratio", basis="constant_dollar"),
        MetricSpec("processed_transactions_growth", unit="ratio", basis="count"),
        MetricSpec("cross_border_share", unit="ratio", basis="derived"),
        MetricSpec("incentive_intensity", unit="ratio", basis="derived"),
    )
    parameters = VISA_PARAMETERS
    factors = FACTORS
    switches = (
        SwitchSpec(
            "service_lag",
            default=True,
            description="When True, service revenue uses prior-quarter PV; when False, same-quarter PV.",
        ),
        SwitchSpec(
            "pool_mix",
            default=False,
            description=(
                "When True, freeze the cross-border share so domestic and cross-border "
                "share one growth driver (travel draws still consumed)."
            ),
        ),
    )
    intervention_types = INTERVENTION_TYPES
    identities = (
        IdentitySpec(
            result="net_revenue",
            terms=(
                IdentityTerm("service_revenue", 1.0),
                IdentityTerm("data_processing_revenue", 1.0),
                IdentityTerm("international_transaction_revenue", 1.0),
                IdentityTerm("other_revenue", 1.0),
                IdentityTerm("client_incentives", -1.0),
            ),
        ),
        IdentitySpec(
            result="operating_profit_ex_special_items",
            terms=(
                IdentityTerm("net_revenue", 1.0),
                IdentityTerm("operating_expenses_ex_special_items", -1.0),
            ),
        ),
        IdentitySpec(
            result="payments_volume_nominal_us",
            terms=(
                IdentityTerm("domestic_payments_volume", 1.0),
                IdentityTerm("cross_border_ex_intra_europe_volume", 1.0),
            ),
        ),
    )

    def factor_correlation(self, params: Mapping[str, float]) -> FloatArray:
        """Build a 6×6 correlation matrix: 3×3 macro block + identity for independent factors."""
        c_dt = float(params["corr_demand_travel"])
        c_df = float(params["corr_demand_fx"])
        c_tf = float(params["corr_travel_fx"])
        macro = np.array(
            [
                [1.0, c_dt, c_df],
                [c_dt, 1.0, c_tf],
                [c_df, c_tf, 1.0],
            ],
            dtype=np.float64,
        )
        n = len(self.factors)
        corr = np.eye(n, dtype=np.float64)
        # Macro factors occupy the first three slots matching FACTORS order.
        for i, _name in enumerate(_MACRO_FACTORS):
            for j, _name_j in enumerate(_MACRO_FACTORS):
                corr[i, j] = macro[i, j]
        return corr

    def validate_parameters(self, values: Mapping[str, float]) -> list[str]:
        errors = super().validate_parameters(values)
        if errors:
            return errors
        # PSD check on the 3×3 macro correlation block.
        c_dt = float(values["corr_demand_travel"])
        c_df = float(values["corr_demand_fx"])
        c_tf = float(values["corr_travel_fx"])
        macro = np.array(
            [
                [1.0, c_dt, c_df],
                [c_dt, 1.0, c_tf],
                [c_df, c_tf, 1.0],
            ],
            dtype=np.float64,
        )
        eig = np.linalg.eigvalsh(macro)
        if float(np.min(eig)) < -1e-10:
            errors.append(
                f"macro correlation block is not positive-semidefinite (min eigenvalue {float(np.min(eig)):.3e})"
            )
        return errors

    def parse_interventions(self, raw: Sequence[Mapping[str, Any]]) -> tuple[Any, ...]:
        return parse_visa_interventions(raw)

    def initial_state(
        self,
        start: StartingState,
        params: Mapping[str, float],
        n_paths: int,
    ) -> PathArrays:
        return build_initial_state(start, params, n_paths)

    def transition(
        self,
        state: PathArrays,
        shocks: PathArrays,
        params: Mapping[str, float],
        switches: Mapping[str, bool],
        period: FiscalPeriod,
        interventions: tuple[Any, ...] = (),
    ) -> StepResult:
        return transition_quarter(state, shocks, params, switches, period, interventions=interventions)


__all__ = ["VisaModel"]
