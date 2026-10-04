"""Operating-profit paths to forward earnings and an earnings/multiple value grid (LON-25).

Forward earnings hold the origin tax rate, net interest/other, and diluted share
count flat across the first four simulated quarters:

    earnings_q = (operating_profit_q + net_interest_other) * (1 - tax_rate)
    forward_eps = sum(earnings_q) / diluted_shares

Value per share is forward EPS times a multiple. Equity value in USD millions is
that product times the diluted share count (millions). Business uncertainty is
the EPS p10–p90 spread at the mid multiple. Multiple uncertainty is the low–high
spread at median EPS. The outer envelope is the product of those extremes and is
not a probability interval.

Any path with non-positive forward EPS makes the whole result unsupported.
Dropping those paths would bias the value upward.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from longaeva_app.valuation.multiples import MIN_BAND_QUARTERS, MultipleBand

FloatArray = npt.NDArray[np.floating[Any]]

OPERATING_PROFIT_METRIC = "operating_profit_ex_special_items"
FORWARD_QUARTERS = 4
OUTER_ENVELOPE_LABEL = "not a probability interval"
EPS_QUANTILES: tuple[tuple[str, float], ...] = (("p10", 0.10), ("p50", 0.50), ("p90", 0.90))
MULTIPLE_ROLES: tuple[str, ...] = ("low", "mid", "high")

Status = Literal["ok", "unsupported"]


@dataclass(frozen=True, slots=True)
class Assumption:
    name: str
    value: float | None
    unit: str
    source: str


@dataclass(frozen=True, slots=True)
class ForwardEps:
    mean: float
    p10: float
    p50: float
    p90: float
    n_paths: int


@dataclass(frozen=True, slots=True)
class ValueCell:
    eps_quantile: str
    multiple_role: str
    multiple: float
    value_per_share: float
    equity_usd_millions: float


@dataclass(frozen=True, slots=True)
class EarningsDriven:
    multiple: float
    value_per_share: dict[str, float]
    equity_usd_millions: dict[str, float]
    spread_per_share: float
    spread_equity_usd_millions: float


@dataclass(frozen=True, slots=True)
class MultipleDriven:
    forward_eps: float
    value_per_share: dict[str, float]
    equity_usd_millions: dict[str, float]
    spread_per_share: float
    spread_equity_usd_millions: float


@dataclass(frozen=True, slots=True)
class OuterEnvelope:
    low_per_share: float
    high_per_share: float
    low_equity_usd_millions: float
    high_equity_usd_millions: float
    label: str


@dataclass(frozen=True, slots=True)
class ValuationResult:
    status: Status
    reason: str | None
    assumptions: tuple[Assumption, ...]
    n_paths: int
    n_quarters: int
    forward_eps: ForwardEps | None = None
    band: MultipleBand | None = None
    grid: tuple[ValueCell, ...] | None = None
    earnings_driven: EarningsDriven | None = None
    multiple_driven: MultipleDriven | None = None
    outer_envelope: OuterEnvelope | None = None


def _assumptions(
    tax_rate: float | None,
    net_interest_other: float | None,
    diluted_shares: float | None,
    sources: Mapping[str, str] | None,
) -> tuple[Assumption, ...]:
    specs = (
        ("tax_rate", tax_rate, "ratio"),
        ("net_interest_other", net_interest_other, "usd_millions"),
        ("diluted_shares", diluted_shares, "shares_millions"),
    )
    out: list[Assumption] = []
    for name, value, unit in specs:
        source = sources.get(name) if sources is not None else None
        if source is None:
            source = "missing" if value is None else "starting_state"
        out.append(Assumption(name=name, value=value, unit=unit, source=source))
    return tuple(out)


def _unsupported(
    reason: str,
    assumptions: tuple[Assumption, ...],
    *,
    n_paths: int,
    n_quarters: int,
    band: MultipleBand | None = None,
) -> ValuationResult:
    return ValuationResult(
        status="unsupported",
        reason=reason,
        assumptions=assumptions,
        n_paths=n_paths,
        n_quarters=n_quarters,
        band=band,
    )


def _assumption_problem(
    tax_rate: float | None,
    net_interest_other: float | None,
    diluted_shares: float | None,
) -> str | None:
    if tax_rate is None:
        return "Missing tax_rate."
    if not math.isfinite(tax_rate) or not (0.0 <= tax_rate < 1.0):
        return f"tax_rate must be in [0, 1); got {tax_rate}."
    if net_interest_other is None:
        return "Missing net_interest_other."
    if not math.isfinite(net_interest_other):
        return f"net_interest_other must be finite; got {net_interest_other}."
    if diluted_shares is None:
        return "Missing diluted_shares."
    if not math.isfinite(diluted_shares) or diluted_shares <= 0.0:
        return f"diluted_shares must be positive; got {diluted_shares}."
    return None


def _band_problem(band: MultipleBand | None) -> str | None:
    if band is None:
        return (
            "No multiple band is available. The historical window has fewer than "
            f"{MIN_BAND_QUARTERS} quarters accepted by this cutoff."
        )
    if band.source == "sec_trailing_pe" and band.n_quarters < MIN_BAND_QUARTERS:
        return (
            f"Multiple band has {band.n_quarters} quarters accepted by the cutoff; "
            f"at least {MIN_BAND_QUARTERS} are required."
        )
    ordered = (
        math.isfinite(band.low)
        and math.isfinite(band.mid)
        and math.isfinite(band.high)
        and band.low > 0.0
        and band.mid > 0.0
        and band.high > 0.0
        and band.low <= band.mid <= band.high
    )
    if not ordered:
        return "Multiple band is invalid: low, mid, and high must be positive and ordered low <= mid <= high."
    return None


def value_bridge(
    operating_profit: FloatArray,
    *,
    tax_rate: float | None,
    net_interest_other: float | None,
    diluted_shares: float | None,
    band: MultipleBand | None,
    assumption_sources: Mapping[str, str] | None = None,
) -> ValuationResult:
    """Map operating-profit paths to a value grid, or an unsupported reason."""
    assumptions = _assumptions(tax_rate, net_interest_other, diluted_shares, assumption_sources)
    paths = np.asarray(operating_profit, dtype=np.float64)
    if paths.ndim != 2:
        return _unsupported(
            "Operating profit paths must be a 2-D array of shape (n_paths, n_quarters).",
            assumptions,
            n_paths=0,
            n_quarters=0,
        )
    n_paths = int(paths.shape[0])
    n_quarters = int(paths.shape[1])
    if n_paths < 1:
        return _unsupported("Operating profit paths are empty.", assumptions, n_paths=n_paths, n_quarters=n_quarters)
    if n_quarters < FORWARD_QUARTERS:
        return _unsupported(
            f"Simulation has {n_quarters} quarters; forward earnings need {FORWARD_QUARTERS}.",
            assumptions,
            n_paths=n_paths,
            n_quarters=n_quarters,
        )
    year = paths[:, :FORWARD_QUARTERS]
    if not bool(np.isfinite(year).all()):
        return _unsupported(
            "Operating profit paths contain non-finite values.",
            assumptions,
            n_paths=n_paths,
            n_quarters=n_quarters,
        )

    problem = _assumption_problem(tax_rate, net_interest_other, diluted_shares)
    if problem is not None or tax_rate is None or net_interest_other is None or diluted_shares is None:
        return _unsupported(
            problem or "Missing a valuation assumption.",
            assumptions,
            n_paths=n_paths,
            n_quarters=n_quarters,
        )
    band_problem = _band_problem(band)
    if band_problem is not None or band is None:
        return _unsupported(
            band_problem or "No multiple band is available.",
            assumptions,
            n_paths=n_paths,
            n_quarters=n_quarters,
            band=band,
        )

    tax = tax_rate
    other = net_interest_other
    shares = diluted_shares
    forward = np.sum((year + other) * (1.0 - tax), axis=1)
    eps = forward / shares
    non_positive = int(np.count_nonzero(eps <= 0.0))
    if non_positive:
        percent = 100.0 * non_positive / n_paths
        return _unsupported(
            (
                f"Forward EPS is non-positive on {non_positive} of {n_paths} paths ({percent:.1f}%). "
                "Dropping those paths would bias the value upward, so the bridge is unsupported."
            ),
            assumptions,
            n_paths=n_paths,
            n_quarters=n_quarters,
            band=band,
        )

    quantile_values = np.quantile(eps, [level for _name, level in EPS_QUANTILES])
    named = {name: float(quantile_values[index]) for index, (name, _level) in enumerate(EPS_QUANTILES)}
    multiples = {"low": band.low, "mid": band.mid, "high": band.high}
    cells: list[ValueCell] = []
    for eps_name in ("p10", "p50", "p90"):
        for role in MULTIPLE_ROLES:
            per_share = named[eps_name] * multiples[role]
            cells.append(
                ValueCell(
                    eps_quantile=eps_name,
                    multiple_role=role,
                    multiple=multiples[role],
                    value_per_share=per_share,
                    equity_usd_millions=per_share * shares,
                )
            )
    earnings_per_share = {name: named[name] * band.mid for name in ("p10", "p50", "p90")}
    earnings_equity = {name: value * shares for name, value in earnings_per_share.items()}
    multiple_per_share = {role: named["p50"] * multiples[role] for role in MULTIPLE_ROLES}
    multiple_equity = {role: value * shares for role, value in multiple_per_share.items()}
    outer_low = named["p10"] * band.low
    outer_high = named["p90"] * band.high
    return ValuationResult(
        status="ok",
        reason=None,
        assumptions=assumptions,
        n_paths=n_paths,
        n_quarters=n_quarters,
        forward_eps=ForwardEps(
            mean=float(np.mean(eps)),
            p10=named["p10"],
            p50=named["p50"],
            p90=named["p90"],
            n_paths=n_paths,
        ),
        band=band,
        grid=tuple(cells),
        earnings_driven=EarningsDriven(
            multiple=band.mid,
            value_per_share=earnings_per_share,
            equity_usd_millions=earnings_equity,
            spread_per_share=earnings_per_share["p90"] - earnings_per_share["p10"],
            spread_equity_usd_millions=earnings_equity["p90"] - earnings_equity["p10"],
        ),
        multiple_driven=MultipleDriven(
            forward_eps=named["p50"],
            value_per_share=multiple_per_share,
            equity_usd_millions=multiple_equity,
            spread_per_share=multiple_per_share["high"] - multiple_per_share["low"],
            spread_equity_usd_millions=multiple_equity["high"] - multiple_equity["low"],
        ),
        outer_envelope=OuterEnvelope(
            low_per_share=outer_low,
            high_per_share=outer_high,
            low_equity_usd_millions=outer_low * shares,
            high_equity_usd_millions=outer_high * shares,
            label=OUTER_ENVELOPE_LABEL,
        ),
    )


__all__ = [
    "EPS_QUANTILES",
    "FORWARD_QUARTERS",
    "OPERATING_PROFIT_METRIC",
    "OUTER_ENVELOPE_LABEL",
    "Assumption",
    "EarningsDriven",
    "ForwardEps",
    "MultipleDriven",
    "OuterEnvelope",
    "ValuationResult",
    "ValueCell",
    "value_bridge",
]
