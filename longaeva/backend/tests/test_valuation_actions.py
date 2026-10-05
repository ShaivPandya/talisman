"""Illustrative actions, costs, and the decision rule (LON-26 / FR-13)."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import numpy.typing as npt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.api.schemas import ParameterEvidence, ParameterSetCreate
from longaeva_app.db.models import ParameterSet, Scenario
from longaeva_app.hashing import content_hash
from longaeva_app.runs.inputs import (
    default_parameter_ranges,
    default_parameter_values,
    parse_aware_utc,
    resolve_fixture_by_origin_date,
)
from longaeva_app.storage.local import LocalArtifactStore
from longaeva_app.valuation.actions import (
    CONFIG_PATH,
    GAP_LABEL,
    REFERENCE_PRICE_LABEL,
    DecisionRule,
    DecisionRuleError,
    canonical_rule,
    decide,
    evaluate_actions,
    execution_costs,
    load_decision_rule,
    override_reference_price,
    parse_decision_rule,
    reference_price,
    target_shares,
    traded_notional,
)
from longaeva_app.valuation.bridge import ValuationResult, value_bridge
from longaeva_app.valuation.multiples import MultipleBand, load_history, override_band, parse_utc
from longaeva_app.worker.queue import claim_next_job, execute_job

# SHA-256 of the parsed committed rule. Comments in the YAML are not hashed.
EXPECTED_RULE_HASH = "d93e2e052b7dbc75f00c4691e8afa464ac54c8d5a9bde602037767ec9dbd3039"
ORIGIN_CUTOFF = "2024-07-23T20:05:38Z"
_ORIGIN = "2024-07-23"
_N_PATHS = 32


def _cutoff() -> datetime:
    return parse_aware_utc(resolve_fixture_by_origin_date(_ORIGIN).cutoff_utc)


def _evidence_parameter_set(session: Session, cutoff: datetime) -> ParameterSet:
    """Same evidence parameter set as test_valuation_bridge.py."""
    values = default_parameter_values()
    obs_id = uuid4()
    links: dict[str, ParameterEvidence] = {}
    flags: dict[str, Any] = {}
    first = True
    for name in values:
        if not first:
            links[name] = ParameterEvidence(assumption=True, rationale="fixture assumption")
            flags[name] = True
        else:
            links[name] = ParameterEvidence(observation_ids=[obs_id])
            flags[name] = False
            first = False
    create = ParameterSetCreate(
        company="visa",
        cutoff_ts=cutoff,
        values=values,
        ranges=default_parameter_ranges(),
        evidence_links=links,
        assumption_flags=flags,
    )
    row = ParameterSet(
        company="visa",
        cutoff_ts=cutoff,
        values=create.values,
        ranges=create.ranges,
        evidence_links={key: link.model_dump(mode="json") for key, link in create.evidence_links.items()},
        assumption_flags=create.assumption_flags,
        content_hash=create.computed_content_hash(),
    )
    session.add(row)
    session.flush()
    return row


def _scenario(session: Session, param_set: ParameterSet) -> Scenario:
    row = Scenario(
        company="visa",
        name="test-baseline",
        parameter_set_id=param_set.id,
        interventions=[],
    )
    session.add(row)
    session.flush()
    return row


def _submit_and_execute(
    client: TestClient,
    test_engine: Engine,
    artifact_store: LocalArtifactStore,
    *,
    scenario_id: str,
    cutoff: datetime,
) -> dict[str, Any]:
    created = client.post(
        "/runs",
        json={
            "scenario_id": scenario_id,
            "cutoff_ts": cutoff.isoformat(),
            "seed": 7,
            "n_paths": _N_PATHS,
            "n_quarters": 4,
            "switches": {},
        },
    )
    assert created.status_code == 202, created.text
    payload = created.json()
    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    claimed = claim_next_job(factory, "test-worker")
    assert claimed is not None
    assert str(claimed) == payload["job_id"]
    execute_job(factory, claimed, "test-worker", artifact_store=artifact_store)
    fetched = client.get(f"/runs/{payload['id']}")
    assert fetched.status_code == 200
    result: dict[str, Any] = fetched.json()
    return result


def _paths(value: float, *, n_paths: int = 8, n_quarters: int = 4) -> npt.NDArray[np.float64]:
    return np.full((n_paths, n_quarters), value, dtype=np.float64)


def _bridge(
    paths: npt.NDArray[np.float64],
    *,
    tax_rate: float | None = 0.0,
    net_interest_other: float | None = 0.0,
    diluted_shares: float | None = 100.0,
    band: MultipleBand | None = None,
) -> ValuationResult:
    return value_bridge(
        paths,
        tax_rate=tax_rate,
        net_interest_other=net_interest_other,
        diluted_shares=diluted_shares,
        band=band if band is not None else override_band(10.0, 20.0, 30.0),
        assumption_sources={
            "tax_rate": "starting_state" if tax_rate is not None else "missing",
            "net_interest_other": "starting_state" if net_interest_other is not None else "missing",
            "diluted_shares": "starting_state" if diluted_shares is not None else "missing",
        },
    )


def _rule(**overrides: Any) -> DecisionRule:
    rule = load_decision_rule()
    if not overrides:
        return rule
    return replace(rule, **overrides)


def test_committed_rule_hash_and_defaults() -> None:
    rule = load_decision_rule()
    assert rule.rule_hash == EXPECTED_RULE_HASH
    assert rule.rule_hash == content_hash(canonical_rule(rule))
    assert rule.version == 1
    assert "illustrative" in rule.label.lower()
    assert rule.transaction_cost_bps == 1
    assert rule.slippage_bps == 3
    assert rule.market_impact_bps == 5
    assert rule.funding_bps_per_day == 0
    assert rule.exit_at_or_below == pytest.approx(-0.25)
    assert rule.trim_at_or_below == pytest.approx(-0.10)
    assert rule.add_at_or_above == pytest.approx(0.15)
    assert rule.add_fraction == pytest.approx(0.25)
    assert rule.trim_fraction == pytest.approx(0.25)
    assert rule.holding_period_trading_days == 63
    assert rule.demo_shares == 1000
    assert rule.direction == "long"


def test_comments_and_whitespace_do_not_change_the_hash(tmp_path: Path) -> None:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    rewritten = "# extra comment\n\n" + text + "\n\n# trailing\n"
    path = tmp_path / "decision_rule.yaml"
    path.write_text(rewritten, encoding="utf-8")
    assert load_decision_rule(path).rule_hash == EXPECTED_RULE_HASH


def test_rule_rejects_missing_unknown_and_bad_fields(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(DecisionRuleError, match="not found"):
        load_decision_rule(missing)

    broken = tmp_path / "broken.yaml"
    broken.write_text(":\n  :\n", encoding="utf-8")
    with pytest.raises(DecisionRuleError, match="parse"):
        load_decision_rule(broken)

    listed = tmp_path / "list.yaml"
    listed.write_text("- 1\n", encoding="utf-8")
    with pytest.raises(DecisionRuleError, match="mapping"):
        load_decision_rule(listed)

    with pytest.raises(DecisionRuleError, match="missing"):
        parse_decision_rule({"version": 1})
    with pytest.raises(DecisionRuleError, match="illustrative"):
        parse_decision_rule(_document(label="A fixed rule."))
    with pytest.raises(DecisionRuleError, match="exit_at_or_below"):
        parse_decision_rule(_document(exit_at_or_below=-0.05, trim_at_or_below=-0.25))
    with pytest.raises(DecisionRuleError, match="add_fraction"):
        parse_decision_rule(_document(add_fraction=1.5))
    with pytest.raises(DecisionRuleError, match="long"):
        parse_decision_rule(_document(direction="short"))
    with pytest.raises(DecisionRuleError, match="unknown"):
        raw = _document()
        raw["note"] = "extra"
        parse_decision_rule(raw)


def test_cost_components_match_the_talisman_fixture() -> None:
    # 10 shares at 100, add 500 notional, 10 bps each of transaction, slippage, impact.
    rule = _rule(
        transaction_cost_bps=10.0,
        slippage_bps=10.0,
        market_impact_bps=10.0,
        funding_bps_per_day=0.0,
    )
    assert traded_notional("add", 10, 15, 100) == pytest.approx(500)
    costs = execution_costs(500, "add", rule)
    assert costs.transaction_cost == pytest.approx(0.5)
    assert costs.slippage_cost == pytest.approx(0.5)
    assert costs.market_impact_cost == pytest.approx(0.5)
    assert costs.funding_cost == pytest.approx(0.0)
    assert costs.total_cost == pytest.approx(1.5)
    assert costs.total_cost_bps == pytest.approx(30)

    assert traded_notional("hold", 10, 10, 100) == 0
    held = execution_costs(0, "hold", rule)
    assert held.total_cost == 0
    assert held.transaction_cost == 0

    assert traded_notional("exit", 10, 0, 100) == pytest.approx(1000)
    exited = execution_costs(1000, "exit", rule)
    assert exited.total_cost == pytest.approx(3.0)
    assert exited.funding_cost == 0


def test_funding_applies_only_to_added_notional() -> None:
    rule = _rule(
        transaction_cost_bps=10.0,
        slippage_bps=10.0,
        market_impact_bps=10.0,
        funding_bps_per_day=1.5,
        holding_period_trading_days=10,
    )
    added = execution_costs(500, "add", rule)
    # 500 * 1.5 bps * 10 days / 10_000 = 0.75, plus 1.5 of explicit friction.
    assert added.funding_cost == pytest.approx(0.75)
    assert added.total_cost == pytest.approx(2.25)
    assert added.total_cost_bps == pytest.approx(45)

    trimmed = execution_costs(500, "trim", rule)
    assert trimmed.funding_cost == 0
    assert trimmed.total_cost == pytest.approx(1.5)
    exited = execution_costs(500, "exit", rule)
    assert exited.funding_cost == 0
    assert exited.total_cost == pytest.approx(1.5)


def test_sizing_scales_the_position_and_trim_stops_at_zero() -> None:
    rule = load_decision_rule()
    assert target_shares("hold", 1000, rule) == pytest.approx(1000)
    assert target_shares("add", 1000, rule) == pytest.approx(1250)
    assert target_shares("trim", 1000, rule) == pytest.approx(750)
    assert target_shares("exit", 1000, rule) == 0
    assert target_shares("trim", 1000, _rule(trim_fraction=2.0)) == 0
    assert traded_notional("trim", 1000, 750, 100) == pytest.approx(25_000)
    assert traded_notional("exit", 1000, 0, 100) == pytest.approx(100_000)


def test_thresholds_are_inclusive() -> None:
    rule = load_decision_rule()
    assert decide(rule.exit_at_or_below, rule) == "exit"
    assert decide(math.nextafter(rule.exit_at_or_below, 0.0), rule) == "trim"
    assert decide(rule.trim_at_or_below, rule) == "trim"
    assert decide(math.nextafter(rule.trim_at_or_below, 0.0), rule) == "hold"
    assert decide(0.0, rule) == "hold"
    assert decide(math.nextafter(rule.add_at_or_above, 0.0), rule) == "hold"
    assert decide(rule.add_at_or_above, rule) == "add"

    # Constant paths: forward EPS 10, mid multiple 20, value per share 200.
    valuation = _bridge(_paths(250.0))
    assert _decision_at(valuation, 100.0) == "add"
    assert _decision_at(valuation, 200.0) == "hold"
    assert _decision_at(valuation, 230.0) == "trim"
    assert _decision_at(valuation, 400.0) == "exit"


def test_value_gap_uses_target_shares_and_separated_points() -> None:
    rule = load_decision_rule()
    valuation = _bridge(_paths(250.0))
    result = evaluate_actions(valuation, override_reference_price(100.0), 1000, rule)
    assert result.status == "ok"
    assert result.decision == "add"
    assert result.margin == pytest.approx(1.0)
    assert result.value_per_share == pytest.approx(200.0)
    names = [row.action for row in result.actions]
    assert names == ["hold", "add", "trim", "exit"]
    hold = result.actions[0]
    assert hold.is_no_action
    assert hold.selected is False
    assert hold.costs is not None
    assert hold.costs.total_cost == 0

    added = result.actions[1]
    assert added.selected
    assert added.target_shares == pytest.approx(1250)
    assert added.costs is not None
    assert added.costs.traded_notional == pytest.approx(25_000)
    assert added.costs.total_cost == pytest.approx(22.5)
    assert added.gaps is not None
    by_name = {gap.name: gap for gap in added.gaps}
    assert set(by_name) == {"earnings_p10", "earnings_p50", "earnings_p90", "multiple_low", "multiple_high"}
    # Mid multiple on flat paths: p10 = p50 = p90 = 200. Low/high multiples: 100 and 300.
    assert by_name["earnings_p50"].net_gap == pytest.approx(1250 * (200.0 - 100.0) - 22.5)
    assert by_name["multiple_low"].value_per_share == pytest.approx(100.0)
    assert by_name["multiple_high"].value_per_share == pytest.approx(300.0)
    assert by_name["earnings_p50"].label == GAP_LABEL


def test_unsupported_bridge_and_missing_price_are_no_action() -> None:
    rule = load_decision_rule()
    paths = _paths(100.0, n_paths=4)
    paths[0, :] = -500.0
    unsupported = _bridge(paths)
    price = override_reference_price(100.0)
    result = evaluate_actions(unsupported, price, 1000, rule)
    assert result.status == "unsupported"
    assert result.reason is not None
    assert "non-positive" in result.reason
    assert result.decision == "hold"
    assert result.margin is None
    assert result.value_per_share is None
    assert result.reference == price
    hold = result.actions[0]
    assert hold.is_no_action and hold.selected
    assert hold.costs is None
    assert hold.gaps is None
    assert all(row.costs is None for row in result.actions)

    missing = evaluate_actions(_bridge(_paths(250.0)), None, 1000, rule)
    assert missing.status == "unsupported"
    assert missing.decision == "hold"
    assert missing.reference is None
    assert missing.reason is not None
    assert "reference price" in missing.reason.lower()
    assert "invented" in missing.reason.lower()


def test_reference_price_uses_the_latest_buyback_average_at_the_cutoff() -> None:
    rows = load_history()
    price = reference_price(parse_utc(ORIGIN_CUTOFF), rows=rows)
    assert price is not None
    assert price.period_label == "FY2024Q2"
    assert price.price == pytest.approx(280.80)
    assert price.source == "sec_buyback_average"
    assert price.source_label == REFERENCE_PRICE_LABEL
    assert "not a market close" in price.source_label
    current = next(row for row in rows if row.period_label == "FY2024Q3")
    assert current.price_acceptance_utc > parse_utc(ORIGIN_CUTOFF)
    assert reference_price(parse_utc("2020-01-01T00:00:00Z"), rows=rows) is None

    override = override_reference_price(100.0)
    assert override.source == "request_override"
    assert "not a market close" in override.source_label.lower()
    with pytest.raises(DecisionRuleError):
        override_reference_price(0.0)


def test_labels_say_illustrative() -> None:
    rule = load_decision_rule()
    result = evaluate_actions(
        _bridge(_paths(250.0)),
        override_reference_price(200.0),
        rule.demo_shares,
        rule,
    )
    assert "illustrative" in result.label.lower()
    assert result.decision == "hold"
    for row in result.actions:
        assert "illustrative" in row.label.lower()
        assert row.gaps is not None
        for gap in row.gaps:
            assert "illustrative" in gap.label.lower()
            assert "probability" in gap.label.lower()
    hold = result.actions[0]
    assert "no-action" in hold.label.lower()
    assert hold.selected


def test_decision_rule_endpoint_returns_the_pinned_hash() -> None:
    from longaeva_app.api.main import app

    with TestClient(app) as client:
        response = client.get("/valuation/decision-rule")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rule_hash"] == EXPECTED_RULE_HASH
    assert body["version"] == 1
    assert body["holding_period_trading_days"] == 63
    assert body["costs"]["transaction_cost_bps"] == 1
    assert body["costs"]["funding_bps_per_day"] == 0
    assert body["thresholds"]["add_at_or_above"] == pytest.approx(0.15)
    assert body["demo_position"]["shares"] == 1000
    assert body["demo_position"]["direction"] == "long"
    assert "illustrative" in body["label"].lower()


@pytest.mark.db
def test_api_actions_ok_override_unsupported_and_errors(
    client: TestClient,
    test_engine: Engine,
    db_session: Session,
    artifact_store: LocalArtifactStore,
) -> None:
    cutoff = _cutoff()
    param_set = _evidence_parameter_set(db_session, cutoff)
    scenario = _scenario(db_session, param_set)
    db_session.commit()

    missing = client.post("/valuation/actions", json={"run_id": str(uuid4())})
    assert missing.status_code == 404

    row = _submit_and_execute(
        client,
        test_engine,
        artifact_store,
        scenario_id=str(scenario.id),
        cutoff=cutoff,
    )
    assert row["status"] == "succeeded"

    valued = client.post("/valuation/actions", json={"run_id": row["id"]})
    assert valued.status_code == 200, valued.text
    body = valued.json()
    assert body["status"] == "ok"
    assert body["rule"]["rule_hash"] == EXPECTED_RULE_HASH
    assert "illustrative" in body["label"].lower()
    assert body["position"]["shares"] == 1000
    assert body["position"]["source"] == "decision_rule"
    assert body["position"]["direction"] == "long"
    assert body["reference_price"]["source"] == "sec_buyback_average"
    assert body["reference_price"]["period_label"] == "FY2024Q2"
    assert body["reference_price"]["source_label"] == REFERENCE_PRICE_LABEL
    assert body["bridge"]["status"] == "ok"
    price = body["reference_price"]["price"]
    assert body["value_per_share"] == pytest.approx(body["bridge"]["earnings_driven"]["value_per_share"]["p50"])
    assert body["margin"] == pytest.approx(body["value_per_share"] / price - 1.0)
    assert body["decision"] == decide(body["margin"], load_decision_rule())
    assert [item["action"] for item in body["actions"]] == ["hold", "add", "trim", "exit"]
    selected = [item for item in body["actions"] if item["selected"]]
    assert len(selected) == 1
    assert selected[0]["action"] == body["decision"]
    hold = body["actions"][0]
    assert hold["is_no_action"] is True
    assert "no-action" in hold["label"]
    assert hold["costs"]["total_cost"] == 0
    added = body["actions"][1]
    assert added["target_shares"] == pytest.approx(1250)
    assert added["costs"]["funding_cost"] == 0
    assert added["costs"]["traded_notional"] == pytest.approx(250 * price)
    assert added["costs"]["transaction_cost"] == pytest.approx(added["costs"]["traded_notional"] * 1 / 10_000)
    assert added["costs"]["slippage_cost"] == pytest.approx(added["costs"]["traded_notional"] * 3 / 10_000)
    assert added["costs"]["market_impact_cost"] == pytest.approx(added["costs"]["traded_notional"] * 5 / 10_000)
    assert added["costs"]["total_cost"] == pytest.approx(added["costs"]["traded_notional"] * 9 / 10_000)
    gap = next(item for item in added["gaps"] if item["name"] == "earnings_p50")
    assert "illustrative" in gap["label"].lower()
    assert gap["net_gap"] == pytest.approx(
        added["target_shares"] * (body["value_per_share"] - price) - added["costs"]["total_cost"]
    )
    for item in body["actions"]:
        assert "illustrative" in item["label"].lower()

    overridden = client.post(
        "/valuation/actions",
        json={"run_id": row["id"], "shares": 10, "reference_price": 100},
    )
    assert overridden.status_code == 200, overridden.text
    custom = overridden.json()
    assert custom["status"] == "ok"
    assert custom["position"]["source"] == "request_override"
    assert custom["position"]["shares"] == 10
    assert custom["reference_price"]["source"] == "request_override"
    assert custom["reference_price"]["price"] == 100
    assert "not a market close" in custom["reference_price"]["source_label"].lower()
    assert custom["rule"]["rule_hash"] == EXPECTED_RULE_HASH

    blocked_value = client.post(
        "/valuation/actions",
        json={"run_id": row["id"], "multiple_range": {"low": 30, "mid": 10, "high": 20}},
    )
    assert blocked_value.status_code == 200, blocked_value.text
    refused = blocked_value.json()
    assert refused["status"] == "unsupported"
    assert refused["bridge"]["status"] == "unsupported"
    assert refused["decision"] == "hold"
    assert refused["margin"] is None
    assert refused["value_per_share"] is None
    assert refused["actions"][0]["costs"] is None
    assert refused["reference_price"]["period_label"] == "FY2024Q2"

    queued = client.post(
        "/runs",
        json={
            "scenario_id": str(scenario.id),
            "cutoff_ts": cutoff.isoformat(),
            "seed": 7,
            "n_paths": 32,
            "n_quarters": 4,
            "switches": {},
        },
    )
    assert queued.status_code == 202, queued.text
    blocked = client.post("/valuation/actions", json={"run_id": queued.json()["id"]})
    assert blocked.status_code == 409

    zero_shares = client.post("/valuation/actions", json={"run_id": row["id"], "shares": 0})
    assert zero_shares.status_code == 422
    zero_price = client.post("/valuation/actions", json={"run_id": row["id"], "reference_price": 0})
    assert zero_price.status_code == 422


def _decision_at(valuation: ValuationResult, price: float) -> str:
    result = evaluate_actions(valuation, override_reference_price(price), 1000, load_decision_rule())
    assert result.status == "ok"
    return result.decision


def _document(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "version": 1,
        "label": "Illustrative test rule.",
        "costs": {
            "transaction_cost_bps": 1,
            "slippage_bps": 3,
            "market_impact_bps": 5,
            "funding_bps_per_day": 0,
        },
        "thresholds": {
            "exit_at_or_below": -0.25,
            "trim_at_or_below": -0.10,
            "add_at_or_above": 0.15,
        },
        "sizing": {"add_fraction": 0.25, "trim_fraction": 0.25},
        "holding_period_trading_days": 63,
        "demo_position": {"shares": 1000, "direction": "long"},
    }
    if "label" in overrides:
        raw["label"] = overrides["label"]
    if "direction" in overrides:
        position = dict(raw["demo_position"])
        position["direction"] = overrides["direction"]
        raw["demo_position"] = position
    if "add_fraction" in overrides:
        sizing = dict(raw["sizing"])
        sizing["add_fraction"] = overrides["add_fraction"]
        raw["sizing"] = sizing
    if "exit_at_or_below" in overrides or "trim_at_or_below" in overrides:
        thresholds = dict(raw["thresholds"])
        if "exit_at_or_below" in overrides:
            thresholds["exit_at_or_below"] = overrides["exit_at_or_below"]
        if "trim_at_or_below" in overrides:
            thresholds["trim_at_or_below"] = overrides["trim_at_or_below"]
        raw["thresholds"] = thresholds
    return raw
