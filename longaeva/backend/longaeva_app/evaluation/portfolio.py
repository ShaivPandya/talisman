"""Independent benchmark windows and synthetic long/cash scoring (LON-28).

Real Visa prices remain blocked by LON-6. No live strategy adapter is provided.
Only the explicit report projection below may be written to disk.
"""

from __future__ import annotations

import calendar
import json
import math
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from longaeva_app.collect.benchmark_sources import load_manifest, parse_retained_visa_dividends
from longaeva_app.collect.benchmarks import BenchmarkInputs, Fetch, fetch_inputs
from longaeva_app.evaluation.origins import load_evaluation_origins
from longaeva_app.hashing import content_hash, sha256_hex
from longaeva_app.valuation.actions import (
    CONFIG_PATH,
    ActionName,
    DecisionRule,
    canonical_rule,
    decide,
    load_decision_rule,
    target_shares,
)

SUITE_VERSION = "lon28-v1"
EXPECTED_RULE_HASH = "d93e2e052b7dbc75f00c4691e8afa464ac54c8d5a9bde602037767ec9dbd3039"
EXPLORATORY = "Exploratory independent holding-period results; overlapping windows are not a compounded portfolio or evidence of alpha."
VISA_REASON = "No license-compliant free daily Visa price source; LON-6 gate remains blocked."
PACKAGE_ROOT = Path(__file__).resolve().parents[3]


def assert_frozen(rule: DecisionRule) -> None:
    if rule.rule_hash != EXPECTED_RULE_HASH or content_hash(canonical_rule(rule)) != EXPECTED_RULE_HASH:
        raise ValueError("decision-rule hash differs from the pre-scoring frozen value")


def select_window(sessions: Sequence[date], cutoff: datetime, horizon: int) -> tuple[date, ...]:
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must have a timezone")
    if horizon <= 0 or list(sessions) != sorted(set(sessions)):
        raise ValueError("positive horizon and unique ordered sessions required")
    cutoff_date = cutoff.astimezone(ZoneInfo("America/New_York")).date()
    if not sessions or sessions[0] > cutoff_date:
        raise ValueError("session history does not cover cutoff")
    after = [day for day in sessions if day > cutoff_date]
    if len(after) < horizon + 1:
        raise ValueError("insufficient coverage for entry plus complete holding period")
    return tuple(after[: horizon + 1])


def primary_returns(inputs: BenchmarkInputs, as_of: date) -> tuple[dict[date, float | None], set[date]]:
    sessions = inputs.sessions()
    counts = Counter(day.strftime("%Y-%m") for day in sessions if inputs.fred.get(day) is not None)
    gaps = {day.strftime("%Y-%m") for day in sessions if inputs.fred.get(day) is None}
    months = sorted(inputs.shiller.dividends)
    first_fred = min(inputs.fred) if inputs.fred else date.max
    last_fred = max(inputs.fred) if inputs.fred else date.min
    returns: dict[date, float | None] = {}
    estimated: set[date] = set()
    for previous, day in zip(sessions, sessions[1:], strict=False):
        month = day.strftime("%Y-%m")
        last_day = date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])
        last_weekday = last_day
        while last_weekday.weekday() >= 5:
            last_weekday -= timedelta(days=1)
        dividend_index = bisect_right(months, month) - 1
        p0, p1 = inputs.fred.get(previous), inputs.fred.get(day)
        complete = first_fred <= day.replace(day=1) and last_fred >= last_weekday
        if p0 is None or p1 is None or dividend_index < 0 or month in gaps or last_day >= as_of or not complete:
            returns[day] = None
            continue
        source_month = months[dividend_index]
        dividend = inputs.shiller.dividends[source_month] / (12 * counts[month])
        returns[day] = (p1 + dividend) / p0 - 1
        if source_month != month:
            estimated.add(day)
    return returns, estimated


def return_metrics(returns: Sequence[float]) -> dict[str, float]:
    if not returns or any(not math.isfinite(value) or value <= -1 for value in returns):
        raise ValueError("finite returns greater than -100% required")
    wealth, peak, drawdown = 1.0, 1.0, 0.0
    for value in returns:
        wealth *= 1 + value
        peak = max(peak, wealth)
        drawdown = min(drawdown, wealth / peak - 1)
    return {"total_return": wealth - 1, "max_drawdown": drawdown}


def drift_diagnostic(
    inputs: BenchmarkInputs, returns: Mapping[date, float | None], start: date, end: date
) -> dict[str, Any]:
    """Compare monthly-average *real* wealth changes on a matched basis.

    CPI converts our nominal daily wealth to real units. The workbook's real
    TR price uses monthly-average prices, so average daily wealth before
    differencing. Arbitrary starting scales cancel. Never output the levels.
    """
    shiller = inputs.shiller
    empty = {"status": "unavailable", "n_months": 0, "mean_absolute_drift_pp": None, "max_absolute_drift_pp": None}
    if shiller.diagnostic_basis != "monthly_average_real_total_return":
        return {**empty, "reason": "Workbook lacks a recognized real total-return price / CPI basis."}
    monthly: dict[str, list[float]] = defaultdict(list)
    invalid: set[str] = set()
    wealth = 1.0
    for day in inputs.sessions():
        if day < start.replace(day=1) or day > end:
            continue
        month = day.strftime("%Y-%m")
        value = returns.get(day)
        if value is None:
            invalid.add(month)
        else:
            wealth *= 1 + value
            monthly[month].append(wealth)
    months = sorted(monthly)
    differences: list[float] = []
    for first, second in zip(months, months[1:], strict=False):
        next_month = (
            (date.fromisoformat(first + "-01").replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m")
        )
        if second != next_month or first in invalid or second in invalid:
            continue
        second_end = date.fromisoformat(second + "-01")
        second_end = second_end.replace(day=calendar.monthrange(second_end.year, second_end.month)[1])
        if second_end > end:
            continue
        if any(m not in shiller.cpi or m not in shiller.real_total_return for m in (first, second)):
            continue
        ours = (mean(monthly[second]) / shiller.cpi[second]) / (mean(monthly[first]) / shiller.cpi[first]) - 1
        theirs = shiller.real_total_return[second] / shiller.real_total_return[first] - 1
        differences.append(100 * (ours - theirs))
    if not differences:
        return {**empty, "reason": "No complete consecutive months with matching CPI and real TR observations."}
    return {
        "status": "ok",
        "n_months": len(differences),
        "mean_absolute_drift_pp": mean(abs(x) for x in differences),
        "max_absolute_drift_pp": max(abs(x) for x in differences),
        "mean_signed_drift_pp": mean(differences),
        "method": "Monthly-average daily approximate wealth / monthly CPI versus Shiller real total-return price; compare monthly percentage changes.",
        "limitation": "Method/timing diagnostic against Shiller's monthly construction, not validation against official S&P total return.",
    }


@dataclass(frozen=True)
class Signal:
    value_per_share: float
    reference_price: float
    value_available_at: datetime
    price_available_at: datetime


@dataclass(frozen=True)
class Dividend:
    ex_date: date
    payable_date: date
    amount_per_share: float


def score_synthetic_window(
    *,
    sessions: Sequence[date],
    prices: Mapping[date, float],
    cutoff: datetime,
    signal: Signal,
    dividends: Sequence[Dividend],
    dividends_complete: bool,
    benchmark_returns: Mapping[str, Sequence[float]],
    rule: DecisionRule,
    capital: float = 100_000,
) -> dict[str, Any]:
    """Pure, funded long/cash scorer. Inputs must be synthetic, split-consistent.

    Dividends become receivables on ex-date and cash on payable date; neither
    changes share count. Terminal wealth includes outstanding receivables.
    Initial and terminal trades pay friction, including for a 'hold' window.
    """
    assert_frozen(rule)
    if not dividends_complete:
        raise ValueError("dividend coverage must be explicitly complete; missing is not zero")
    for timestamp in (cutoff, signal.value_available_at, signal.price_available_at):
        if timestamp.tzinfo is None:
            raise ValueError("signal and cutoff timestamps must be timezone-aware")
    if max(signal.value_available_at, signal.price_available_at) > cutoff:
        raise ValueError("signal input published after cutoff")
    if any(not math.isfinite(x) or x <= 0 for x in (capital, signal.value_per_share, signal.reference_price)):
        raise ValueError("positive finite capital and signal values required")
    days = select_window(sessions, cutoff, rule.holding_period_trading_days)
    if any(day not in prices or not math.isfinite(prices[day]) or prices[day] <= 0 for day in days):
        raise ValueError("complete positive price coverage required")
    if len({d.ex_date for d in dividends}) != len(dividends):
        raise ValueError("duplicate dividend ex-date")
    if any(
        d.payable_date < d.ex_date or not math.isfinite(d.amount_per_share) or d.amount_per_share < 0 for d in dividends
    ):
        raise ValueError("invalid dividend event")
    if any(len(values) != len(days) - 1 for values in benchmark_returns.values()):
        raise ValueError("benchmark coverage must match the full holding window")
    benchmark_metrics = {key: return_metrics(values) for key, values in benchmark_returns.items()}
    action = decide(signal.value_per_share / signal.reference_price - 1, rule)
    base_weight = 1 / (1 + rule.add_fraction)
    weight = target_shares(action, base_weight, rule)
    friction = (rule.transaction_cost_bps + rule.slippage_bps + rule.market_impact_bps) / 10_000

    def simulate(weight: float, action: ActionName) -> dict[str, float]:
        # Reserve funding on only the incremental add allocation. All fees are
        # financed with cash; there is no borrowing even for the 100% target.
        added_fraction = max(0.0, weight - base_weight) / weight if weight and action == "add" else 0.0
        funding_rate = added_fraction * rule.funding_bps_per_day * rule.holding_period_trading_days / 10_000
        notional = capital * weight / (1 + friction + funding_rate)
        shares = notional / prices[days[0]]
        entry_cost, funding_cost = notional * friction, notional * funding_rate
        cash = capital - notional - entry_cost - funding_cost
        assert cash >= -1e-8
        cash = max(0.0, cash)
        entitled = [d for d in dividends if days[0] < d.ex_date <= days[-1]]
        peak, drawdown = capital, 0.0
        exposures: list[float] = []
        for i, day in enumerate(days):
            # Paid cash and unpaid receivables have equal marked value; adding
            # entitlement once avoids a second credit at the payment date.
            entitlement = shares * sum(d.amount_per_share for d in entitled if d.ex_date <= day)
            equity = cash + shares * prices[day] + entitlement
            if i < len(days) - 1:
                exposures.append(shares * prices[day] / equity)
            else:
                equity -= shares * prices[day] * friction
            peak = max(peak, equity)
            drawdown = min(drawdown, equity / peak - 1)
        terminal_notional = shares * prices[days[-1]]
        terminal_cost = terminal_notional * friction
        dividend_total = shares * sum(d.amount_per_share for d in entitled)
        return {
            "total_return": (cash + terminal_notional - terminal_cost + dividend_total) / capital - 1,
            "max_drawdown": drawdown,
            "average_invested_exposure": mean(exposures),
            "entry_cost": entry_cost,
            "exit_cost": terminal_cost,
            "funding_cost": funding_cost,
            "transaction_cost": (notional + terminal_notional) * rule.transaction_cost_bps / 10_000,
            "slippage_cost": (notional + terminal_notional) * rule.slippage_bps / 10_000,
            "market_impact_cost": (notional + terminal_notional) * rule.market_impact_bps / 10_000,
            "dividends_paid": shares * sum(d.amount_per_share for d in entitled if d.payable_date <= days[-1]),
            "dividends_receivable": shares * sum(d.amount_per_share for d in entitled if d.payable_date > days[-1]),
            "initial_cash_after_costs": max(0.0, cash),
            "target_weight": weight,
        }

    strategy, buy_hold = simulate(weight, action), simulate(1.0, "hold")
    return {
        "synthetic": True,
        "action": action,
        "entry_date": days[0].isoformat(),
        "exit_date": days[-1].isoformat(),
        "rule_hash": rule.rule_hash,
        "strategy": strategy,
        "visa_buy_and_hold": buy_hold,
        "excess_vs_visa": strategy["total_return"] - buy_hold["total_return"],
        "excess_vs_benchmarks": {
            key: strategy["total_return"] - value["total_return"] for key, value in benchmark_metrics.items()
        },
    }


def overlap_counts(windows: Sequence[tuple[date, date]]) -> dict[str, int]:
    pairs = [
        (i, j)
        for i in range(len(windows))
        for j in range(i + 1, len(windows))
        if max(windows[i][0], windows[j][0]) < min(windows[i][1], windows[j][1])
    ]
    return {"overlapping_pairs": len(pairs), "windows_with_overlap": len({i for pair in pairs for i in pair})}


def run_portfolio_evaluation(
    *,
    window: str = "all",
    origin_dates: list[str] | None = None,
    fetch: Fetch | None = None,
    now: datetime | None = None,
    rule_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    # This check must precede every network operation and outcome calculation.
    rule = load_decision_rule(rule_path)
    assert_frozen(rule)
    frozen_at = now or datetime.now(UTC)
    if frozen_at.tzinfo is None:
        raise ValueError("evaluation timestamp must be timezone-aware")
    manifest = load_manifest()
    origins = load_evaluation_origins(window=window, origin_dates=origin_dates, include_prospective=True)
    if origin_dates and set(origin_dates) != {origin.origin_date for origin in origins}:
        raise ValueError("requested origin is unknown or outside selected window")
    inputs = fetch_inputs(manifest, fetch=fetch)
    primary, estimated = primary_returns(inputs, frozen_at.date())
    sessions = [day for day in inputs.sessions() if day < frozen_at.date()]
    config = {
        "suite_version": SUITE_VERSION,
        "as_of_date": frozen_at.date().isoformat(),
        "rule_hash": rule.rule_hash,
        "rule": canonical_rule(rule),
        "origins": [o.origin_date for o in origins],
        "window": window,
        "manifest_hash": content_hash(manifest),
        "origin_inventory_hash": sha256_hex((PACKAGE_ROOT / "data/fixtures/origins.csv").read_bytes()),
        "code_hash": content_hash(
            {
                p.name: sha256_hex(p.read_bytes())
                for p in (
                    Path(__file__),
                    Path(__file__).with_name("origins.py"),
                    Path(__file__).parents[1] / "collect/benchmarks.py",
                    Path(__file__).parents[1] / "collect/benchmark_sources.py",
                    Path(__file__).parents[1] / "valuation/actions.py",
                )
            }
        ),
        "source_hashes": {s["source_id"]: s.get("sha256") for s in inputs.sources},
        "holding_period_sessions": rule.holding_period_trading_days,
        "entry": "close of first observed session after cutoff date in America/New_York",
        "exit": "close 63 sessions after entry; no shortening at next origin",
        "overlap": "independent windows; arithmetic summaries only",
        "calendar": "union of observed FRED prices and dated Ken French sessions; no forward-filled prices/returns",
        "benchmark_vintage": "latest retrieved outcomes only; not used as forecast inputs",
    }
    skipped = {"status": "not_run", "reason": VISA_REASON, "metrics": None}
    rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    windows: list[tuple[date, date]] = []
    for origin in origins:
        if not origin.scored:
            exclusions.append(
                {
                    "origin_date": origin.origin_date,
                    "reason": origin.exclusion_reason or "Prospective origin; not scored.",
                }
            )
            continue
        row: dict[str, Any] = {
            "origin_date": origin.origin_date,
            "cutoff_ts": origin.cutoff_ts.isoformat(),
            "label": origin.label,
            "entry_date": None,
            "exit_date": None,
            "benchmarks": {},
            "visa_buy_and_hold": {**skipped, "label": manifest["labels"]["visa"]},
            "visa_strategy": dict(skipped),
            "excess_vs_visa": None,
            "excess_vs_benchmarks": None,
        }
        try:
            days = select_window(sessions, origin.cutoff_ts, rule.holding_period_trading_days)
        except ValueError as exc:
            days = ()
            row["window_reason"] = str(exc)
        if days:
            row.update(entry_date=days[0].isoformat(), exit_date=days[-1].isoformat())
            windows.append((days[0], days[-1]))
        for key, values, label_key in (
            ("sp500_tr_approx", primary, "primary"),
            ("us_total_market_tr", inputs.french, "secondary"),
        ):
            daily = [values.get(day) for day in days[1:]]
            if not daily or any(value is None for value in daily):
                result: dict[str, Any] = {
                    "status": "unavailable",
                    "metrics": None,
                    "reason": "Incomplete session, price, return or full-month dividend coverage; see source status.",
                }
            else:
                metrics = return_metrics([value for value in daily if value is not None])
                result = {
                    "status": "ok",
                    "metrics": {**metrics, "average_invested_exposure": 1.0},
                    "estimated": key == "sp500_tr_approx" and any(day in estimated for day in days[1:]),
                }
            row["benchmarks"][key] = {**result, "label": manifest["labels"][label_key]}
        rows.append(row)
    aggregates: dict[str, Any] = {}
    for key in ("sp500_tr_approx", "us_total_market_tr"):
        successful = [row["benchmarks"][key] for row in rows if row["benchmarks"][key]["status"] == "ok"]
        aggregates[key] = {
            "n_scored": len(successful),
            "n_unavailable": len(rows) - len(successful),
            "n_estimated": sum(bool(item["estimated"]) for item in successful),
            "mean_return": mean(item["metrics"]["total_return"] for item in successful) if successful else None,
            "worst_window_drawdown": min(item["metrics"]["max_drawdown"] for item in successful)
            if successful
            else None,
        }
    dividends = parse_retained_visa_dividends()
    dividend_files = {item["path"]: sha256_hex((PACKAGE_ROOT / item["path"]).read_bytes()) for item in dividends}
    config["sec_dividend_source_hashes"] = dividend_files
    report: dict[str, Any] = {
        "suite_version": SUITE_VERSION,
        "label": EXPLORATORY,
        "rule_frozen_at": frozen_at.isoformat(),
        "config": config,
        "config_hash": content_hash(config),
        "labels": manifest["labels"],
        "sources": inputs.sources,
        "origins": rows,
        "n_eligible": len(rows),
        "n_excluded": len(exclusions),
        "exclusions": exclusions,
        "aggregates": aggregates,
        "overlap": overlap_counts(windows),
        "visa_strategy": {**skipped, "n_scored": 0},
        "visa_buy_and_hold": {**skipped, "n_scored": 0, "label": manifest["labels"]["visa"]},
        "sec_dividends": {
            "coverage": "partial",
            "scoring_ready": False,
            "declarations": dividends,
            "limitation": "Only retained LON-3 release declarations; not a complete dividend ledger. Missing declarations do not mean zero dividends. Ex-dates follow the LON-6 convention, not exchange-verified dates.",
        },
        "drift_diagnostic": drift_diagnostic(inputs, primary, min(w[0] for w in windows), max(w[1] for w in windows))
        if windows
        else {"status": "unavailable", "reason": "No complete holding windows.", "n_months": 0},
    }
    assert_frozen(load_decision_rule(rule_path))
    return report


def write_portfolio_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def format_portfolio_table(report: dict[str, Any]) -> str:
    lines = [
        report["label"],
        f"Eligible: {report['n_eligible']}; excluded: {report['n_excluded']}",
        "Origin | Entry | Exit | S&P approximation | US total market | Visa strategy",
    ]
    for row in report["origins"]:
        values = [
            f"{item['metrics']['total_return']:.2%}" + (" (estimated)" if item.get("estimated") else "")
            if item["status"] == "ok"
            else "unavailable"
            for item in row["benchmarks"].values()
        ]
        lines.append(
            " | ".join([row["origin_date"], row["entry_date"] or "—", row["exit_date"] or "—", *values, "not run"])
        )
    lines.extend(
        [
            report["labels"]["primary"],
            report["labels"]["primary_footnote"],
            report["labels"]["secondary"],
            report["labels"]["visa"],
        ]
    )
    return "\n".join(lines)
