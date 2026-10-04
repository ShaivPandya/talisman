"""Test-only stub second company (December fiscal year-end)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from longaeva_app.companies.base import (
    CompanyModel,
    FiscalCalendar,
    FiscalPeriod,
    FloatArray,
    IdentitySpec,
    IdentityTerm,
    MetricSpec,
    ParameterSpec,
    PathArrays,
    StartingState,
    StepResult,
    SwitchSpec,
    VariableSpec,
)


class StubCompany(CompanyModel):
    """Minimal second-company implementation for FR-18 interface conformance."""

    key = "stubco"
    calendar = FiscalCalendar(fiscal_year_end_month=12)
    state_variables = (
        VariableSpec("activity", unit="index", description="Activity index"),
        VariableSpec("opex", unit="usd_millions", description="Recurring opex"),
    )
    metrics = (
        MetricSpec("gross_revenue", unit="usd_millions", basis="nominal"),
        MetricSpec("incentives", unit="usd_millions", basis="nominal"),
        MetricSpec("net_revenue", unit="usd_millions", basis="nominal"),
        MetricSpec("operating_expenses", unit="usd_millions", basis="nominal"),
        MetricSpec("operating_profit", unit="usd_millions", basis="nominal"),
    )
    parameters = (
        ParameterSpec("yield", unit="ratio", lower=0.001, upper=0.05, default=0.01),
        ParameterSpec("incentive_intensity", unit="ratio", lower=0.0, upper=0.5, default=0.1),
        ParameterSpec("activity_drift", unit="ratio", lower=-0.2, upper=0.2, default=0.02),
        ParameterSpec("opex_growth", unit="ratio", lower=-0.1, upper=0.2, default=0.01),
        ParameterSpec("demand_vol", unit="ratio", lower=0.0, upper=0.5, default=0.05),
        ParameterSpec("fx_vol", unit="ratio", lower=0.0, upper=0.5, default=0.02),
        ParameterSpec("demand_fx_corr", unit="correlation", lower=-1.0, upper=1.0, default=0.3),
    )
    factors = ("demand", "fx")
    switches = (
        SwitchSpec("pool_mix", default=False, description="Unused stub switch"),
        SwitchSpec("service_lag", default=True, description="Unused stub switch"),
    )
    identities = (
        IdentitySpec(
            result="net_revenue",
            terms=(IdentityTerm("gross_revenue", 1.0), IdentityTerm("incentives", -1.0)),
        ),
        IdentitySpec(
            result="operating_profit",
            terms=(IdentityTerm("net_revenue", 1.0), IdentityTerm("operating_expenses", -1.0)),
        ),
    )

    def factor_correlation(self, params: Mapping[str, float]) -> FloatArray:
        corr = float(params["demand_fx_corr"])
        matrix = np.array([[1.0, corr], [corr, 1.0]], dtype=np.float64)
        return matrix

    def initial_state(
        self,
        start: StartingState,
        params: Mapping[str, float],
        n_paths: int,
    ) -> PathArrays:
        if n_paths < 1:
            raise ValueError("n_paths must be >= 1")
        activity = float(start.get("activity", 100.0))
        opex = float(start.get("opex", 10.0))
        return {
            "activity": np.full(n_paths, activity, dtype=np.float64),
            "opex": np.full(n_paths, opex, dtype=np.float64),
        }

    def transition(
        self,
        state: PathArrays,
        shocks: PathArrays,
        params: Mapping[str, float],
        switches: Mapping[str, bool],
        period: FiscalPeriod,
        interventions: tuple[Any, ...] = (),
    ) -> StepResult:
        del switches, period  # stub ignores ablation switches / calendar for dynamics
        if interventions:
            raise ValueError("stubco does not accept interventions")
        activity = np.array(state["activity"], dtype=np.float64, copy=True)
        opex = np.array(state["opex"], dtype=np.float64, copy=True)
        demand = np.asarray(shocks["demand"], dtype=np.float64)
        fx = np.asarray(shocks["fx"], dtype=np.float64)

        activity = activity * (1.0 + float(params["activity_drift"]) + float(params["demand_vol"]) * demand)
        # Mild FX effect on yield realization
        effective_yield = float(params["yield"]) * (1.0 + 0.1 * float(params["fx_vol"]) * fx)
        gross = activity * effective_yield
        incentives = gross * float(params["incentive_intensity"])
        net = gross - incentives
        opex = opex * (1.0 + float(params["opex_growth"]))
        profit = net - opex

        return StepResult(
            state={"activity": activity, "opex": opex},
            metrics={
                "gross_revenue": gross,
                "incentives": incentives,
                "net_revenue": net,
                "operating_expenses": opex,
                "operating_profit": profit,
            },
        )
