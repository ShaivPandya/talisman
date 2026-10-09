"""Illustrative hold/add/trim/exit actions with explicit costs.

Sizing and cost arithmetic are adapted from Talisman's
``portfolio/scenario_simulator.py`` (``_apply_delta``, ``_traded_notional``,
``_execution_friction``, lines 357–518). Adaptations:

- Only the percent-of-position path is kept. Add and trim scale the demo
  position by the fractions in the decision rule. Exit goes to zero shares.
- Funding applies only to added notional, over ``holding_period_trading_days``.
  Trim and exit pay transaction, slippage, and impact, not funding.
- The ADV participation cap, policy gate, ontology writeback, and scenario
  P&L are not carried over.

The decision compares p50 forward value per share (p50 EPS times the mid
multiple) with a reference price::

    margin = value_p50 / reference_price - 1

The default price is the latest SEC average repurchase price whose price
filing was accepted at or before the cutoff. It is a quarterly buyback
average, not a market close. Hold is the no-action outcome. An unsupported
bridge, or a cutoff with no repurchase price, stays a reason: no price and
no value are invented.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from longaeva_app.hashing import content_hash
from longaeva_app.valuation.bridge import ValuationResult
from longaeva_app.valuation.multiples import PeQuarter, as_utc, load_history, period_sort_key

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PACKAGE_ROOT / "config" / "decision_rule.yaml"

ActionName = Literal["hold", "add", "trim", "exit"]
PriceSource = Literal["sec_buyback_average", "request_override"]
Status = Literal["ok", "unsupported"]

ACTIONS: tuple[ActionName, ...] = ("hold", "add", "trim", "exit")
GAP_NAMES: tuple[str, ...] = (
    "earnings_p10",
    "earnings_p50",
    "earnings_p90",
    "multiple_low",
    "multiple_high",
)
REFERENCE_PRICE_LABEL = "quarterly buyback average, not a market close"
OVERRIDE_PRICE_LABEL = "Request override. Not a market close."
GAP_LABEL = "Illustrative. Not a probability."
NO_ACTION: ActionName = "hold"

_TOP_LEVEL = (
    "version",
    "label",
    "costs",
    "thresholds",
    "sizing",
    "holding_period_trading_days",
    "demo_position",
)
_COST_KEYS = (
    "transaction_cost_bps",
    "slippage_bps",
    "market_impact_bps",
    "funding_bps_per_day",
)
_THRESHOLD_KEYS = ("exit_at_or_below", "trim_at_or_below", "add_at_or_above")
_SIZING_KEYS = ("add_fraction", "trim_fraction")
_POSITION_KEYS = ("shares", "direction")


class DecisionRuleError(ValueError):
    """Raised when the decision-rule config or an action input is invalid."""


@dataclass(frozen=True, slots=True)
class DecisionRule:
    version: int
    label: str
    transaction_cost_bps: float
    slippage_bps: float
    market_impact_bps: float
    funding_bps_per_day: float
    exit_at_or_below: float
    trim_at_or_below: float
    add_at_or_above: float
    add_fraction: float
    trim_fraction: float
    holding_period_trading_days: int
    demo_shares: float
    direction: Literal["long"]
    rule_hash: str


@dataclass(frozen=True, slots=True)
class ReferencePrice:
    price: float
    period_label: str | None
    acceptance_utc: datetime | None
    source: PriceSource
    source_label: str
    price_source_id: str | None
    price_quote: str | None


@dataclass(frozen=True, slots=True)
class CostComponents:
    traded_notional: float
    transaction_cost: float
    slippage_cost: float
    market_impact_cost: float
    funding_cost: float
    total_cost: float
    total_cost_bps: float


@dataclass(frozen=True, slots=True)
class ValueGap:
    name: str
    value_per_share: float
    net_gap: float
    label: str


@dataclass(frozen=True, slots=True)
class ActionRow:
    action: ActionName
    label: str
    is_no_action: bool
    selected: bool
    target_shares: float | None
    costs: CostComponents | None
    gaps: tuple[ValueGap, ...] | None


@dataclass(frozen=True, slots=True)
class ActionsResult:
    status: Status
    reason: str | None
    label: str
    rule_version: int
    rule_hash: str
    decision: ActionName
    margin: float | None
    value_per_share: float | None
    reference: ReferencePrice | None
    shares: float
    direction: Literal["long"]
    actions: tuple[ActionRow, ...]


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _reject_keys(raw: Mapping[str, Any], allowed: tuple[str, ...], name: str) -> None:
    missing = [key for key in allowed if key not in raw]
    unknown = [key for key in raw if key not in allowed]
    if missing or unknown:
        raise DecisionRuleError(f"{name} keys must be {list(allowed)}; missing {missing}; unknown {unknown}.")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DecisionRuleError(f"{name} must be a mapping.")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionRuleError(f"{name} must be a number.")
    number = float(value)
    if not math.isfinite(number):
        raise DecisionRuleError(f"{name} must be finite.")
    return number


def _non_negative(value: Any, name: str) -> float:
    number = _finite(value, name)
    if number < 0.0:
        raise DecisionRuleError(f"{name} must be >= 0.")
    return number


def _fraction(value: Any, name: str) -> float:
    number = _finite(value, name)
    if not 0.0 < number <= 1.0:
        raise DecisionRuleError(f"{name} must be in (0, 1].")
    return number


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DecisionRuleError(f"{name} must be an integer.")
    if value < 0:
        raise DecisionRuleError(f"{name} must be >= 0.")
    return int(value)


def canonical_rule(rule: DecisionRule) -> dict[str, Any]:
    """Parsed rule values. Comments and key order are not part of the hash."""
    return {
        "version": rule.version,
        "label": rule.label,
        "costs": {
            "transaction_cost_bps": rule.transaction_cost_bps,
            "slippage_bps": rule.slippage_bps,
            "market_impact_bps": rule.market_impact_bps,
            "funding_bps_per_day": rule.funding_bps_per_day,
        },
        "thresholds": {
            "exit_at_or_below": rule.exit_at_or_below,
            "trim_at_or_below": rule.trim_at_or_below,
            "add_at_or_above": rule.add_at_or_above,
        },
        "sizing": {
            "add_fraction": rule.add_fraction,
            "trim_fraction": rule.trim_fraction,
        },
        "holding_period_trading_days": rule.holding_period_trading_days,
        "demo_position": {
            "shares": rule.demo_shares,
            "direction": rule.direction,
        },
    }


def parse_decision_rule(raw: Mapping[str, Any]) -> DecisionRule:
    """Validate a parsed rule document and attach its canonical hash."""
    _reject_keys(raw, _TOP_LEVEL, "decision rule")
    version = raw["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise DecisionRuleError("version must be 1.")
    label = raw["label"]
    if not isinstance(label, str) or not label.strip():
        raise DecisionRuleError("label must be a non-empty string.")
    if "illustrative" not in label.lower():
        raise DecisionRuleError("label must contain 'illustrative'.")

    costs = _mapping(raw["costs"], "costs")
    _reject_keys(costs, _COST_KEYS, "costs")
    thresholds = _mapping(raw["thresholds"], "thresholds")
    _reject_keys(thresholds, _THRESHOLD_KEYS, "thresholds")
    sizing = _mapping(raw["sizing"], "sizing")
    _reject_keys(sizing, _SIZING_KEYS, "sizing")
    position = _mapping(raw["demo_position"], "demo_position")
    _reject_keys(position, _POSITION_KEYS, "demo_position")

    exit_at = _finite(thresholds["exit_at_or_below"], "thresholds.exit_at_or_below")
    trim_at = _finite(thresholds["trim_at_or_below"], "thresholds.trim_at_or_below")
    add_at = _finite(thresholds["add_at_or_above"], "thresholds.add_at_or_above")
    if not exit_at < trim_at < 0.0 < add_at:
        raise DecisionRuleError("thresholds must satisfy exit_at_or_below < trim_at_or_below < 0 < add_at_or_above.")

    direction = position["direction"]
    if direction != "long":
        raise DecisionRuleError("demo_position.direction must be 'long'.")
    shares = _finite(position["shares"], "demo_position.shares")
    if shares <= 0.0:
        raise DecisionRuleError("demo_position.shares must be positive.")

    draft = DecisionRule(
        version=version,
        label=label,
        transaction_cost_bps=_non_negative(costs["transaction_cost_bps"], "costs.transaction_cost_bps"),
        slippage_bps=_non_negative(costs["slippage_bps"], "costs.slippage_bps"),
        market_impact_bps=_non_negative(costs["market_impact_bps"], "costs.market_impact_bps"),
        funding_bps_per_day=_non_negative(costs["funding_bps_per_day"], "costs.funding_bps_per_day"),
        exit_at_or_below=exit_at,
        trim_at_or_below=trim_at,
        add_at_or_above=add_at,
        add_fraction=_fraction(sizing["add_fraction"], "sizing.add_fraction"),
        trim_fraction=_fraction(sizing["trim_fraction"], "sizing.trim_fraction"),
        holding_period_trading_days=_non_negative_int(
            raw["holding_period_trading_days"], "holding_period_trading_days"
        ),
        demo_shares=shares,
        direction="long",
        rule_hash="",
    )
    return DecisionRule(
        version=draft.version,
        label=draft.label,
        transaction_cost_bps=draft.transaction_cost_bps,
        slippage_bps=draft.slippage_bps,
        market_impact_bps=draft.market_impact_bps,
        funding_bps_per_day=draft.funding_bps_per_day,
        exit_at_or_below=draft.exit_at_or_below,
        trim_at_or_below=draft.trim_at_or_below,
        add_at_or_above=draft.add_at_or_above,
        add_fraction=draft.add_fraction,
        trim_fraction=draft.trim_fraction,
        holding_period_trading_days=draft.holding_period_trading_days,
        demo_shares=draft.demo_shares,
        direction=draft.direction,
        rule_hash=content_hash(canonical_rule(draft)),
    )


def load_decision_rule(path: Path = CONFIG_PATH) -> DecisionRule:
    """Load and hash ``config/decision_rule.yaml``."""
    if not path.is_file():
        raise DecisionRuleError(f"Decision rule config not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DecisionRuleError(f"Decision rule config failed to parse: {exc}") from exc
    if not isinstance(loaded, dict):
        raise DecisionRuleError("Decision rule config must be a mapping.")
    return parse_decision_rule(loaded)


def reference_price(
    cutoff_ts: datetime,
    rows: tuple[PeQuarter, ...] | list[PeQuarter] | None = None,
) -> ReferencePrice | None:
    """Latest fiscal period whose repurchase-price filing was accepted by ``cutoff_ts``.

    Eligibility is the price filing alone. Trailing-EPS eligibility belongs to
    the multiple band. Returns ``None`` when nothing was public yet.
    """
    history = tuple(rows) if rows is not None else load_history()
    cutoff = as_utc(cutoff_ts)
    kept = [row for row in history if as_utc(row.price_acceptance_utc) <= cutoff]
    if not kept:
        return None
    latest = max(kept, key=lambda row: period_sort_key(row.period_label))
    return ReferencePrice(
        price=latest.avg_purchase_price,
        period_label=latest.period_label,
        acceptance_utc=as_utc(latest.price_acceptance_utc),
        source="sec_buyback_average",
        source_label=REFERENCE_PRICE_LABEL,
        price_source_id=latest.price_source_id,
        price_quote=latest.price_quote,
    )


def override_reference_price(price: float) -> ReferencePrice:
    """Caller-supplied price. It is not described as a market close."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        raise DecisionRuleError("reference_price must be a number.")
    number = float(price)
    if not math.isfinite(number) or number <= 0.0:
        raise DecisionRuleError(f"reference_price must be positive; got {price}.")
    return ReferencePrice(
        price=number,
        period_label=None,
        acceptance_utc=None,
        source="request_override",
        source_label=OVERRIDE_PRICE_LABEL,
        price_source_id=None,
        price_quote=None,
    )


def _action_label(action: ActionName) -> str:
    if action == NO_ACTION:
        return "Illustrative no-action outcome."
    return f"Illustrative {action}."


def target_shares(action: ActionName, shares: float, rule: DecisionRule) -> float:
    """Percent-of-position sizing. Adapted from ``_apply_delta``; never negative."""
    if action == "hold":
        return _round(shares)
    if action == "exit":
        return 0.0
    if action == "add":
        return _round(max(0.0, shares * (1.0 + abs(rule.add_fraction))))
    if action == "trim":
        return _round(max(0.0, shares * (1.0 - abs(rule.trim_fraction))))
    raise DecisionRuleError(f"Unknown action: {action}")


def traded_notional(action: ActionName, shares: float, target: float, price: float) -> float:
    """Dollars traded. Adapted from ``_traded_notional``. Hold trades nothing."""
    current = shares * price
    if action == "hold":
        return 0.0
    if action == "exit":
        return _round(current)
    return _round(abs(target * price - current))


def execution_costs(traded: float, action: ActionName, rule: DecisionRule) -> CostComponents:
    """Dollar costs of ``traded`` notional. Adapted from ``_execution_friction``.

    Funding is charged only when ``action`` is ``add``.
    """
    if traded <= 0.0:
        return CostComponents(
            traded_notional=0.0,
            transaction_cost=0.0,
            slippage_cost=0.0,
            market_impact_cost=0.0,
            funding_cost=0.0,
            total_cost=0.0,
            total_cost_bps=0.0,
        )
    transaction = traded * rule.transaction_cost_bps / 10_000.0
    slippage = traded * rule.slippage_bps / 10_000.0
    impact = traded * rule.market_impact_bps / 10_000.0
    funding = 0.0
    funding_bps = 0.0
    if action == "add":
        funding_bps = rule.funding_bps_per_day * float(rule.holding_period_trading_days)
        funding = traded * funding_bps / 10_000.0
    total_bps = rule.transaction_cost_bps + rule.slippage_bps + rule.market_impact_bps + funding_bps
    total = transaction + slippage + impact + funding
    return CostComponents(
        traded_notional=_round(traded),
        transaction_cost=_round(transaction),
        slippage_cost=_round(slippage),
        market_impact_cost=_round(impact),
        funding_cost=_round(funding),
        total_cost=_round(total),
        total_cost_bps=_round(total_bps),
    )


def decide(margin: float, rule: DecisionRule) -> ActionName:
    """Inclusive thresholds. Exit is tested before trim."""
    if margin <= rule.exit_at_or_below:
        return "exit"
    if margin <= rule.trim_at_or_below:
        return "trim"
    if margin >= rule.add_at_or_above:
        return "add"
    return "hold"


def _require_shares(shares: float) -> float:
    if isinstance(shares, bool) or not isinstance(shares, (int, float)):
        raise DecisionRuleError("shares must be a number.")
    number = float(shares)
    if not math.isfinite(number) or number <= 0.0:
        raise DecisionRuleError(f"shares must be positive; got {shares}.")
    return number


def _value_points(valuation: ValuationResult) -> dict[str, float] | None:
    earnings = valuation.earnings_driven
    multiple = valuation.multiple_driven
    if earnings is None or multiple is None:
        return None
    points = {
        "earnings_p10": earnings.value_per_share["p10"],
        "earnings_p50": earnings.value_per_share["p50"],
        "earnings_p90": earnings.value_per_share["p90"],
        "multiple_low": multiple.value_per_share["low"],
        "multiple_high": multiple.value_per_share["high"],
    }
    if any(not math.isfinite(value) or value <= 0.0 for value in points.values()):
        return None
    return points


def _unsupported(
    rule: DecisionRule,
    shares: float,
    *,
    reason: str,
    reference: ReferencePrice | None,
) -> ActionsResult:
    rows = tuple(
        ActionRow(
            action=action,
            label=_action_label(action),
            is_no_action=action == NO_ACTION,
            selected=action == NO_ACTION,
            target_shares=target_shares(action, shares, rule),
            costs=None,
            gaps=None,
        )
        for action in ACTIONS
    )
    return ActionsResult(
        status="unsupported",
        reason=reason,
        label=rule.label,
        rule_version=rule.version,
        rule_hash=rule.rule_hash,
        decision=NO_ACTION,
        margin=None,
        value_per_share=None,
        reference=reference,
        shares=shares,
        direction=rule.direction,
        actions=rows,
    )


def evaluate_actions(
    valuation: ValuationResult,
    reference: ReferencePrice | None,
    shares: float,
    rule: DecisionRule,
) -> ActionsResult:
    """Four illustrative rows plus the rule's decision.

    Hold is always present and is the no-action outcome. Costs and value gaps
    are omitted when the bridge is unsupported or no reference price exists.
    """
    position = _require_shares(shares)
    if valuation.status != "ok":
        reason = valuation.reason or "Valuation bridge is unsupported."
        return _unsupported(rule, position, reason=reason, reference=reference)
    points = _value_points(valuation)
    if points is None:
        return _unsupported(
            rule,
            position,
            reason=valuation.reason or "Valuation bridge did not produce a positive value per share.",
            reference=reference,
        )
    if reference is None:
        return _unsupported(
            rule,
            position,
            reason=(
                "No SEC average repurchase price was accepted at or before the cutoff. No reference price is invented."
            ),
            reference=None,
        )

    price = reference.price
    value_p50 = points["earnings_p50"]
    margin = value_p50 / price - 1.0
    decision = decide(margin, rule)
    rows: list[ActionRow] = []
    for action in ACTIONS:
        target = target_shares(action, position, rule)
        traded = traded_notional(action, position, target, price)
        costs = execution_costs(traded, action, rule)
        gaps = tuple(
            ValueGap(
                name=name,
                value_per_share=points[name],
                net_gap=_round(target * (points[name] - price) - costs.total_cost),
                label=GAP_LABEL,
            )
            for name in GAP_NAMES
        )
        rows.append(
            ActionRow(
                action=action,
                label=_action_label(action),
                is_no_action=action == NO_ACTION,
                selected=action == decision,
                target_shares=target,
                costs=costs,
                gaps=gaps,
            )
        )
    return ActionsResult(
        status="ok",
        reason=None,
        label=rule.label,
        rule_version=rule.version,
        rule_hash=rule.rule_hash,
        decision=decision,
        margin=margin,
        value_per_share=value_p50,
        reference=reference,
        shares=position,
        direction=rule.direction,
        actions=tuple(rows),
    )


__all__ = [
    "ACTIONS",
    "CONFIG_PATH",
    "GAP_LABEL",
    "GAP_NAMES",
    "NO_ACTION",
    "OVERRIDE_PRICE_LABEL",
    "REFERENCE_PRICE_LABEL",
    "ActionName",
    "ActionRow",
    "ActionsResult",
    "CostComponents",
    "DecisionRule",
    "DecisionRuleError",
    "ReferencePrice",
    "ValueGap",
    "canonical_rule",
    "decide",
    "evaluate_actions",
    "execution_costs",
    "load_decision_rule",
    "override_reference_price",
    "parse_decision_rule",
    "reference_price",
    "target_shares",
    "traded_notional",
]
