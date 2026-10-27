"""Parse IBKR Flex Query Open Positions XML into portfolio position rows."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Any

from portfolio.instruments import (
    build_option_contract_symbol,
    display_ticker,
    futures_spec,
    normalize_option_type,
    normalize_portfolio_instrument_row,
    parse_occ_symbol,
    position_row_id,
)
from portfolio.position_groups import normalize_group_name

SUPPORTED_ASSET_CATEGORIES = {"STK", "OPT", "FUT"}
PRESERVED_METADATA_FIELDS = ("conviction", "contrarian", "group_name", "group_conviction")
DEFAULT_CONVICTION = 3
IBKR_FLEX_INDEX_HEDGE_TICKERS = frozenset({"SPY", "IWM", "QQQ"})


def _attr(row: ET.Element, name: str) -> str:
    return str(row.attrib.get(name) or "").strip()


def _optional_float(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _ibkr_expiry_to_iso(value: str) -> str | None:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        year = int(text[:4])
        month = int(text[4:6])
        day = int(text[6:8])
        return date(year, month, day).isoformat()
    if len(text) == 10 and text[4] == "-":
        return date.fromisoformat(text).isoformat()
    return None


def _normalize_direction(side: str, quantity: float | None) -> str:
    side_text = side.strip().lower()
    if side_text == "short":
        return "short"
    if side_text == "long":
        return "long"
    if quantity is not None and quantity < 0:
        return "short"
    return "long"


def _abs_quantity(value: float | None) -> float | None:
    if value is None:
        return None
    return abs(value)


def _compact_ibkr_option_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace(" ", "")


def _option_type_from_put_call(value: str) -> str | None:
    raw = str(value or "").strip().upper()
    if raw in {"C", "CALL"}:
        return "call"
    if raw in {"P", "PUT"}:
        return "put"
    return normalize_option_type(raw)


def _parse_open_position_row(
    element: ET.Element, *, base_currency: str | None = None, as_of: str | None = None
) -> dict[str, Any] | None:
    asset_category = _attr(element, "assetCategory").upper()
    if asset_category not in SUPPORTED_ASSET_CATEGORIES:
        return None

    raw_quantity = _optional_float(_attr(element, "position"))
    if raw_quantity is None:
        raise ValueError("Open position has missing or invalid quantity.")
    direction = _normalize_direction(_attr(element, "side"), raw_quantity)
    quantity = _abs_quantity(raw_quantity)
    currency = _attr(element, "currency") or None
    exchange = _attr(element, "listingExchange") or None
    fx_rate = _optional_float(_attr(element, "fxRateToBase"))
    cost_basis = _optional_float(_attr(element, "costBasisPrice"))
    base_currency = base_currency or (currency if fx_rate == 1 else None)
    if currency and currency == base_currency:
        fx_rate = 1.0
    if fx_rate is not None and fx_rate <= 0:
        raise ValueError("FX rate to base must be positive.")

    def in_base(name: str) -> float | None:
        value = _optional_float(_attr(element, name))
        return value * fx_rate if value is not None and fx_rate is not None else None

    cost_basis_base = in_base("costBasisMoney")
    notional_base = in_base("positionValue")
    report_date = _ibkr_expiry_to_iso(_attr(element, "reportDate")) or as_of

    base_row: dict[str, Any] = {
        "asset": "equity",
        "direction": direction,
        "contrarian": False,
        "conviction": DEFAULT_CONVICTION,
        "cost_basis": cost_basis,
        "shares": quantity,
        "quantity": quantity,
        "currency": currency,
        "exchange": exchange,
        "base_currency": base_currency,
        "fx_rate_to_base": fx_rate,
        "fx_rate_as_of": report_date,
        "cost_basis_base": cost_basis_base,
        "notional_base": notional_base,
        "source": "ibkr_flex",
        "as_of": report_date,
        "broker_mark_price": _optional_float(_attr(element, "markPrice")),
        "broker_unrealized_pnl_base": in_base("fifoPnlUnrealized"),
        "valuation_status": "ok" if currency and fx_rate else "missing_fx_rate",
        "ibkr_lots": [],
    }

    if asset_category == "STK":
        ticker = _attr(element, "symbol").upper()
        if not ticker:
            raise ValueError("STK row missing symbol.")
        base_row.update(
            {
                "ticker": ticker,
                "instrument_type": "security",
                "price_symbol": ticker,
                "contract_multiplier": 1,
            }
        )
        return base_row

    if asset_category == "FUT":
        ticker = _attr(element, "symbol").upper().replace(" ", "")
        match = re.fullmatch(r"(.+?)[FGHJKMNQUVXZ]\d{1,4}", ticker)
        root_symbol = _attr(element, "underlyingSymbol").upper() or (match.group(1) if match else ticker)
        spec = futures_spec(root_symbol)
        multiplier = _optional_float(_attr(element, "multiplier"))
        if multiplier is None and spec:
            multiplier = spec.contract_multiplier
        if not ticker or multiplier is None:
            raise ValueError("Futures row requires a symbol and known or explicit multiplier.")
        base_row.update(
            ticker=ticker,
            instrument_type="future",
            price_symbol=f"{root_symbol}=F",
            contract_multiplier=multiplier,
            asset=spec.asset if spec else "commodity",
        )
        return base_row

    underlying = _attr(element, "underlyingSymbol").upper()
    expiry = _ibkr_expiry_to_iso(_attr(element, "expiry"))
    strike = _optional_float(_attr(element, "strike"))
    option_type = _option_type_from_put_call(_attr(element, "putCall"))
    multiplier = _optional_float(_attr(element, "multiplier")) or 100.0
    compact_symbol = _compact_ibkr_option_symbol(_attr(element, "symbol"))
    parsed_occ = parse_occ_symbol(compact_symbol)

    if not underlying and parsed_occ is not None:
        underlying = parsed_occ.underlying_ticker
    if expiry is None and parsed_occ is not None:
        expiry = parsed_occ.option_expiration
    if strike is None and parsed_occ is not None:
        strike = parsed_occ.option_strike
    if option_type is None and parsed_occ is not None:
        option_type = parsed_occ.option_type

    if not underlying or expiry is None or strike is None or option_type is None:
        raise ValueError(f"Option row missing required fields: symbol={_attr(element, 'symbol')!r}.")

    contract_symbol = build_option_contract_symbol(underlying, expiry, option_type, strike)
    base_row.update(
        {
            "ticker": underlying,
            "underlying_ticker": underlying,
            "instrument_type": "option",
            "price_symbol": contract_symbol,
            "option_contract_symbol": contract_symbol,
            "option_expiration": expiry,
            "option_strike": strike,
            "option_type": option_type,
            "contract_multiplier": multiplier,
        }
    )
    return base_row


@dataclass(frozen=True)
class FlexStatement:
    positions: list[dict[str, Any]]
    as_of: str | None
    base_currency: str | None
    net_liquidation: float | None
    cash_balances: list[dict[str, Any]]


def parse_ibkr_flex_statement(payload: bytes | str) -> FlexStatement:
    """Read one account statement, retaining lots without counting summaries twice."""
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else str(payload)
    if not text.strip():
        raise ValueError("Uploaded Flex XML is empty.")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("Flex XML must not contain document types or entities.")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("Invalid Flex XML.") from exc
    statements = list(root.iter("FlexStatement"))
    if len(statements) > 1:
        raise ValueError("Configure a single-account, single-day Flex query.")
    statement = statements[0] if statements else root
    dates = {_ibkr_expiry_to_iso(_attr(row, "reportDate")) for row in statement.iter("OpenPosition")}
    dates.discard(None)
    if len(dates) > 1:
        raise ValueError("Flex query contains multiple position report dates.")
    as_of = next(iter(dates), None) or _ibkr_expiry_to_iso(_attr(statement, "toDate"))
    info = next(statement.iter("AccountInformation"), statement)
    base_currency = _attr(info, "baseCurrency") or _attr(info, "currency") or None
    if not base_currency:
        base_candidates = {
            _attr(row, "currency")
            for row in statement.iter("OpenPosition")
            if _optional_float(_attr(row, "fxRateToBase")) == 1
        }
        if len(base_candidates) == 1:
            base_currency = base_candidates.pop()
    grouped: dict[str, list[tuple[ET.Element, dict[str, Any]]]] = {}
    for element in statement.iter("OpenPosition"):
        parsed = _parse_open_position_row(element, base_currency=base_currency, as_of=as_of)
        if parsed is None:
            # Ignore zero balances, but never propose a partial replacement of a book.
            if _optional_float(_attr(element, "position")) != 0:
                raise ValueError(f"Unsupported open position asset category: {_attr(element, 'assetCategory')}.")
            continue
        if not parsed["quantity"]:
            continue
        row = normalize_portfolio_instrument_row(parsed)
        row["position_id"] = position_row_id(row)
        grouped.setdefault(row["position_id"], []).append((element, row))
    rows = []
    for position_id, entries in grouped.items():
        summaries = [row for element, row in entries if _attr(element, "levelOfDetail").upper() != "LOT"]
        lots = [(element, row) for element, row in entries if _attr(element, "levelOfDetail").upper() == "LOT"]
        if len(summaries) > 1 or len({row["direction"] for _, row in entries}) > 1:
            raise ValueError(f"Duplicate position_id in Flex import: {position_id}.")
        row = dict(summaries[0] if summaries else entries[0][1])
        if not summaries:
            quantity = sum(lot["quantity"] for _, lot in lots)
            row["quantity"] = row["shares"] = quantity
            for field in ("cost_basis_base", "notional_base", "broker_unrealized_pnl_base"):
                values = [lot[field] for _, lot in lots]
                row[field] = sum(values) if all(v is not None for v in values) else None
            costs = [lot["cost_basis"] for _, lot in lots]
            row["cost_basis"] = (
                sum(lot["cost_basis"] * lot["quantity"] for _, lot in lots) / quantity
                if all(v is not None for v in costs)
                else None
            )
        if summaries and lots and not math.isclose(sum(lot["quantity"] for _, lot in lots), row["quantity"]):
            raise ValueError(f"Lot quantities do not match summary for {position_id}.")
        lot_ids = [_attr(element, "originatingTransactionID") for element, _ in lots]
        nonempty_ids = [lot_id for lot_id in lot_ids if lot_id]
        if len(nonempty_ids) != len(set(nonempty_ids)):
            raise ValueError(f"Duplicate lot in Flex import: {position_id}.")
        row["ibkr_lots"] = [
            {
                "open_date": _ibkr_expiry_to_iso(_attr(element, "openDateTime").split(";")[0]),
                "quantity": lot["quantity"],
                "cost_basis": lot["cost_basis"],
                "lot_id": _attr(element, "originatingTransactionID") or None,
            }
            for element, lot in lots
        ]
        rows.append(row)
    if not rows:
        raise ValueError("No supported STK/OPT/FUT open positions found in Flex XML.")
    nav_rows = list(statement.iter("EquitySummaryByReportDateInBase"))
    if not nav_rows:
        nav_rows = [row for row in statement.iter("EquitySummaryInBase") if "total" in row.attrib]
    nav_values = [
        _optional_float(_attr(row, "total"))
        for row in nav_rows
        if not as_of or not _attr(row, "reportDate") or _ibkr_expiry_to_iso(_attr(row, "reportDate")) == as_of
    ]
    nav = nav_values[0] if len(nav_values) == 1 else None
    if len(nav_values) > 1:
        raise ValueError("Ambiguous net liquidation values in Flex statement.")
    balances = []
    for element in statement.iter("CashReportCurrency"):
        currency = _attr(element, "currency")
        if not currency or currency == "BASE_SUMMARY":
            continue
        amount = _optional_float(_attr(element, "endingCash"))
        if amount is not None:
            balances.append(
                {
                    "currency": currency,
                    "balance": amount,
                    "settled_cash": _optional_float(_attr(element, "endingSettledCash")),
                }
            )
    return FlexStatement(rows, as_of, base_currency, nav, balances)


def parse_ibkr_flex_open_positions_xml(payload: bytes | str) -> list[dict[str, Any]]:
    """Compatibility entry point for manual XML uploads."""
    return parse_ibkr_flex_statement(payload).positions


def _leg_conviction(row: dict[str, Any]) -> int:
    value = row.get("conviction")
    if value is None:
        return DEFAULT_CONVICTION
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CONVICTION
    return max(1, min(5, parsed))


def _representative_metadata_leg(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Prefer a leg carrying a group, then highest conviction."""
    current_grouped = bool(normalize_group_name(current.get("group_name")))
    candidate_grouped = bool(normalize_group_name(candidate.get("group_name")))
    if candidate_grouped and not current_grouped:
        return candidate
    if current_grouped and not candidate_grouped:
        return current
    return candidate if _leg_conviction(candidate) > _leg_conviction(current) else current


def _index_existing_by_underlying(existing_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_underlying: dict[str, dict[str, Any]] = {}
    for row in existing_rows:
        if str(row.get("role") or "position").lower() == "hedge":
            continue
        key = display_ticker(row)
        if not key:
            continue
        existing = by_underlying.get(key)
        by_underlying[key] = _representative_metadata_leg(existing, row) if existing else row
    return by_underlying


def merge_preserved_portfolio_metadata(
    imported_rows: list[dict[str, Any]],
    existing_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve app-only metadata from existing rows when position_id matches."""
    existing_by_id: dict[str, dict[str, Any]] = {}
    for row in existing_rows:
        if str(row.get("role") or "position").lower() == "hedge":
            continue
        key = position_row_id(row)
        if key:
            existing_by_id[key] = row
    existing_by_underlying = _index_existing_by_underlying(existing_rows)

    merged: list[dict[str, Any]] = []
    for row in imported_rows:
        out = dict(row)
        existing = existing_by_id.get(position_row_id(out))
        if existing is None:
            underlying_key = display_ticker(out)
            if underlying_key:
                existing = existing_by_underlying.get(underlying_key)
        if existing:
            for field in PRESERVED_METADATA_FIELDS:
                if field in existing and existing.get(field) is not None:
                    out[field] = existing[field]
        else:
            out.setdefault("conviction", DEFAULT_CONVICTION)
            out.setdefault("contrarian", False)
            out.setdefault("group_name", None)
            out.setdefault("group_conviction", None)
        merged.append(out)
    return merged


def is_ibkr_flex_index_hedge_row(row: dict[str, Any]) -> bool:
    """True when a Flex row should be staged as a hedge (short index ETF security)."""
    ticker = str(row.get("ticker") or "").strip().upper()
    direction = str(row.get("direction") or "").strip().lower()
    instrument_type = str(row.get("instrument_type") or "security").strip().lower()
    return instrument_type == "security" and direction == "short" and ticker in IBKR_FLEX_INDEX_HEDGE_TICKERS


def split_ibkr_flex_import_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split parsed Flex rows into portfolio positions and hedge positions."""
    portfolio_rows: list[dict[str, Any]] = []
    hedge_rows: list[dict[str, Any]] = []
    for row in rows:
        if is_ibkr_flex_index_hedge_row(row):
            hedge_rows.append(row)
        else:
            portfolio_rows.append(row)
    return portfolio_rows, hedge_rows


def merge_ibkr_flex_hedge_replacement(
    imported_hedge_rows: list[dict[str, Any]],
    existing_hedge_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build full hedge replacement payload: imported rows replace matches; others preserved."""
    imported_by_id: dict[str, dict[str, Any]] = {}
    for row in imported_hedge_rows:
        key = position_row_id(row)
        if key:
            imported_by_id[key] = row

    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for existing in existing_hedge_rows:
        key = position_row_id(existing)
        if not key or key in seen_ids:
            continue
        if key in imported_by_id:
            merged.append(dict(imported_by_id[key]))
            seen_ids.add(key)
        else:
            if existing.get("source") != "ibkr_flex":
                merged.append(dict(existing))
            seen_ids.add(key)

    for key, row in imported_by_id.items():
        if key not in seen_ids:
            merged.append(dict(row))
            seen_ids.add(key)

    return merged
