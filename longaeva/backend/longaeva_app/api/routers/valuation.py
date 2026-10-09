"""Earnings/multiple valuation bridge and illustrative actions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from longaeva_app.api.deps import get_artifact_store
from longaeva_app.api.schemas import (
    ActionRowRead,
    AssumptionRead,
    CostComponentsRead,
    DecisionRuleCostsRead,
    DecisionRuleRead,
    DecisionRuleSizingRead,
    DecisionRuleThresholdsRead,
    DemoPositionRead,
    EarningsDrivenRead,
    EpsComponentRead,
    ForwardEpsRead,
    MultipleBandRead,
    MultipleDrivenRead,
    MultipleRangeInput,
    OuterEnvelopeRead,
    PeHistoryRowRead,
    PositionRead,
    ReferencePriceRead,
    ValuationActionsRead,
    ValuationActionsRequest,
    ValuationBridgeRead,
    ValuationBridgeRequest,
    ValuationMultiplesRead,
    ValueCellRead,
    ValueGapRead,
)
from longaeva_app.db.models import Run
from longaeva_app.db.session import get_db
from longaeva_app.engine.outputs import load_npz_arrays
from longaeva_app.storage.local import LocalArtifactStore
from longaeva_app.valuation.actions import (
    ActionsResult,
    DecisionRule,
    DecisionRuleError,
    ReferencePrice,
    evaluate_actions,
    load_decision_rule,
    override_reference_price,
    reference_price,
)
from longaeva_app.valuation.bridge import OPERATING_PROFIT_METRIC, ValuationResult, value_bridge
from longaeva_app.valuation.multiples import (
    METHOD_LABEL,
    MIN_BAND_QUARTERS,
    PRICE_ANCHOR,
    SOURCE_BASIS,
    MultipleBand,
    PeHistoryError,
    PeQuarter,
    as_utc,
    eligible_rows,
    load_history,
    override_band,
    pe_band,
)

router = APIRouter(prefix="/valuation", tags=["valuation"])

_FAR_FUTURE = datetime(9999, 1, 1, tzinfo=UTC)


def _state_float(state: dict[str, Any], key: str) -> float | None:
    raw = state.get(key)
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _resolve(override: float | None, state_value: float | None) -> tuple[float | None, str]:
    if override is not None:
        return override, "request_override"
    if state_value is not None:
        return state_value, "starting_state"
    return None, "missing"


def _band_read(band: MultipleBand | None) -> MultipleBandRead | None:
    if band is None:
        return None
    return MultipleBandRead(
        low=band.low,
        mid=band.mid,
        high=band.high,
        n_quarters=band.n_quarters,
        window_start=band.window_start,
        window_end=band.window_end,
        source=band.source,
        source_label=band.source_label,
        method_label=band.method_label,
        periods=list(band.periods),
    )


def _row_read(row: PeQuarter) -> PeHistoryRowRead:
    return PeHistoryRowRead(
        period_label=row.period_label,
        period_end=row.period_end,
        avg_purchase_price=row.avg_purchase_price,
        price_source_id=row.price_source_id,
        price_form=row.price_form,
        price_acceptance_utc=row.price_acceptance_utc,
        price_url=row.price_url,
        price_quote=row.price_quote,
        price_char_start=row.price_char_start,
        price_char_end=row.price_char_end,
        price_anchor=PRICE_ANCHOR,
        ttm_eps=row.ttm_eps,
        trailing_pe=row.trailing_pe,
        eps_components=[
            EpsComponentRead(
                period_label=component.period_label,
                value=component.value,
                source_id=component.source_id,
                acceptance_utc=component.acceptance_utc,
            )
            for component in row.eps_components
        ],
    )


def _bridge_read(run: Run, result: ValuationResult) -> ValuationBridgeRead:
    forward = None
    if result.forward_eps is not None:
        forward = ForwardEpsRead(
            mean=result.forward_eps.mean,
            p10=result.forward_eps.p10,
            p50=result.forward_eps.p50,
            p90=result.forward_eps.p90,
            n_paths=result.forward_eps.n_paths,
        )
    earnings = None
    if result.earnings_driven is not None:
        earnings = EarningsDrivenRead(
            multiple=result.earnings_driven.multiple,
            value_per_share=result.earnings_driven.value_per_share,
            equity_usd_millions=result.earnings_driven.equity_usd_millions,
            spread_per_share=result.earnings_driven.spread_per_share,
            spread_equity_usd_millions=result.earnings_driven.spread_equity_usd_millions,
        )
    multiple = None
    if result.multiple_driven is not None:
        multiple = MultipleDrivenRead(
            forward_eps=result.multiple_driven.forward_eps,
            value_per_share=result.multiple_driven.value_per_share,
            equity_usd_millions=result.multiple_driven.equity_usd_millions,
            spread_per_share=result.multiple_driven.spread_per_share,
            spread_equity_usd_millions=result.multiple_driven.spread_equity_usd_millions,
        )
    envelope = None
    if result.outer_envelope is not None:
        envelope = OuterEnvelopeRead(
            low_per_share=result.outer_envelope.low_per_share,
            high_per_share=result.outer_envelope.high_per_share,
            low_equity_usd_millions=result.outer_envelope.low_equity_usd_millions,
            high_equity_usd_millions=result.outer_envelope.high_equity_usd_millions,
            label=result.outer_envelope.label,
        )
    grid = None
    if result.grid is not None:
        grid = [
            ValueCellRead(
                eps_quantile=cell.eps_quantile,
                multiple_role=cell.multiple_role,
                multiple=cell.multiple,
                value_per_share=cell.value_per_share,
                equity_usd_millions=cell.equity_usd_millions,
            )
            for cell in result.grid
        ]
    return ValuationBridgeRead(
        status=result.status,
        reason=result.reason,
        run_id=run.id,
        cutoff_ts=run.cutoff_ts,
        metric=OPERATING_PROFIT_METRIC,
        n_paths=result.n_paths,
        n_quarters=result.n_quarters,
        assumptions=[
            AssumptionRead(name=item.name, value=item.value, unit=item.unit, source=item.source)
            for item in result.assumptions
        ],
        forward_eps=forward,
        multiple_band=_band_read(result.band),
        grid=grid,
        earnings_driven=earnings,
        multiple_driven=multiple,
        outer_envelope=envelope,
    )


def _load_fixture_history() -> tuple[PeQuarter, ...]:
    try:
        return load_history()
    except PeHistoryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


def _load_run_paths(
    session: Session,
    store: LocalArtifactStore,
    run_id: Any,
) -> tuple[Run, Any]:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status != "succeeded":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run has not succeeded")
    if run.outputs_path is None or not store.exists(run.outputs_path):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run is missing path outputs")
    metrics, _states, _periods = load_npz_arrays(store.read_bytes(run.outputs_path))
    operating_profit = metrics.get(OPERATING_PROFIT_METRIC)
    if operating_profit is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run paths are missing {OPERATING_PROFIT_METRIC}",
        )
    return run, operating_profit


def _result_for_run(
    run: Run,
    operating_profit: Any,
    *,
    tax_rate: float | None,
    net_interest_other: float | None,
    diluted_shares: float | None,
    multiple_range: MultipleRangeInput | None,
) -> ValuationResult:
    state = run.starting_state if isinstance(run.starting_state, dict) else {}
    tax, tax_source = _resolve(tax_rate, _state_float(state, "tax_rate"))
    other, other_source = _resolve(net_interest_other, _state_float(state, "net_interest_other"))
    shares, shares_source = _resolve(diluted_shares, _state_float(state, "diluted_shares"))
    if multiple_range is not None:
        band: MultipleBand | None = override_band(multiple_range.low, multiple_range.mid, multiple_range.high)
    else:
        band = pe_band(as_utc(run.cutoff_ts), rows=_load_fixture_history())
    return value_bridge(
        operating_profit,
        tax_rate=tax,
        net_interest_other=other,
        diluted_shares=shares,
        band=band,
        assumption_sources={
            "tax_rate": tax_source,
            "net_interest_other": other_source,
            "diluted_shares": shares_source,
        },
    )


def _rule_read(rule: DecisionRule) -> DecisionRuleRead:
    return DecisionRuleRead(
        version=rule.version,
        label=rule.label,
        rule_hash=rule.rule_hash,
        costs=DecisionRuleCostsRead(
            transaction_cost_bps=rule.transaction_cost_bps,
            slippage_bps=rule.slippage_bps,
            market_impact_bps=rule.market_impact_bps,
            funding_bps_per_day=rule.funding_bps_per_day,
        ),
        thresholds=DecisionRuleThresholdsRead(
            exit_at_or_below=rule.exit_at_or_below,
            trim_at_or_below=rule.trim_at_or_below,
            add_at_or_above=rule.add_at_or_above,
        ),
        sizing=DecisionRuleSizingRead(
            add_fraction=rule.add_fraction,
            trim_fraction=rule.trim_fraction,
        ),
        holding_period_trading_days=rule.holding_period_trading_days,
        demo_position=DemoPositionRead(shares=rule.demo_shares, direction=rule.direction),
    )


def _actions_read(
    run: Run,
    bridge: ValuationBridgeRead,
    result: ActionsResult,
    *,
    position_source: Literal["decision_rule", "request_override"],
    rule: DecisionRule,
) -> ValuationActionsRead:
    reference = None
    if result.reference is not None:
        reference = ReferencePriceRead(
            price=result.reference.price,
            period_label=result.reference.period_label,
            acceptance_utc=result.reference.acceptance_utc,
            source=result.reference.source,
            source_label=result.reference.source_label,
            price_source_id=result.reference.price_source_id,
            price_quote=result.reference.price_quote,
        )
    rows: list[ActionRowRead] = []
    for row in result.actions:
        costs = None
        if row.costs is not None:
            costs = CostComponentsRead(
                traded_notional=row.costs.traded_notional,
                transaction_cost=row.costs.transaction_cost,
                slippage_cost=row.costs.slippage_cost,
                market_impact_cost=row.costs.market_impact_cost,
                funding_cost=row.costs.funding_cost,
                total_cost=row.costs.total_cost,
                total_cost_bps=row.costs.total_cost_bps,
            )
        gaps = None
        if row.gaps is not None:
            gaps = [
                ValueGapRead(
                    name=gap.name,
                    value_per_share=gap.value_per_share,
                    net_gap=gap.net_gap,
                    label=gap.label,
                )
                for gap in row.gaps
            ]
        rows.append(
            ActionRowRead(
                action=row.action,
                label=row.label,
                is_no_action=row.is_no_action,
                selected=row.selected,
                target_shares=row.target_shares,
                costs=costs,
                gaps=gaps,
            )
        )
    return ValuationActionsRead(
        status=result.status,
        reason=result.reason,
        label=result.label,
        run_id=run.id,
        bridge=bridge,
        reference_price=reference,
        position=PositionRead(shares=result.shares, direction=result.direction, source=position_source),
        rule=_rule_read(rule),
        decision=result.decision,
        margin=result.margin,
        value_per_share=result.value_per_share,
        actions=rows,
    )


def _loaded_rule() -> DecisionRule:
    try:
        return load_decision_rule()
    except DecisionRuleError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/bridge", response_model=ValuationBridgeRead)
def post_bridge(
    body: ValuationBridgeRequest,
    session: Session = Depends(get_db),
    store: LocalArtifactStore = Depends(get_artifact_store),
) -> ValuationBridgeRead:
    run, operating_profit = _load_run_paths(session, store, body.run_id)
    result = _result_for_run(
        run,
        operating_profit,
        tax_rate=body.tax_rate,
        net_interest_other=body.net_interest_other,
        diluted_shares=body.diluted_shares,
        multiple_range=body.multiple_range,
    )
    return _bridge_read(run, result)


@router.post("/actions", response_model=ValuationActionsRead)
def post_actions(
    body: ValuationActionsRequest,
    session: Session = Depends(get_db),
    store: LocalArtifactStore = Depends(get_artifact_store),
) -> ValuationActionsRead:
    run, operating_profit = _load_run_paths(session, store, body.run_id)
    valuation = _result_for_run(
        run,
        operating_profit,
        tax_rate=body.tax_rate,
        net_interest_other=body.net_interest_other,
        diluted_shares=body.diluted_shares,
        multiple_range=body.multiple_range,
    )
    rule = _loaded_rule()
    price: ReferencePrice | None
    if body.reference_price is not None:
        try:
            price = override_reference_price(body.reference_price)
        except DecisionRuleError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    else:
        try:
            price = reference_price(as_utc(run.cutoff_ts))
        except PeHistoryError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    position_source: Literal["decision_rule", "request_override"]
    if body.shares is None:
        position_shares = rule.demo_shares
        position_source = "decision_rule"
    else:
        position_shares = body.shares
        position_source = "request_override"
    try:
        actions = evaluate_actions(valuation, price, position_shares, rule)
    except DecisionRuleError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _actions_read(run, _bridge_read(run, valuation), actions, position_source=position_source, rule=rule)


@router.get("/decision-rule", response_model=DecisionRuleRead)
def get_decision_rule() -> DecisionRuleRead:
    return _rule_read(_loaded_rule())


@router.get("/multiples", response_model=ValuationMultiplesRead)
def get_multiples(
    cutoff_ts: datetime | None = Query(default=None),
) -> ValuationMultiplesRead:
    history = _load_fixture_history()
    if cutoff_ts is None:
        rows = history
        band = pe_band(_FAR_FUTURE, rows=history)
        echoed: datetime | None = None
    else:
        cutoff = as_utc(cutoff_ts)
        rows = eligible_rows(cutoff, rows=history)
        band = pe_band(cutoff, rows=history)
        echoed = cutoff
    bridge_status: Literal["ok", "unsupported"]
    if band is None:
        reason = (
            f"Fewer than {MIN_BAND_QUARTERS} quarters have a price filing and trailing EPS "
            "releases accepted at or before the cutoff."
        )
        bridge_status = "unsupported"
    else:
        reason = None
        bridge_status = "ok"
    return ValuationMultiplesRead(
        status=bridge_status,
        reason=reason,
        cutoff_ts=echoed,
        source_basis=SOURCE_BASIS,
        method_label=METHOD_LABEL,
        rows=[_row_read(row) for row in rows],
        band=_band_read(band),
    )


__all__ = ["router"]
