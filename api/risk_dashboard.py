"""Durable portfolio risk dashboard contracts and refresh orchestration."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from api.portfolio_settings import DEFAULT_PORTFOLIO_BOOK_SIZE, get_configured_portfolio_book_size
from api.serializers import serialize_value
from api.snapshot_keys import SNAPSHOT_PORTFOLIO_RISK_DASHBOARD
from api.snapshot_store import get_snapshot_response, write_snapshot_failure, write_snapshot_success
from ontology.runtime_read_service import OntologyRuntimeReadService
from portfolio.risk_dashboard import aggregate_view, build_rows, load_market_inputs
from utils.market_freshness import evaluate_source_freshness, expected_market_date


class RiskDashboardPosition(BaseModel):
    position_id: str
    ticker: str
    underlying_ticker: str
    price_symbol: str
    asset: str | None = None
    sector: str | None = None
    group_name: str | None = None
    role: Literal["position", "hedge"]
    instrument_type: str
    direction: str
    quantity: float | None = None
    contract_multiplier: float | None = None
    currency: str | None = None
    price: float | None = None
    price_as_of: str | None = None
    fx_rate_to_usd: float | None = None
    fx_as_of: str | None = None
    exposure_multiplier: float
    signed_notional: float | None = None
    gross_notional: float | None = None
    weight_pct: float | None = None
    premium_usd: float | None = None
    option_type: str | None = None
    option_strike: float | None = None
    option_expiration: str | None = None
    beta_eligible: bool
    beta_status: str
    beta_spy: float | None = None
    beta_iwm: float | None = None
    beta_spy_observations: int = 0
    beta_iwm_observations: int = 0
    beta_spy_as_of: str | None = None
    beta_iwm_as_of: str | None = None
    beta_contribution_spy: float | None = None
    beta_contribution_iwm: float | None = None
    risk_score: float | None = None
    risk_level: str | None = None
    drivers: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class RiskExposureSummary(BaseModel):
    long_usd: float | None
    short_usd: float | None
    gross_usd: float | None
    net_usd: float | None
    long_pct: float | None
    short_pct: float | None
    gross_pct: float | None
    net_pct: float | None


class RiskExposureBucket(BaseModel):
    name: str
    gross_usd: float
    net_usd: float
    gross_share_pct: float | None
    position_count: int


class RiskBetaAggregate(BaseModel):
    primary: float | None
    hedges: float | None
    combined: float | None
    covered_count: int
    eligible_count: int
    covered_gross_pct: float | None


class RiskCoverage(BaseModel):
    position_count: int
    linear_count: int
    valued_linear_count: int
    option_count: int
    priced_option_count: int
    classification_gap_count: int


class RiskDashboardView(BaseModel):
    summary: RiskExposureSummary
    breakdowns: dict[str, list[RiskExposureBucket]]
    betas: dict[str, RiskBetaAggregate]
    coverage: RiskCoverage


class PortfolioRiskDashboard(BaseModel):
    version: int = 1
    computed_at: str
    as_of: str | None
    base_currency: Literal["USD"] = "USD"
    book_size: float
    book_is_default: bool
    holdings_fingerprint: str
    quality: Literal["ok", "degraded"]
    positions: list[RiskDashboardPosition]
    views: dict[str, RiskDashboardView]
    stress: dict[str, Any] | None = None
    source_status: dict[str, Any]
    beta_method: dict[str, Any]
    freshness: dict[str, Any] = Field(default_factory=dict)
    snapshot_meta: dict[str, Any] = Field(default_factory=dict)


def dashboard_request() -> dict[str, Any]:
    rows = serialize_value(OntologyRuntimeReadService().positions(include_hedges=True))
    configured = get_configured_portfolio_book_size()
    return {
        "holdings": rows,
        "book_size": configured or DEFAULT_PORTFOLIO_BOOK_SIZE,
        "book_is_default": configured is None,
    }


def holdings_fingerprint(holdings: list[dict[str, Any]]) -> str:
    # Ignore temporal bookkeeping; portfolio edits and valuation inputs determine identity.
    fields = (
        "id",
        "position_id",
        "ticker",
        "underlying_ticker",
        "price_symbol",
        "asset",
        "sector",
        "direction",
        "quantity",
        "shares",
        "contract_multiplier",
        "currency",
        "group_name",
        "role",
        "instrument_type",
        "option_contract_symbol",
        "option_type",
        "option_strike",
        "option_expiration",
        "economic_underlying_ticker",
        "exposure_multiplier",
        "economic_exposure_factor",
    )
    normalized = [{field: row.get(field) for field in fields} for row in holdings]
    encoded = sorted(json.dumps(row, sort_keys=True, default=str) for row in normalized)
    return hashlib.sha256(json.dumps(encoded).encode()).hexdigest()


def dashboard_cache_key(payload: dict[str, Any]) -> str:
    return f"risk_dashboard:v1:{holdings_fingerprint(payload['holdings'])}:{payload['book_size']}:{payload['book_is_default']}:{expected_market_date().isoformat()}"


def latest_dashboard() -> dict[str, Any] | None:
    saved = get_snapshot_response(SNAPSHOT_PORTFOLIO_RISK_DASHBOARD)
    if saved is None:
        return None
    current = dashboard_request()
    result = copy.deepcopy(saved)
    snapshot_meta = result.pop("_meta", {}).get("snapshot", {})
    result["snapshot_meta"] = snapshot_meta
    market = evaluate_source_freshness(result.get("as_of"), policy="market_session", calendar_id="XNYS")
    holdings_changed = holdings_fingerprint(current["holdings"]) != result["holdings_fingerprint"]
    book_changed = (
        current["book_size"] != result["book_size"] or current["book_is_default"] != result["book_is_default"]
    )
    result["freshness"] = {
        "stale": holdings_changed or book_changed or not market.fresh or snapshot_meta.get("refresh_status") == "error",
        "holdings_changed": holdings_changed,
        "book_changed": book_changed,
        "market": market.to_dict(),
        "refresh_error": snapshot_meta.get("error"),
    }
    return PortfolioRiskDashboard.model_validate(result).model_dump(mode="json")


def compute_dashboard(payload: dict[str, Any]) -> dict[str, Any]:
    """Runs in the existing durable worker, never in a latest/dashboard read."""
    from api.position_risk import get_latest_portfolio_risk, refresh_portfolio_risk
    from portfolio.portfolio_optimizer.portfolio_analyzer import (
        BETA_EWMA_HALFLIFE_DAYS,
        BETA_METHOD,
        BETA_MIN_OBS,
        BETA_SHRINK_TO_ONE,
        LOOKBACK_DAYS,
    )

    now = datetime.now(UTC)
    holdings = payload["holdings"]
    book = float(payload["book_size"])
    try:
        inputs = (
            load_market_inputs(holdings, now=now)
            if holdings
            else {
                "close": pd.DataFrame(),
                "adjusted": pd.DataFrame(),
                "metadata": {},
                "currencies": {},
            }
        )
        stress_error = None
        try:
            stress = refresh_portfolio_risk()
        except Exception as exc:
            stress_error = str(exc)
            stress = get_latest_portfolio_risk()
        rows = build_rows(holdings, inputs, book, stress)
        views = {
            "all_holdings": aggregate_view(rows, book),
            "primary_positions": aggregate_view([row for row in rows if row["role"] != "hedge"], book),
        }
        if holdings and not any(row["signed_notional"] is not None or row["premium_usd"] is not None for row in rows):
            raise ValueError(
                "No holdings could be valued from daily closes; the prior risk snapshot has been retained."
            )
        dates = [row[key] for row in rows for key in ("price_as_of", "fx_as_of") if row[key]]
        as_of = min(dates) if dates else expected_market_date(now).isoformat()
        incomplete = any(
            row["issues"] or (row["beta_eligible"] and (row["beta_spy"] is None or row["beta_iwm"] is None))
            for row in rows
        )
        result = PortfolioRiskDashboard.model_validate(
            {
                "computed_at": now.isoformat(),
                "as_of": as_of,
                "book_size": book,
                "book_is_default": payload["book_is_default"],
                "holdings_fingerprint": holdings_fingerprint(holdings),
                "quality": "degraded"
                if incomplete or stress_error or (stress or {}).get("quality") == "degraded"
                else "ok",
                "positions": rows,
                "views": views,
                "stress": stress,
                "source_status": {
                    "prices": {"provider": "yfinance", "basis": "daily_close", "as_of": as_of},
                    "portfolio": {"provider": "ontology", "as_of": now.isoformat()},
                    "stress": {
                        "error": stress_error,
                        "as_of": (stress or {}).get("as_of"),
                        "quality": (stress or {}).get("quality", "missing"),
                    },
                },
                "beta_method": {
                    "method": BETA_METHOD,
                    "lookback_days": LOOKBACK_DAYS,
                    "halflife_observations": BETA_EWMA_HALFLIFE_DAYS,
                    "minimum_observations": BETA_MIN_OBS,
                    "shrink_to_one": BETA_SHRINK_TO_ONE,
                },
            }
        ).model_dump(mode="json")
        write_snapshot_success(SNAPSHOT_PORTFOLIO_RISK_DASHBOARD, result, as_of_date=as_of, version=1)
        return result
    except Exception as exc:
        write_snapshot_failure(SNAPSHOT_PORTFOLIO_RISK_DASHBOARD, str(exc), version=1)
        raise
