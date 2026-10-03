"""Company-model interface and fiscal calendar (FR-18).

Visa economics land in LON-19; this module declares the shared boundary so a stub
second company can pass conformance tests without engine changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from calendar import monthrange
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt

type FloatArray = npt.NDArray[np.floating[Any]]
type PathArrays = dict[str, FloatArray]
type StartingState = Mapping[str, float]


@dataclass(frozen=True, slots=True)
class FiscalPeriod:
    year: int
    quarter: int  # 1..4

    def __post_init__(self) -> None:
        if self.quarter not in {1, 2, 3, 4}:
            raise ValueError(f"quarter must be 1..4, got {self.quarter}")
        if self.year < 1:
            raise ValueError(f"year must be positive, got {self.year}")

    def label(self) -> str:
        return f"FY{self.year}Q{self.quarter}"

    def next(self) -> FiscalPeriod:
        if self.quarter == 4:
            return FiscalPeriod(self.year + 1, 1)
        return FiscalPeriod(self.year, self.quarter + 1)


@dataclass(frozen=True, slots=True)
class FiscalCalendar:
    """Fiscal calendar with a fixed year-end month (1..12). Day is last day of that month."""

    fiscal_year_end_month: int

    def __post_init__(self) -> None:
        if self.fiscal_year_end_month not in range(1, 13):
            raise ValueError(f"fiscal_year_end_month must be 1..12, got {self.fiscal_year_end_month}")

    def period_end(self, period: FiscalPeriod) -> date:
        end_month = ((self.fiscal_year_end_month - 1 + period.quarter * 3) % 12) + 1
        # Fiscal year Y ends in calendar year Y for end_month; Q1 of FY Y may end in calendar Y-1.
        if end_month > self.fiscal_year_end_month:
            cal_year = period.year - 1
        else:
            cal_year = period.year
        return _month_end(cal_year, end_month)

    def period_start(self, period: FiscalPeriod) -> date:
        # Start is day after previous period end
        if period.quarter == 1:
            prev = FiscalPeriod(period.year - 1, 4)
        else:
            prev = FiscalPeriod(period.year, period.quarter - 1)
        prev_end = self.period_end(prev)
        return date.fromordinal(prev_end.toordinal() + 1)

    def period_containing(self, day: date) -> FiscalPeriod:
        # Search nearby fiscal years
        for year in range(day.year - 1, day.year + 2):
            for quarter in (1, 2, 3, 4):
                period = FiscalPeriod(year, quarter)
                if self.period_start(period) <= day <= self.period_end(period):
                    return period
        raise ValueError(f"No fiscal period contains {day.isoformat()}")

    def label(self, period: FiscalPeriod) -> str:
        return period.label()


@dataclass(frozen=True, slots=True)
class VariableSpec:
    name: str
    unit: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class MetricSpec:
    name: str
    unit: str
    basis: str = "nominal"


PARAMETER_ROLES: frozenset[str] = frozenset({"free", "estimated", "assumption"})


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    unit: str
    lower: float
    upper: float
    default: float
    role: str = "free"
    description: str = ""

    def __post_init__(self) -> None:
        if self.lower > self.upper:
            raise ValueError(f"parameter {self.name}: lower > upper")
        if not (self.lower <= self.default <= self.upper):
            raise ValueError(f"parameter {self.name}: default outside [{self.lower}, {self.upper}]")
        if self.role not in PARAMETER_ROLES:
            raise ValueError(f"parameter {self.name}: role must be one of {sorted(PARAMETER_ROLES)}, got {self.role!r}")


@dataclass(frozen=True, slots=True)
class SwitchSpec:
    name: str
    default: bool
    description: str = ""


@dataclass(frozen=True, slots=True)
class IdentityTerm:
    metric: str
    sign: float = 1.0


@dataclass(frozen=True, slots=True)
class IdentitySpec:
    """result_metric ≈ sum(sign * metric) within relative tolerance."""

    result: str
    terms: tuple[IdentityTerm, ...]
    relative_tolerance: float = 1e-9


@dataclass(frozen=True, slots=True)
class StepResult:
    state: PathArrays
    metrics: PathArrays


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


class CompanyModel(ABC):
    """Company-agnostic simulation boundary (FR-18).

    Company modules never generate random numbers. All randomness arrives through
    ``shocks`` so paired runs share draws (FR-10) and replay is exact (FR-09).
    """

    key: ClassVar[str]
    calendar: ClassVar[FiscalCalendar]
    state_variables: ClassVar[tuple[VariableSpec, ...]]
    metrics: ClassVar[tuple[MetricSpec, ...]]
    parameters: ClassVar[tuple[ParameterSpec, ...]]
    factors: ClassVar[tuple[str, ...]]
    switches: ClassVar[tuple[SwitchSpec, ...]]
    identities: ClassVar[tuple[IdentitySpec, ...]]

    def default_parameters(self) -> dict[str, float]:
        return {spec.name: spec.default for spec in self.parameters}

    def default_switches(self) -> dict[str, bool]:
        return {spec.name: spec.default for spec in self.switches}

    def validate_parameters(self, values: Mapping[str, float]) -> list[str]:
        errors: list[str] = []
        known = {spec.name: spec for spec in self.parameters}
        for name, value in values.items():
            if name not in known:
                errors.append(f"unknown parameter: {name}")
                continue
            spec = known[name]
            if value < spec.lower or value > spec.upper:
                errors.append(f"{name}={value} outside [{spec.lower}, {spec.upper}]")
        for name in known:
            if name not in values:
                errors.append(f"missing parameter: {name}")
        return errors

    def validate_declarations(self) -> list[str]:
        errors: list[str] = []
        if not self.key or not self.key.replace("_", "").isalnum() or self.key != self.key.lower():
            errors.append(f"key must be a lowercase slug, got {self.key!r}")
        if not self.factors:
            errors.append("factors must be non-empty")
        if len(set(self.factors)) != len(self.factors):
            errors.append("factors must be unique")
        state_names = [s.name for s in self.state_variables]
        metric_names = [m.name for m in self.metrics]
        param_names = [p.name for p in self.parameters]
        switch_names = [s.name for s in self.switches]
        for label, names in (
            ("state_variables", state_names),
            ("metrics", metric_names),
            ("parameters", param_names),
            ("switches", switch_names),
        ):
            if len(set(names)) != len(names):
                errors.append(f"{label} names must be unique")
        known_metrics = set(metric_names)
        for identity in self.identities:
            if identity.result not in known_metrics:
                errors.append(f"identity result unknown metric: {identity.result}")
            for term in identity.terms:
                if term.metric not in known_metrics:
                    errors.append(f"identity term unknown metric: {term.metric}")
        for spec in self.parameters:
            if spec.role not in PARAMETER_ROLES:
                errors.append(f"parameter {spec.name}: invalid role {spec.role!r}")
        return errors

    @abstractmethod
    def factor_correlation(self, params: Mapping[str, float]) -> FloatArray:
        """Return an (n_factors, n_factors) correlation matrix."""

    @abstractmethod
    def initial_state(
        self,
        start: StartingState,
        params: Mapping[str, float],
        n_paths: int,
    ) -> PathArrays:
        """Broadcast starting state to ``n_paths`` path arrays keyed by state variable."""

    @abstractmethod
    def transition(
        self,
        state: PathArrays,
        shocks: PathArrays,
        params: Mapping[str, float],
        switches: Mapping[str, bool],
        period: FiscalPeriod,
    ) -> StepResult:
        """Advance one fiscal quarter. Must not mutate ``state`` or ``shocks``."""
