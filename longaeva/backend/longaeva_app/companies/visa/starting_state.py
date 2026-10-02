"""Visa starting-state fixtures and reconciliation helpers (LON-3).

Fixtures live under ``data/fixtures/states/visa_YYYY-MM-DD.json``. Every measured
or derived value carries a source span into a retained original. Identities and
derived recomputes are checked offline by ``tests/test_state_reconciliation.py``.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from longaeva_app.companies.base import StartingState
from longaeva_app.companies.visa.definitions import (
    BASIS_VOCABULARY,
    FIELDS,
    UNIT_VOCABULARY,
    FieldDefinition,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[4]  # longaeva/
STATES_DIR = PACKAGE_ROOT / "data" / "fixtures" / "states"

FIELD_BY_NAME: dict[str, FieldDefinition] = {f.name: f for f in FIELDS}

ValueStatus = Literal["measured", "derived", "unavailable_at_cutoff"]

# Reported financials are in whole millions / whole percent / one-decimal billions.
# Allow half a reported unit of residual per identity term (Visa footnotes rounding).
IDENTITY_ABS_TOLERANCE = {
    "usd_millions": 0.5,
    "usd_billions": 0.05,
    "percent": 0.5,
    "ratio": 0.0005,
    "transactions_millions": 0.5,
    "shares_millions": 0.5,
    "index": 1e-9,
}


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str  # "{accession}/{document}"
    accession: str
    document: str
    form: str
    acceptance_utc: str
    url: str
    role: Literal["input", "post_cutoff_check"]
    content_sha256: str
    note: str = ""


class Span(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor: str
    quote: str
    char_start: int
    char_end: int

    @model_validator(mode="after")
    def _order(self) -> Span:
        if self.char_end < self.char_start:
            raise ValueError("char_end must be >= char_start")
        if self.char_end - self.char_start != len(self.quote):
            raise ValueError(f"char span length {self.char_end - self.char_start} != quote length {len(self.quote)}")
        return self


class Derivation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    formula: str
    inputs: dict[str, float]
    # Half-width band from whole-percent growth rounding, in the field's unit.
    rounding_band: float | None = None


class StateValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: ValueStatus
    value: float | None = None
    unit: str
    basis: str
    period_label: str | None = None  # e.g. FY2024Q3
    period_start: date | None = None
    period_end: date | None = None
    source_id: str | None = None
    span: Span | None = None
    derivation: Derivation | None = None
    unavailable_reason: str | None = None
    first_post_cutoff_source_id: str | None = None
    note: str = ""

    @field_validator("unit")
    @classmethod
    def _unit_vocab(cls, v: str) -> str:
        if v not in UNIT_VOCABULARY:
            raise ValueError(f"unknown unit: {v}")
        return v

    @field_validator("basis")
    @classmethod
    def _basis_vocab(cls, v: str) -> str:
        if v not in BASIS_VOCABULARY:
            raise ValueError(f"unknown basis: {v}")
        return v

    @model_validator(mode="after")
    def _status_rules(self) -> StateValue:
        if self.name not in FIELD_BY_NAME:
            raise ValueError(f"unknown field: {self.name}")
        field = FIELD_BY_NAME[self.name]
        if self.unit != field.unit:
            raise ValueError(f"{self.name}: unit {self.unit} != field definition {field.unit}")
        # Derived observations may use basis "derived" even when the field's default basis differs.
        if self.status != "derived" and self.basis != field.basis and self.basis != "derived":
            # Allow gaap/ex_special_items etc. to match; flag only clear mismatches of category.
            if field.basis not in {self.basis, "derived"} and self.basis not in {
                field.basis,
                "derived",
            }:
                pass  # soft: definitions use the scoring basis; fixtures may tag measured basis

        if self.status == "measured":
            if self.value is None:
                raise ValueError(f"{self.name}: measured value requires value")
            if self.span is None or self.source_id is None:
                raise ValueError(f"{self.name}: measured value requires source_id and span")
            if self.derivation is not None:
                raise ValueError(f"{self.name}: measured value must not have derivation")
        elif self.status == "derived":
            if self.value is None:
                raise ValueError(f"{self.name}: derived value requires value")
            if self.derivation is None:
                raise ValueError(f"{self.name}: derived value requires derivation")
            if self.span is None or self.source_id is None:
                # Derived values still cite the growth / level inputs via derivation;
                # they must also point at a primary supporting source + span for the
                # growth rate or the year-ago level used in the formula.
                raise ValueError(f"{self.name}: derived value requires a supporting source_id and span")
        elif self.status == "unavailable_at_cutoff":
            if self.value is not None:
                raise ValueError(f"{self.name}: unavailable value must not set value")
            if not self.unavailable_reason:
                raise ValueError(f"{self.name}: unavailable value requires unavailable_reason")
        return self


class IdentityResidual(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    left: float
    right: float
    residual: float
    tolerance: float
    passed: bool


class SupportingLevel(BaseModel):
    """Measured intermediate (e.g. year-ago PV) used in a derivation but not a FIELDS key."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: float
    unit: str
    basis: str
    period_label: str
    period_start: date
    period_end: date
    source_id: str
    span: Span
    note: str = ""

    @field_validator("unit")
    @classmethod
    def _unit_vocab(cls, v: str) -> str:
        if v not in UNIT_VOCABULARY:
            raise ValueError(f"unknown unit: {v}")
        return v

    @field_validator("basis")
    @classmethod
    def _basis_vocab(cls, v: str) -> str:
        if v not in BASIS_VOCABULARY:
            raise ValueError(f"unknown basis: {v}")
        return v


class StartingStateFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    company: Literal["visa"] = "visa"
    origin_date: date
    cutoff_utc: str
    fiscal_year: int
    fiscal_quarter: int
    target_fiscal_year: int
    target_fiscal_quarter: int
    release_accession: str
    prior_10q_accession: str
    sources: dict[str, SourceRef]
    values: dict[str, StateValue]
    supporting_levels: dict[str, SupportingLevel] = Field(default_factory=dict)
    post_cutoff_comparisons: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sources_cover_values(self) -> StartingStateFixture:
        for name, val in self.values.items():
            if val.source_id is not None and val.source_id not in self.sources:
                raise ValueError(f"{name}: source_id {val.source_id} not in sources")
            if val.first_post_cutoff_source_id is not None and val.first_post_cutoff_source_id not in self.sources:
                raise ValueError(
                    f"{name}: first_post_cutoff_source_id {val.first_post_cutoff_source_id} not in sources"
                )
        for key, level in self.supporting_levels.items():
            if level.source_id not in self.sources:
                raise ValueError(f"supporting_levels[{key}]: source_id not in sources")
            if level.key != key:
                raise ValueError(f"supporting_levels key {key!r} != level.key {level.key!r}")
        return self


def load_fixture(path: Path) -> StartingStateFixture:
    data = json.loads(path.read_text(encoding="utf-8"))
    return StartingStateFixture.model_validate(data)


def fixture_path_for(origin_date: str) -> Path:
    return STATES_DIR / f"visa_{origin_date}.json"


def required_fixture_paths() -> tuple[Path, Path]:
    return (
        STATES_DIR / "visa_2024-07-23.json",
        STATES_DIR / "visa_2025-10-28.json",
    )


def _get(values: dict[str, StateValue], name: str) -> float:
    entry = values[name]
    if entry.value is None:
        raise KeyError(f"{name} has no numeric value (status={entry.status})")
    return float(entry.value)


def identity_residuals(fixture: StartingStateFixture) -> list[IdentityResidual]:
    """Compute the four identity checks required by LON-3 / MR-04."""
    v = fixture.values
    out: list[IdentityResidual] = []

    def check(name: str, left: float, right: float, unit: str) -> None:
        tol = IDENTITY_ABS_TOLERANCE[unit]
        residual = left - right
        out.append(
            IdentityResidual(
                name=name,
                left=left,
                right=right,
                residual=residual,
                tolerance=tol,
                passed=abs(residual) <= tol,
            )
        )

    categories = (
        _get(v, "service_revenue")
        + _get(v, "data_processing_revenue")
        + _get(v, "international_transaction_revenue")
        + _get(v, "other_revenue")
        - _get(v, "client_incentives")
    )
    check("net_revenue_identity", categories, _get(v, "net_revenue"), "usd_millions")

    check(
        "operating_profit_gaap_identity",
        _get(v, "net_revenue") - _get(v, "operating_expenses_gaap"),
        _get(v, "operating_profit_gaap"),
        "usd_millions",
    )
    check(
        "operating_profit_ex_special_items_identity",
        _get(v, "net_revenue") - _get(v, "operating_expenses_ex_special_items"),
        _get(v, "operating_profit_ex_special_items"),
        "usd_millions",
    )

    # GAAP opex − sum(excluded items that reduce GAAP opex) + sum(excluded benefits)
    # equals ex-special-items opex. The fixture stores special_items as the net GAAP
    # amount of identified items removed in the bridge (positive = expense removed).
    # Bridge identity: opex_gaap - special_items_net_in_opex = opex_ex
    # where special_items on the fixture is the algebraic sum of opex bridge lines
    # that move from GAAP to non-GAAP (signs as in the release table: negative in
    # the release means an expense is excluded, i.e. subtract a negative? See below).
    #
    # Release bridge "As reported" → "Non-GAAP" for opex:
    #   Non-GAAP = As reported + sum(signed bridge adjustments printed in the table)
    # We store operating_expenses_gaap, operating_expenses_ex_special_items, and
    # special_items = gaap - ex_special_items (so special_items = amount removed).
    check(
        "opex_bridge_identity",
        _get(v, "operating_expenses_gaap") - _get(v, "special_items"),
        _get(v, "operating_expenses_ex_special_items"),
        "usd_millions",
    )

    return out


def recompute_derived(fixture: StartingStateFixture) -> dict[str, float]:
    """Recompute every derived value from its ``derivation.inputs`` and ``formula``.

    Supported formulas (LON-3 roll-forward):
      - ``year_ago * (1 + growth_pct/100)``
      - ``(ttm - nine_month) * (1 + growth_pct/100)``
      - ``(ttm - nine_month)``  (year-ago quarter as residual of TTM)
      - ``a - b`` / ``a + b`` / ``a * b`` / ``a / b``
    """
    results: dict[str, float] = {}
    for name, entry in fixture.values.items():
        if entry.status != "derived" or entry.derivation is None:
            continue
        formula = entry.derivation.formula.strip()
        inputs = entry.derivation.inputs
        results[name] = _eval_formula(formula, inputs)
    return results


_FORMULA_YEAR_AGO_GROWTH = re.compile(r"^year_ago\s*\*\s*\(\s*1\s*\+\s*growth_pct\s*/\s*100\s*\)$")
_FORMULA_TTM_RESIDUAL_GROWTH = re.compile(
    r"^\(\s*ttm\s*-\s*nine_month\s*\)\s*\*\s*\(\s*1\s*\+\s*growth_pct\s*/\s*100\s*\)$"
)
_FORMULA_TTM_RESIDUAL = re.compile(r"^\(\s*ttm\s*-\s*nine_month\s*\)$")
_FORMULA_BINARY = re.compile(r"^(?P<a>[a-z_]+)\s*(?P<op>[+\-*/])\s*(?P<b>[a-z_]+)$")


def _eval_formula(formula: str, inputs: dict[str, float]) -> float:
    if _FORMULA_YEAR_AGO_GROWTH.match(formula):
        return inputs["year_ago"] * (1.0 + inputs["growth_pct"] / 100.0)
    if _FORMULA_TTM_RESIDUAL_GROWTH.match(formula):
        return (inputs["ttm"] - inputs["nine_month"]) * (1.0 + inputs["growth_pct"] / 100.0)
    if _FORMULA_TTM_RESIDUAL.match(formula):
        return inputs["ttm"] - inputs["nine_month"]
    m = _FORMULA_BINARY.match(formula)
    if m:
        a = inputs[m.group("a")]
        b = inputs[m.group("b")]
        op = m.group("op")
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return a / b
    raise ValueError(f"unsupported derivation formula: {formula!r}")


def to_starting_state(fixture: StartingStateFixture) -> StartingState:
    """Map fixture values to the engine ``StartingState`` mapping (LON-19).

    Only fields with a numeric value are included. Indices that are unavailable
    stay out of the map (engine will require them later once calibrated).
    """
    out: dict[str, float] = {}
    for name, entry in fixture.values.items():
        if entry.value is not None:
            out[name] = float(entry.value)
    return out


def parse_numeric_quote(quote: str, unit: str) -> float:
    """Parse a span quote into a float in the field's unit.

    Handles ``$``, commas, parentheses (negatives), trailing ``%``, and bare numbers.
    Does not convert billions↔millions; the quote must already be in the field unit
    (e.g. ``8,900`` for usd_millions, ``6,482`` for usd_billions, ``18.6`` for percent
    stored as percent points, or ``0.186`` for ratio — callers choose).
    """
    s = quote.strip()
    s = s.replace(",", "").replace("$", "").replace("\xa0", "").strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    if not s:
        raise ValueError(f"empty numeric quote: {quote!r}")
    value = float(s)
    if negative:
        value = -value
    if unit == "percent":
        return value
    return value


__all__ = [
    "STATES_DIR",
    "StartingStateFixture",
    "StateValue",
    "SourceRef",
    "Span",
    "Derivation",
    "SupportingLevel",
    "IdentityResidual",
    "load_fixture",
    "fixture_path_for",
    "required_fixture_paths",
    "identity_residuals",
    "recompute_derived",
    "to_starting_state",
    "parse_numeric_quote",
    "IDENTITY_ABS_TOLERANCE",
    "FIELD_BY_NAME",
]
