"""Reconcile broker statements through the existing human-approval boundary."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from api.portfolio_settings import get_configured_portfolio_book_size, normalize_portfolio_book_size
from api.snapshot_store import read_snapshot, write_snapshot_failure, write_snapshot_success
from ontology.policy import system_actor
from portfolio.ibkr_flex_import import (
    FlexStatement,
    merge_ibkr_flex_hedge_replacement,
    merge_preserved_portfolio_metadata,
    parse_ibkr_flex_statement,
    split_ibkr_flex_import_rows,
)
from utils.market_freshness import MARKET_TIMEZONE, previous_market_session

SNAPSHOT_KEY = "ibkr_flex:statement"
# Marks and statement dates refresh independently of changes to the approved book.
HOLDING_FIELDS = (
    "ticker",
    "asset",
    "direction",
    "cost_basis",
    "quantity",
    "instrument_type",
    "price_symbol",
    "contract_multiplier",
    "position_id",
    "currency",
    "underlying_ticker",
    "option_contract_symbol",
    "option_expiration",
    "option_strike",
    "option_type",
    "contrarian",
    "conviction",
    "group_name",
    "group_conviction",
)


def _same_holdings(left: list[dict], right: list[dict], model) -> bool:
    def canonical(rows):
        normalized = [model(**row).model_dump() for row in rows]
        return sorted(
            ({key: row.get(key) for key in HOLDING_FIELDS} for row in normalized),
            key=lambda row: str(row["position_id"] or row["ticker"]),
        )

    return canonical(left) == canonical(right)


def stage_flex_statement(
    statement: FlexStatement,
    *,
    actor,
    read_service,
    stage,
    filename=None,
    reason=None,
    scheduled: bool = False,
    pending: list[dict] | None = None,
) -> dict[str, Any]:
    # Import lazily to keep the manual route and scheduled job on exactly the same validation path.
    from api.routers.portfolio_edit import HedgePosition, PortfolioPosition

    portfolio, hedges = split_ibkr_flex_import_rows(statement.positions)
    existing = read_service.positions(include_hedges=False)
    merged = merge_preserved_portfolio_metadata(portfolio, existing)
    positions = [PortfolioPosition(**row).model_dump() for row in merged]
    existing_hedges = read_service.list_objects("HedgePosition", limit=1000) if scheduled or hedges else []
    hedge_rows = [
        HedgePosition(**row).model_dump() for row in merge_ibkr_flex_hedge_replacement(hedges, existing_hedges)
    ]
    nav = None
    if statement.net_liquidation is not None:
        if statement.base_currency != "USD":
            raise ValueError("NAV book-size proposals require a USD-base statement.")
        nav = normalize_portfolio_book_size(statement.net_liquidation)
    proposals = []

    def propose(action, payload, suffix, model=None):
        if scheduled:
            for approval in pending or []:
                if approval.get("action_id") != action:
                    continue
                prior = approval.get("proposed_change") or {}
                if approval.get("base_state_hash"):
                    from ontology.action_registry import compute_action_base_state_hash

                    if compute_action_base_state_hash(action, prior) != approval["base_state_hash"]:
                        continue
                matches = (
                    _same_holdings(payload["positions"], prior.get("positions", []), model)
                    if model
                    else prior.get("book_size") == payload.get("book_size")
                )
                if matches:
                    proposals.append(
                        {
                            "approval_id": approval["id"],
                            "action_id": action,
                            "entity_type": approval.get("entity_type"),
                            "status": "pending_approval_reused",
                        }
                    )
                    return
        proposals.append(
            stage(
                action,
                payload,
                source_id=f"portfolio_edit.import_ibkr_flex_{suffix}",
                actor=actor,
                reason=reason or f"Reconcile IBKR Flex statement {statement.as_of or filename or 'upload.xml'}",
                apply=False,
                validation_status_code=400,
            )
        )

    if not scheduled or not _same_holdings(positions, existing, PortfolioPosition):
        propose("update_portfolio_positions", {"positions": positions}, "portfolio_positions", PortfolioPosition)
    if (hedges or scheduled) and not _same_holdings(hedge_rows, existing_hedges, HedgePosition):
        propose("update_hedge_positions", {"positions": hedge_rows}, "hedge_positions", HedgePosition)
    if nav is not None and nav != get_configured_portfolio_book_size():
        propose(
            "update_portfolio_settings",
            {
                "book_size": nav,
                "source": "ibkr_flex",
                "as_of": statement.as_of,
                "base_currency": statement.base_currency,
            },
            "settings",
        )
    return {
        **(proposals[0] if proposals else {"status": "unchanged"}),
        "staged_proposals": proposals,
        "import_summary": {
            "source": "ibkr_flex",
            "filename": filename,
            "as_of": statement.as_of,
            "imported_count": len(statement.positions),
            "portfolio_imported_count": len(portfolio),
            "hedge_imported_count": len(hedges),
            "hedge_tickers": sorted({r["ticker"] for r in hedges}),
            "preserved_metadata_count": sum(
                any(a.get(k) != b.get(k) for k in ("conviction", "contrarian", "group_name", "group_conviction"))
                for a, b in zip(portfolio, merged, strict=True)
            ),
        },
    }


def sync_ibkr_flex(_payload=None) -> dict[str, Any]:
    from api.action_execution import stage_api_action
    from ontology.command_service import OntologyCommandService
    from ontology.runtime_read_service import OntologyRuntimeReadService
    from portfolio.ibkr_flex_client import FlexClient

    try:
        statement = parse_ibkr_flex_statement(
            FlexClient(
                os.getenv("IBKR_FLEX_TOKEN", "").strip(), os.getenv("IBKR_FLEX_QUERY_ID", "").strip()
            ).fetch_statement()
        )
        if not statement.as_of:
            raise ValueError("Flex statement is missing its report date.")
        previous = read_snapshot(SNAPSHOT_KEY)
        today = datetime.now(MARKET_TIMEZONE).date()
        if statement.as_of > today.isoformat():
            raise ValueError("Flex statement report date is in the future.")
        if previous and previous.as_of_date and statement.as_of < previous.as_of_date:
            raise ValueError("Flex statement is older than the last successful sync.")
        expected = previous_market_session(today - timedelta(days=1)).isoformat()
        if statement.as_of < expected:
            raise ValueError(f"Flex statement is stale: {statement.as_of}; expected {expected} or later.")
        actor = system_actor("ibkr_flex")
        result = stage_flex_statement(
            statement,
            actor=actor,
            read_service=OntologyRuntimeReadService(),
            stage=stage_api_action,
            scheduled=True,
            pending=OntologyCommandService().list_approvals(status="pending", actor=actor, limit=1000),
        )
        write_snapshot_success(
            SNAPSHOT_KEY,
            {
                "source": "ibkr_flex",
                "as_of": statement.as_of,
                "base_currency": statement.base_currency,
                "positions": statement.positions,
                "cash_balances": statement.cash_balances,
                "net_liquidation": statement.net_liquidation,
                "last_success_at": datetime.now(UTC).isoformat(),
                "staged_proposals": result["staged_proposals"],
            },
            as_of_date=statement.as_of,
        )
        return result
    except Exception as exc:
        # Only our client/validation messages may be exposed. Third-party exceptions can contain credentials.
        from portfolio.ibkr_flex_client import FlexServiceError

        error = (
            str(exc)
            if isinstance(exc, (ValueError, FlexServiceError))
            else "IBKR Flex sync failed while staging the statement."
        )
        write_snapshot_failure(SNAPSHOT_KEY, error)
        raise RuntimeError(error) from None


def ibkr_flex_status() -> dict[str, Any]:
    record = read_snapshot(SNAPSHOT_KEY)
    payload = dict(record.payload or {}) if record else {}
    expected = previous_market_session(datetime.now(MARKET_TIMEZONE).date() - timedelta(days=1)).isoformat()
    stale = bool(record and (not record.as_of_date or record.as_of_date < expected))
    return {
        **payload,
        "configured": bool(os.getenv("IBKR_FLEX_TOKEN") and os.getenv("IBKR_FLEX_QUERY_ID")),
        "status": "failed"
        if record and record.status == "error"
        else "stale"
        if stale
        else "ok"
        if record
        else "never_synced",
        "stale": stale,
        "error": record.error if record else None,
        "expected_as_of": expected,
    }
