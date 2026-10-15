"""Measured portfolio exposure and market beta, independent of persistence/UI.

Option premiums are deliberately separate from linear economic exposure. No
cost-basis, conviction, equal-weight, or assumed-beta substitutes are used.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from portfolio.economic_exposure import resolve_economic_exposure
from portfolio.instruments import chart_price_symbol, direction_sign, display_ticker, futures_spec, position_row_id
from portfolio.valuation import fallback_market_metadata
from utils.fx import currency_lookup_and_unit_scale
from utils.market_freshness import expected_market_date
from utils.retry import yf_download, yf_ticker_info

BENCHMARKS = ("SPY", "IWM")


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def quote_symbol(row: Mapping[str, Any]) -> str:
    if row.get("instrument_type") == "option":
        # Never price an option with its underlying's share price.
        return str(row.get("option_contract_symbol") or "").strip().upper()
    return chart_price_symbol(row)


def beta_symbol(row: Mapping[str, Any]) -> str:
    exposure = resolve_economic_exposure(row)
    return exposure.underlying_ticker if exposure.is_mapped else chart_price_symbol(row)


def beta_eligible(row: Mapping[str, Any]) -> bool:
    if row.get("asset") != "equity":
        return False
    instrument = str(row.get("instrument_type") or "security")
    if instrument == "security":
        return True
    if instrument == "future":
        spec = futures_spec(chart_price_symbol(row))
        return spec is not None and spec.asset == "equity"
    return False


def _price_panel(raw: pd.DataFrame, symbols: list[str], field: str) -> pd.DataFrame:
    panel = pd.DataFrame(index=raw.index)
    for symbol in symbols:
        if isinstance(raw.columns, pd.MultiIndex):
            for key in ((field, symbol), (symbol, field)):
                if key in raw:
                    panel[symbol] = pd.to_numeric(raw[key], errors="coerce")
                    break
        elif len(symbols) == 1 and field in raw:
            panel[symbols[0]] = pd.to_numeric(raw[field], errors="coerce")
    return panel.sort_index().replace([np.inf, -np.inf], np.nan)


def load_market_inputs(holdings: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    """One bounded daily-price download, with share/contract marks and FX.

    The current unfinished daily bar is removed. Raw Close values price holdings;
    dividend/split-adjusted histories are used for return regressions.
    """
    from portfolio.portfolio_optimizer.portfolio_analyzer import LOOKBACK_DAYS

    symbols = {symbol for row in holdings if (symbol := quote_symbol(row))}
    metadata_symbols = {
        str(row.get("underlying_ticker") or display_ticker(row))
        if row.get("instrument_type") == "option"
        else quote_symbol(row)
        for row in holdings
    }
    metadata_symbols.update(beta_symbol(row) for row in holdings if beta_eligible(row))
    metadata_symbols.discard("")

    def metadata_for(symbol: str) -> tuple[str, dict[str, Any]]:
        fallback = fallback_market_metadata(symbol)
        try:
            info = yf_ticker_info(symbol, max_retries=1)
        except Exception:
            info = {}
        return symbol, {
            "currency": info.get("currency") or fallback.get("currency"),
            "sector": info.get("sector"),
        }

    with ThreadPoolExecutor(max_workers=min(8, len(metadata_symbols) or 1)) as pool:
        metadata = dict(pool.map(metadata_for, sorted(metadata_symbols)))
    currencies: dict[str, str | None] = {}
    for row in holdings:
        symbol = quote_symbol(row)
        lookup = (
            str(row.get("underlying_ticker") or display_ticker(row))
            if row.get("instrument_type") == "option"
            else symbol
        )
        currencies[symbol] = row.get("currency") or metadata.get(lookup, {}).get("currency")
    for row in holdings:
        if beta_eligible(row):
            symbol = beta_symbol(row)
            symbols.add(symbol)
            currencies.setdefault(symbol, metadata.get(symbol, {}).get("currency"))
    for benchmark in BENCHMARKS:
        symbols.add(benchmark)
        currencies[benchmark] = "USD"
    fx_symbols: set[str] = set()
    for currency in currencies.values():
        unit = currency_lookup_and_unit_scale(currency)
        if unit and unit[0] != "USD":
            fx_symbols.update((f"{unit[0]}USD=X", f"USD{unit[0]}=X"))
    symbols.update(fx_symbols)
    ordered = sorted(symbols)
    cutoff = expected_market_date(now)
    raw = yf_download(
        ordered,
        start=(cutoff - timedelta(days=LOOKBACK_DAYS)).isoformat(),
        end=(cutoff + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=True,
        max_retries=1,
    )
    if raw is None or raw.empty:
        raise ValueError("No daily closing prices were returned; the prior risk snapshot has been retained.")
    raw = raw[[pd.Timestamp(value).date() <= cutoff for value in raw.index]]
    close = _price_panel(raw, ordered, "Close")
    adjusted = _price_panel(raw, ordered, "Adj Close")
    # Some Yahoo instruments (notably futures) have no adjusted-close column.
    for symbol in ordered:
        if symbol not in adjusted or adjusted[symbol].dropna().empty:
            if symbol in close:
                adjusted[symbol] = close[symbol]
    return {"close": close, "adjusted": adjusted, "metadata": metadata, "currencies": currencies}


def _series(panel: pd.DataFrame, symbol: str) -> pd.Series:
    if symbol not in panel:
        return pd.Series(dtype=float)
    return pd.to_numeric(panel[symbol], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def _latest(series: pd.Series) -> tuple[float | None, str | None]:
    if series.empty:
        return None, None
    return number(series.iloc[-1]), pd.Timestamp(series.index[-1]).date().isoformat()


def _usd_series(panel: pd.DataFrame, symbol: str, currency: str | None) -> pd.Series:
    unit = currency_lookup_and_unit_scale(currency)
    if unit is None:
        return pd.Series(dtype=float)
    local = _series(panel, symbol)
    if unit[0] == "USD":
        return local * unit[1]
    direct = _series(panel, f"{unit[0]}USD=X")
    inverse = _series(panel, f"USD{unit[0]}=X")
    fx = direct if not direct.empty else 1.0 / inverse.replace(0, np.nan)
    if fx.empty:
        return pd.Series(dtype=float)
    # Pairwise dates only: do not fabricate zero returns by filling missing prices.
    return (local * fx * unit[1]).dropna()


def _fx_at(close: pd.DataFrame, currency: str | None, as_of: str | None) -> tuple[float | None, str | None]:
    unit = currency_lookup_and_unit_scale(currency)
    if unit is None or as_of is None:
        return None, None
    if unit[0] == "USD":
        return unit[1], as_of
    for symbol, inverse in ((f"{unit[0]}USD=X", False), (f"USD{unit[0]}=X", True)):
        series = _series(close, symbol)
        series = series[[pd.Timestamp(value).date().isoformat() <= as_of for value in series.index]]
        rate, fx_date = _latest(series)
        if rate is not None and rate > 0:
            return (1.0 / rate if inverse else rate) * unit[1], fx_date
    return None, None


def measured_betas(inputs: dict[str, Any], holdings: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    from portfolio.portfolio_optimizer.portfolio_analyzer import BETA_MIN_OBS, compute_betas

    panel: pd.DataFrame = inputs["adjusted"]
    currencies = inputs["currencies"]
    result: dict[str, dict[str, Any]] = {}
    for symbol in sorted({beta_symbol(row) for row in holdings if beta_eligible(row)}):
        prices = _usd_series(panel, symbol, currencies.get(symbol))
        returns = prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
        estimates: dict[str, Any] = {}
        for benchmark in BENCHMARKS:
            market = _usd_series(panel, benchmark, "USD").pct_change(fill_method=None)
            pairs = pd.concat([returns.rename("position"), market.rename(benchmark)], axis=1).dropna()
            observations = len(pairs)
            beta = None
            if observations >= BETA_MIN_OBS and number(pairs[benchmark].var()) not in (None, 0):
                # The shared helper's 1.0 sentinel is never used for missing history.
                beta = number(compute_betas(pairs, benchmark).get("position"))
            estimates[benchmark] = {
                "beta": beta,
                "observations": observations,
                "as_of": pd.Timestamp(pairs.index[-1]).date().isoformat() if not pairs.empty else None,
            }
        result[symbol] = estimates
    return result


def build_rows(
    holdings: list[dict[str, Any]], inputs: dict[str, Any], book: float, stress: dict[str, Any] | None
) -> list[dict[str, Any]]:
    betas = measured_betas(inputs, holdings)
    stress_rows = (stress or {}).get("position_snapshots") or (stress or {}).get("results") or []
    stress_by_ticker = {str(row.get("ticker") or "").upper(): row for row in stress_rows if isinstance(row, dict)}
    rows = []
    for index, holding in enumerate(holdings):
        instrument = str(holding.get("instrument_type") or "security")
        option = instrument == "option"
        exposure = resolve_economic_exposure(holding)
        symbol = quote_symbol(holding)
        underlying = exposure.underlying_ticker
        role = "hedge" if holding.get("role") == "hedge" else "position"
        metadata = inputs["metadata"].get(underlying, {})
        currency = holding.get("currency") or inputs["currencies"].get(symbol)
        price, price_as_of = _latest(_series(inputs["close"], symbol))
        fx_rate, fx_as_of = _fx_at(inputs["close"], currency, price_as_of)
        quantity = number(holding.get("quantity") if holding.get("quantity") is not None else holding.get("shares"))
        multiplier = number(holding.get("contract_multiplier", 1.0 if instrument in {"security", "spot_fx"} else None))
        issues = []
        if quantity is None:
            issues.append("missing_quantity")
        if price is None or price <= 0:
            issues.append("missing_price")
        if multiplier is None or multiplier <= 0:
            issues.append("missing_multiplier")
        if not currency:
            issues.append("missing_currency")
        elif fx_rate is None:
            issues.append("missing_fx_rate")
        asset = holding.get("asset")
        sector = holding.get("sector") or metadata.get("sector")
        if not asset:
            issues.append("missing_asset")
        if asset == "equity" and instrument != "future" and not sector:
            issues.append("missing_sector")
        mark = None
        if (
            quantity is not None
            and price is not None
            and price > 0
            and multiplier is not None
            and multiplier > 0
            and fx_rate is not None
        ):
            mark = abs(quantity) * price * multiplier * fx_rate
        signed = None if option or mark is None else mark * direction_sign(holding) * exposure.factor
        eligible = beta_eligible(holding)
        estimates = betas.get(beta_symbol(holding), {}) if eligible else {}
        risk = stress_by_ticker.get(str(holding.get("ticker") or "").upper(), {}) if role == "position" else {}
        row = {
            "position_id": f"{role}:{holding.get('id') or position_row_id(holding) or index}",
            "ticker": display_ticker(holding),
            "underlying_ticker": underlying,
            "price_symbol": symbol,
            "asset": asset,
            "sector": sector or ("Equity index" if eligible and instrument == "future" else None),
            "group_name": holding.get("group_name"),
            "role": role,
            "instrument_type": instrument,
            "direction": str(holding.get("direction") or "long"),
            "quantity": quantity,
            "contract_multiplier": multiplier,
            "currency": currency,
            "price": price,
            "price_as_of": price_as_of,
            "fx_rate_to_usd": fx_rate,
            "fx_as_of": fx_as_of,
            "exposure_multiplier": exposure.factor,
            "signed_notional": signed,
            "gross_notional": abs(signed) if signed is not None else None,
            "weight_pct": signed / book * 100 if signed is not None else None,
            "premium_usd": mark if option else None,
            "option_type": holding.get("option_type"),
            "option_strike": number(holding.get("option_strike")),
            "option_expiration": holding.get("option_expiration"),
            "beta_eligible": eligible,
            "beta_status": "excluded_option" if option else "eligible" if eligible else "unsupported_asset",
            "risk_score": number(risk.get("risk_score")),
            "risk_level": risk.get("risk_level"),
            "drivers": risk.get("drivers") or risk.get("evidence") or [],
            "issues": issues,
        }
        for benchmark in BENCHMARKS:
            estimate = estimates.get(benchmark, {})
            beta = estimate.get("beta")
            row[f"beta_{benchmark.lower()}"] = beta
            row[f"beta_{benchmark.lower()}_observations"] = estimate.get("observations", 0)
            row[f"beta_{benchmark.lower()}_as_of"] = estimate.get("as_of")
            row[f"beta_contribution_{benchmark.lower()}"] = (
                signed / book * beta if signed is not None and beta is not None else None
            )
        rows.append(row)
    return rows


def aggregate_view(rows: list[dict[str, Any]], book: float) -> dict[str, Any]:
    linear = [row for row in rows if row["instrument_type"] != "option"]
    measured = [row for row in linear if row["signed_notional"] is not None]
    options = [row for row in rows if row["instrument_type"] == "option"]
    has_measurement = bool(measured) or not linear
    long = sum(max(0.0, row["signed_notional"]) for row in measured)
    short = sum(max(0.0, -row["signed_notional"]) for row in measured)
    gross = long + short
    totals = {"long": long, "short": short, "gross": gross, "net": long - short}
    summary: dict[str, Any] = {}
    for key, value in totals.items():
        summary[f"{key}_usd"] = value if has_measurement else None
        summary[f"{key}_pct"] = value / book * 100 if has_measurement else None
    breakdowns = {}
    for dimension, field in (
        ("underlying", "underlying_ticker"),
        ("sector", "sector"),
        ("asset", "asset"),
        ("group", "group_name"),
    ):
        buckets: dict[str, dict[str, Any]] = {}
        for row in measured:
            label = str(row.get(field) or ("Ungrouped" if dimension == "group" else "Unclassified"))
            bucket = buckets.setdefault(label, {"name": label, "gross_usd": 0.0, "net_usd": 0.0, "position_count": 0})
            bucket["gross_usd"] += row["gross_notional"]
            bucket["net_usd"] += row["signed_notional"]
            bucket["position_count"] += 1
        breakdowns[dimension] = [
            {**bucket, "gross_share_pct": bucket["gross_usd"] / gross * 100 if gross > 0 else None}
            for bucket in sorted(buckets.values(), key=lambda value: (-value["gross_usd"], value["name"]))
        ]
    eligible = [row for row in linear if row["beta_eligible"]]
    beta_totals = {}
    for benchmark in BENCHMARKS:
        field = f"beta_contribution_{benchmark.lower()}"
        covered = [row for row in eligible if row[field] is not None]
        primary = [row for row in covered if row["role"] != "hedge"]
        hedges = [row for row in covered if row["role"] == "hedge"]
        beta_totals[benchmark] = {
            "primary": sum(row[field] for row in primary)
            if primary or not any(row["role"] != "hedge" for row in eligible)
            else None,
            "hedges": sum(row[field] for row in hedges)
            if hedges or not any(row["role"] == "hedge" for row in eligible)
            else None,
            "combined": sum(row[field] for row in covered) if covered or not eligible else None,
            "covered_count": len(covered),
            "eligible_count": len(eligible),
            "covered_gross_pct": sum(row["gross_notional"] for row in covered) / gross * 100 if gross > 0 else None,
        }
    return {
        "summary": summary,
        "breakdowns": breakdowns,
        "betas": beta_totals,
        "coverage": {
            "position_count": len(rows),
            "linear_count": len(linear),
            "valued_linear_count": len(measured),
            "option_count": len(options),
            "priced_option_count": sum(row["premium_usd"] is not None for row in options),
            "classification_gap_count": sum(
                bool({"missing_asset", "missing_sector"} & set(row["issues"])) for row in rows
            ),
        },
    }
