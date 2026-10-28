"""Screens, ranking and merging for the idea scan. No LLM calls and no network.

Every preset reads one factor frame built from the shared data set. Screen
rules reuse the long/short screen predicates one criterion at a time, so a
card can say which checks fired and a near-miss can say which one failed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import numpy as np
import pandas as pd

from api.idea_scan.data import MARKET_BENCHMARK, STATEMENTS, ScanDataset
from api.idea_scan.presets import (
    BreakdownParams,
    CompositeTopParams,
    IdeaScanPreset,
    LongScreenParams,
    QualityValueParams,
    ShortScreenParams,
)
from equities.long_screen.long_screen import long_fundamentals_pass, long_price_filters_pass
from equities.quality.quality_single import beta_from_prices, raw_metrics_from_statements
from equities.short_screen.short_screen import (
    BOOK_VALUE_KEYS,
    compute_price_metrics,
    compute_quarterly_growth,
    get_item,
    last_col,
    short_fundamentals_pass,
    short_price_filters_pass,
)
from portfolio.momentum.fundamental_momentum.eps_momentum_single import eps_metrics_from_statements
from portfolio.momentum.fundamental_momentum.revenue_momentum_single import revenue_metrics_from_statements
from portfolio.portfolio_optimizer.rank_universe import (
    DEFAULT_WEIGHTS,
    combine_signals,
    compute_eps_momentum_scores,
    compute_price_momentum_scores,
    compute_quality_scores,
    compute_revenue_momentum_scores,
)
from portfolio.portfolio_optimizer.signal_fetchers import fetch_price_momentum_batch

# A +2 sector score at high confidence lifts a name by half a preset hit.
MACRO_POINT_WEIGHT = 0.25
MACRO_CONFIDENCE_WEIGHTS = {"low": 0.5, "medium": 0.75, "high": 1.0}

ISSUANCE_KEYS = ["Issuance Of Capital Stock", "IssuanceOfCapitalStock", "Common Stock Issuance"]
REPURCHASE_KEYS = ["Repurchase Of Capital Stock", "RepurchaseOfCapitalStock", "Common Stock Payments"]
QUALITY_GROWTH_YEARS = 5
MOMENTUM_GROWTH_YEARS = 3
PRICE_FILTER_DAYS = 365
BETA_DAYS = 3 * 365

FACTOR_COLUMNS = ("quality", "price_momentum", "eps_momentum", "revenue_momentum")


def _num(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return np.nan
    return out if math.isfinite(out) else np.nan


def json_safe(value: Any) -> Any:
    """NaN/inf become None and numpy scalars become Python numbers, recursively."""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


# ---------------------------------------------------------------------------
# Factor frame
# ---------------------------------------------------------------------------


def _net_issuance(cashflow: pd.DataFrame | None) -> float:
    col = last_col(cashflow)
    issued = get_item(col, ISSUANCE_KEYS)
    repurchased = get_item(col, REPURCHASE_KEYS)
    if np.isnan(issued) and np.isnan(repurchased):
        return np.nan
    return (0.0 if np.isnan(issued) else abs(issued)) - (0.0 if np.isnan(repurchased) else abs(repurchased))


def _days_to_earnings(info: dict[str, Any], now: datetime) -> int | None:
    stamps = [_num(info.get(k)) for k in ("earningsTimestampStart", "earningsTimestamp")]
    future = [s for s in stamps if not np.isnan(s) and s > now.timestamp()]
    if not future:
        return None
    return int(math.ceil((min(future) - now.timestamp()) / 86400))


def _tail(series: pd.Series, days: int) -> pd.Series:
    series = series.dropna()
    if series.empty:
        return series
    return series[series.index >= series.index[-1] - pd.Timedelta(days=days)]


def _screen_fields(info: dict[str, Any], fundamentals: Any) -> dict[str, Any]:
    """The fetch_yf_data-shaped dict the long/short screen predicates read."""
    price_to_book = _num(info.get("priceToBook"))
    market_cap = _num(info.get("marketCap"))
    book_value = get_item(last_col(fundamentals.balance_sheet), BOOK_VALUE_KEYS)
    if np.isnan(price_to_book) and not np.isnan(market_cap) and not np.isnan(book_value) and book_value > 0:
        price_to_book = market_cap / book_value
    inc_last = last_col(fundamentals.financials)
    return {
        "price_to_book": price_to_book,
        "gross_profit": get_item(inc_last, ["Gross Profit", "GrossProfit"]),
        "operating_income": get_item(inc_last, ["Operating Income", "OperatingIncome", "EBIT", "Ebit"]),
        "market_cap": market_cap,
        "book_value": book_value,
        **compute_quarterly_growth(fundamentals.quarterly_financials),
    }


def build_factor_frame(dataset: ScanDataset, *, now: datetime | None = None) -> pd.DataFrame:
    """One row per ticker with screen fields, price metrics, valuation and factor scores/percentiles."""
    when = now or datetime.now(UTC)
    prices = dataset.prices
    market = prices[MARKET_BENCHMARK].dropna() if MARKET_BENCHMARK in prices.columns else pd.Series(dtype=float)
    market_beta_window = _tail(market, BETA_DAYS)

    rows: dict[str, dict[str, Any]] = {}
    quality_raw: dict[str, dict[str, float]] = {}
    eps_raw: dict[str, dict[str, float]] = {}
    revenue_raw: dict[str, dict[str, float]] = {}

    for ticker in dataset.tickers:
        fundamentals = dataset.fundamentals.get(ticker)
        if fundamentals is None or not (
            fundamentals.info or any(getattr(fundamentals, n) is not None for n in STATEMENTS)
        ):
            continue
        info = fundamentals.info
        close = prices[ticker].dropna() if ticker in prices.columns else pd.Series(dtype=float)
        bench = dataset.primary_benchmark(ticker)
        bench_close = prices[bench].dropna() if bench in prices.columns else None

        price_metrics: dict[str, float | None] = {}
        last_px = np.nan
        if len(close) >= 10:
            last_px = float(close.iloc[-1])
            year = _tail(close, PRICE_FILTER_DAYS)
            price_metrics = compute_price_metrics(
                year, _tail(bench_close, PRICE_FILTER_DAYS) if bench_close is not None else None
            )

        fields = _screen_fields(info, fundamentals)
        shares_out = _num(info.get("sharesOutstanding"))
        beta = beta_from_prices(_tail(close, BETA_DAYS), market_beta_window) if len(close) >= 60 else np.nan
        try:
            quality_raw[ticker] = vars(
                raw_metrics_from_statements(
                    fundamentals.financials,
                    fundamentals.balance_sheet,
                    fundamentals.cashflow,
                    beta=beta,
                    shares_out=shares_out,
                    last_px=last_px,
                    growth_years=QUALITY_GROWTH_YEARS,
                )
            )
        except Exception:
            pass
        eps = eps_metrics_from_statements(
            fundamentals.quarterly_financials,
            fundamentals.financials,
            shares_out=shares_out,
            growth_years=MOMENTUM_GROWTH_YEARS,
        )
        eps_raw[ticker] = {
            "eps_yoy_change": eps.eps_yoy_change,
            "eps_cagr": eps.eps_cagr,
            "eps_growth_acceleration": eps.eps_growth_acceleration,
        }
        revenue = revenue_metrics_from_statements(
            fundamentals.quarterly_financials, fundamentals.financials, growth_years=MOMENTUM_GROWTH_YEARS
        )
        revenue_raw[ticker] = {
            "revenue_yoy_change": revenue.revenue_yoy_change,
            "revenue_cagr": revenue.revenue_cagr,
            "revenue_growth_acceleration": revenue.revenue_growth_acceleration,
        }

        rows[ticker] = {
            "ticker": ticker,
            "company": info.get("longName") or info.get("shortName") or ticker,
            "sector": info.get("sector") or "Unknown",
            "industry": info.get("industry") or "",
            "universes": list(dataset.membership.get(ticker, [])),
            **fields,
            "net_issuance": _net_issuance(fundamentals.cashflow),
            "return_52w": price_metrics.get("return_52w"),
            "drawdown_pct": price_metrics.get("drawdown_pct"),
            "return_3m": price_metrics.get("return_3m"),
            "rel_return_2m": price_metrics.get("rel_return_2m"),
            "enterpriseToEbitda": _num(info.get("enterpriseToEbitda")),
            "forwardPE": _num(info.get("forwardPE")),
            "trailingPE": _num(info.get("trailingPE")),
            "priceToBook": fields["price_to_book"],
            "short_percent_of_float": _num(info.get("shortPercentOfFloat")),
            "short_ratio": _num(info.get("shortRatio")),
            "shares_short": _num(info.get("sharesShort")),
            "date_short_interest": _num(info.get("dateShortInterest")),
            "days_to_earnings": _days_to_earnings(info, when),
        }

    frame = pd.DataFrame.from_dict(rows, orient="index")
    if frame.empty:
        return frame
    tickers = list(frame.index)

    momentum_prices = prices[[c for c in prices.columns if c in set(tickers) | {MARKET_BENCHMARK}]].tail(300)
    momentum_raw = fetch_price_momentum_batch(
        [t for t in tickers if t in momentum_prices.columns],
        {t: MARKET_BENCHMARK for t in tickers},
        momentum_prices,
    )
    scores = {
        "quality": compute_quality_scores(pd.DataFrame.from_dict(quality_raw, orient="index"))[0],
        "price_momentum": compute_price_momentum_scores(momentum_raw)[0],
        "eps_momentum": compute_eps_momentum_scores(pd.DataFrame.from_dict(eps_raw, orient="index"))[0],
        "revenue_momentum": compute_revenue_momentum_scores(pd.DataFrame.from_dict(revenue_raw, orient="index"))[0],
    }
    for name, series in scores.items():
        aligned = series.reindex(frame.index) if not series.empty else pd.Series(np.nan, index=frame.index)
        frame[name] = aligned
        frame[f"{name}_pct"] = aligned.rank(pct=True)
    frame["composite"] = composite_scores(frame, DEFAULT_WEIGHTS)
    frame["composite_pct"] = frame["composite"].rank(pct=True)
    return frame


def composite_scores(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """rank_universe's weighted composite, re-normalised over the factors each ticker has."""
    signals = {name: frame[name] for name in FACTOR_COLUMNS if name in frame.columns}
    active = {k: float(v) for k, v in weights.items() if k in signals and float(v) > 0}
    return combine_signals({k: signals[k] for k in active}, active, list(frame.index)).clip(-3.0, 3.0)


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


@dataclass
class Check:
    label: str
    ok: bool
    has_data: bool = True


@dataclass
class PresetResult:
    preset: IdeaScanPreset
    evaluated: int = 0
    hits_total: int = 0
    hits: list[dict[str, Any]] = field(default_factory=list)
    near_misses: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.preset.id,
            "name": self.preset.name,
            "direction": self.preset.direction,
            "evaluated": self.evaluated,
            "hits": self.hits_total,
            "kept": len(self.hits),
            "near_misses": len(self.near_misses),
        }


def _present(value: Any) -> bool:
    return value is not None and not (isinstance(value, float) and np.isnan(value))


def _fmt(value: Any, digits: int = 1, suffix: str = "") -> str:
    return f"{float(value):.{digits}f}{suffix}" if _present(value) else "n/a"


def _price_dict(row: pd.Series) -> dict[str, float | None]:
    return {
        key: (None if not _present(row.get(key)) else float(row[key]))
        for key in ("return_52w", "drawdown_pct", "return_3m", "rel_return_2m")
    }


def _long_checks(row: pd.Series, p: LongScreenParams) -> list[Check]:
    data = row.to_dict()
    checks: list[Check] = []
    if p.pb_threshold is not None:
        ok = long_fundamentals_pass(data, pb_threshold=p.pb_threshold, profit_type=None)
        checks.append(
            Check(
                f"P/B {_fmt(row.get('price_to_book'), 2)} (< {p.pb_threshold:g})",
                ok,
                _present(data.get("price_to_book")),
            )
        )
    if p.profit_type is not None:
        key = "gross_profit" if p.profit_type == "Gross Profit" else "operating_income"
        ok = long_fundamentals_pass(data, pb_threshold=None, profit_type=p.profit_type)
        checks.append(Check(f"{p.profit_type} positive", ok, _present(data.get(key))))
    if p.check_revenue:
        ok = long_fundamentals_pass(
            data, pb_threshold=None, profit_type=None, check_revenue=True, min_revenue_growth=p.min_revenue_growth
        )
        checks.append(
            Check(
                f"Revenue YoY {_fmt(row.get('rev_yoy_avg'), 1, '%')} (≥ {p.min_revenue_growth:g}%)",
                ok,
                _present(data.get("rev_yoy_avg")),
            )
        )
    if p.check_eps:
        ok = long_fundamentals_pass(
            data, pb_threshold=None, profit_type=None, check_eps=True, min_eps_growth=p.min_eps_growth
        )
        checks.append(
            Check(
                f"EPS YoY {_fmt(row.get('eps_yoy_avg'), 1, '%')} (≥ {p.min_eps_growth:g}%)",
                ok,
                _present(data.get("eps_yoy_avg")),
            )
        )
    if p.require_buybacks:
        net = row.get("net_issuance")
        checks.append(Check("Net buybacks (last fiscal year)", _present(net) and float(net) < 0, _present(net)))
    if p.check_ebit_multiple:
        ok = long_fundamentals_pass(
            data, pb_threshold=None, profit_type=None, check_ebit_multiple=True, max_ebit_multiple=p.max_ebit_multiple
        )
        has = _present(data.get("operating_income")) and _present(data.get("market_cap"))
        checks.append(
            Check(f"Market cap / EBIT {_fmt(data.get('ebit_multiple'), 1)} (≤ {p.max_ebit_multiple:g})", ok, has)
        )
    price = _price_dict(row)
    for flag, label, key in (
        ("check_52w_positive", "52-week return positive", "return_52w"),
        ("check_3m_pos_momentum", "3-month return positive", "return_3m"),
        ("check_2m_pos_rel_momentum", "Beating benchmark over 2 months", "rel_return_2m"),
    ):
        if getattr(p, flag):
            checks.append(Check(label, long_price_filters_pass(price, **{flag: True}), price.get(key) is not None))
    return checks


def _short_checks(row: pd.Series, p: ShortScreenParams) -> list[Check]:
    data = row.to_dict()
    checks: list[Check] = []
    if p.pb_threshold is not None:
        ok = short_fundamentals_pass(data, pb_threshold=p.pb_threshold, loss_type=None)
        checks.append(
            Check(
                f"P/B {_fmt(row.get('price_to_book'), 2)} (> {p.pb_threshold:g})",
                ok,
                _present(data.get("price_to_book")),
            )
        )
    if p.loss_type is not None:
        key = "gross_profit" if p.loss_type == "Gross Loss" else "operating_income"
        ok = short_fundamentals_pass(data, pb_threshold=None, loss_type=p.loss_type)
        checks.append(Check(p.loss_type, ok, _present(data.get(key))))
    if p.check_revenue:
        ok = short_fundamentals_pass(
            data, pb_threshold=None, loss_type=None, check_revenue=True, max_revenue_growth=p.max_revenue_growth
        )
        checks.append(
            Check(
                f"Revenue YoY {_fmt(row.get('rev_yoy_avg'), 1, '%')} (≤ {p.max_revenue_growth:g}%)",
                ok,
                _present(data.get("rev_yoy_avg")),
            )
        )
    if p.check_eps:
        ok = short_fundamentals_pass(
            data, pb_threshold=None, loss_type=None, check_eps=True, max_eps_growth=p.max_eps_growth
        )
        checks.append(
            Check(
                f"EPS YoY {_fmt(row.get('eps_yoy_avg'), 1, '%')} (≤ {p.max_eps_growth:g}%)",
                ok,
                _present(data.get("eps_yoy_avg")),
            )
        )
    if p.require_dilution:
        net = row.get("net_issuance")
        checks.append(Check("Net share issuance (last fiscal year)", _present(net) and float(net) > 0, _present(net)))
    price = _price_dict(row)
    for flag, label, key in (
        ("check_3m_neg_momentum", "3-month return negative", "return_3m"),
        ("check_2m_neg_rel_momentum", "Lagging benchmark over 2 months", "rel_return_2m"),
    ):
        if getattr(p, flag):
            checks.append(Check(label, short_price_filters_pass(price, **{flag: True}), price.get(key) is not None))
    return checks


def sector_valuation_pct(frame: pd.DataFrame, metric: str) -> pd.Series:
    """Percentile of a positive valuation multiple within each sector (low = cheap)."""
    values = frame[metric].where(frame[metric] > 0)
    return values.groupby(frame["sector"]).rank(pct=True)


def _quality_value_checks(row: pd.Series, p: QualityValueParams, valuation_pct: float) -> list[Check]:
    quality_pct = row.get("quality_pct")
    metric_value = row.get(p.valuation_metric)
    return [
        Check(
            f"Quality percentile {_fmt(quality_pct * 100 if _present(quality_pct) else None, 0)} (≥ {p.min_quality_pct * 100:g})",
            _present(quality_pct) and float(quality_pct) >= p.min_quality_pct,
            _present(quality_pct),
        ),
        Check(
            f"{p.valuation_metric} {_fmt(metric_value, 1)} (cheapest {p.max_sector_valuation_pct * 100:g}% of sector)",
            _present(valuation_pct) and float(valuation_pct) <= p.max_sector_valuation_pct,
            _present(valuation_pct),
        ),
    ]


def _composite_checks(composite_pct: float, p: CompositeTopParams) -> list[Check]:
    return [
        Check(
            f"Composite percentile {_fmt(composite_pct * 100 if _present(composite_pct) else None, 0)} (≥ {p.min_composite_pct * 100:g})",
            _present(composite_pct) and float(composite_pct) >= p.min_composite_pct,
            _present(composite_pct),
        )
    ]


def _breakdown_checks(row: pd.Series, p: BreakdownParams, revision: float | None) -> list[Check]:
    pm_pct = row.get("price_momentum_pct")
    checks = [
        Check(
            f"Price momentum percentile {_fmt(pm_pct * 100 if _present(pm_pct) else None, 0)} (≤ {p.max_price_momentum_pct * 100:g})",
            _present(pm_pct) and float(pm_pct) <= p.max_price_momentum_pct,
            _present(pm_pct),
        )
    ]
    if p.require_negative_revisions:
        checks.append(
            Check(
                f"30-day EPS revisions {_fmt(revision * 100 if revision is not None else None, 1, '%')} (negative)",
                revision is not None and revision < 0,
                revision is not None,
            )
        )
    return checks


def breakdown_revision_tickers(frame: pd.DataFrame, presets: list[IdeaScanPreset]) -> list[str]:
    """Tickers whose EPS revisions a breakdown preset needs: those already in its price-momentum tail."""
    wanted: set[str] = set()
    for preset in presets:
        if not preset.enabled or preset.screen != "breakdown":
            continue
        params = BreakdownParams.model_validate(preset.params)
        if not params.require_negative_revisions or frame.empty:
            continue
        in_universe = frame["universes"].apply(lambda u, keys=set(preset.universes): bool(keys & set(u)))
        # A little past the cut-off so near-misses can show their revisions too.
        tail = frame[in_universe & (frame["price_momentum_pct"] <= min(1.0, params.max_price_momentum_pct * 1.5))]
        wanted.update(tail.index)
    return sorted(wanted)


def _row_card(row: pd.Series) -> dict[str, Any]:
    keys = (
        "market_cap",
        "price_to_book",
        "gross_profit",
        "operating_income",
        "rev_yoy_avg",
        "eps_yoy_avg",
        "net_issuance",
        "return_52w",
        "drawdown_pct",
        "return_3m",
        "rel_return_2m",
        "enterpriseToEbitda",
        "forwardPE",
        "trailingPE",
    )
    return cast(dict[str, Any], json_safe({k: row.get(k) for k in keys}))


def evaluate_preset(
    preset: IdeaScanPreset,
    frame: pd.DataFrame,
    *,
    revisions: dict[str, float] | None = None,
    near_miss_limit: int = 10,
) -> PresetResult:
    result = PresetResult(preset=preset)
    if frame.empty or not preset.enabled:
        return result
    revisions = revisions or {}
    keys = set(preset.universes)
    scope = frame[frame["universes"].apply(lambda u: bool(keys & set(u)))]
    result.evaluated = len(scope)
    if scope.empty:
        return result

    composite = composite_scores(frame, preset.weights.model_dump()).rank(pct=True)
    valuation_pct = (
        sector_valuation_pct(frame, QualityValueParams.model_validate(preset.params).valuation_metric)
        if preset.screen == "quality_value"
        else None
    )

    hits: list[dict[str, Any]] = []
    near: list[dict[str, Any]] = []
    for ticker, row in scope.iterrows():
        composite_pct = float(composite.get(ticker, np.nan))
        if preset.screen == "long_screen":
            checks = _long_checks(row, LongScreenParams.model_validate(preset.params))
        elif preset.screen == "short_screen":
            checks = _short_checks(row, ShortScreenParams.model_validate(preset.params))
        elif preset.screen == "quality_value":
            assert valuation_pct is not None
            checks = _quality_value_checks(
                row, QualityValueParams.model_validate(preset.params), float(valuation_pct.get(ticker, np.nan))
            )
        elif preset.screen == "composite_top":
            checks = _composite_checks(composite_pct, CompositeTopParams.model_validate(preset.params))
        else:
            checks = _breakdown_checks(row, BreakdownParams.model_validate(preset.params), revisions.get(str(ticker)))
        if not checks:
            continue
        failed = [c for c in checks if not c.ok]
        score = composite_pct if preset.direction == "long" else 1.0 - composite_pct
        entry = {
            "ticker": str(ticker),
            "preset_id": preset.id,
            "preset_name": preset.name,
            "direction": preset.direction,
            "preset_score": None if np.isnan(score) else score,
            "signals": [c.label for c in checks if c.ok],
            "failed": [c.label for c in failed],
            "revision_30d": revisions.get(str(ticker)),
        }
        if not failed:
            hits.append(entry)
        elif len(failed) == 1 and all(c.has_data for c in checks):
            near.append(entry)

    def by_score(item: dict[str, Any]) -> float:
        return item["preset_score"] if item["preset_score"] is not None else -1.0

    hits.sort(key=by_score, reverse=True)
    near.sort(key=by_score, reverse=True)
    result.hits_total = len(hits)
    result.hits = hits[: preset.max_names]
    result.near_misses = near[:near_miss_limit]
    return result


# ---------------------------------------------------------------------------
# Merging, macro and selection
# ---------------------------------------------------------------------------


def merge_candidates(results: list[PresetResult], frame: pd.DataFrame) -> list[dict[str, Any]]:
    """One candidate per (ticker, direction), however many presets it hit."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for result in results:
        for hit in result.hits:
            key = (hit["ticker"], hit["direction"])
            entry = merged.setdefault(key, {"ticker": hit["ticker"], "direction": hit["direction"], "hits": []})
            entry["hits"].append(hit)

    candidates: list[dict[str, Any]] = []
    for (ticker, direction), entry in merged.items():
        row = frame.loc[ticker]
        scores = [h["preset_score"] for h in entry["hits"] if h["preset_score"] is not None]
        composite = float(np.mean(scores)) if scores else 0.0
        agreement = len(entry["hits"]) + composite
        candidate = {
            "ticker": ticker,
            "direction": direction,
            "company": row.get("company") or ticker,
            "sector": row.get("sector") or "Unknown",
            "industry": row.get("industry") or "",
            "universes": list(row.get("universes") or []),
            "presets": [{"id": h["preset_id"], "name": h["preset_name"]} for h in entry["hits"]],
            "signals": [{"preset_id": h["preset_id"], "label": label} for h in entry["hits"] for label in h["signals"]],
            "preset_count": len(entry["hits"]),
            "direction_composite": composite,
            "agreement_score": agreement,
            "macro_boost": 0.0,
            "final_score": agreement,
            "macro_fit": None,
            "factor_ranks": {f"{name}_pct": row.get(f"{name}_pct") for name in (*FACTOR_COLUMNS, "composite")},
            "metrics": _row_card(row),
            "revision_30d": next((h["revision_30d"] for h in entry["hits"] if h["revision_30d"] is not None), None),
            "days_to_earnings": row.get("days_to_earnings"),
        }
        if direction == "short":
            candidate["short_data"] = {
                "short_percent_of_float": row.get("short_percent_of_float"),
                "short_ratio": row.get("short_ratio"),
                "shares_short": row.get("shares_short"),
                "date_short_interest": row.get("date_short_interest"),
                "borrow": None,
            }
        candidates.append(json_safe(candidate))
    return rank_candidates(candidates)


def rank_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda c: (c.get("final_score") or 0.0, c.get("agreement_score") or 0.0, c["ticker"]),
        reverse=True,
    )


def apply_macro(candidates: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Raise long ranks in tailwind sectors and short ranks in headwind sectors. Never removes a name."""
    by_sector = {str(r.get("sector")): r for r in rows}
    out = []
    for candidate in candidates:
        updated = dict(candidate)
        row = by_sector.get(str(candidate.get("sector")))
        boost = 0.0
        fit = None
        if row is not None:
            score = float(row.get("score") or 0)
            directional = score if candidate["direction"] == "long" else -score
            weight = MACRO_CONFIDENCE_WEIGHTS.get(str(row.get("confidence")), 0.5)
            boost = max(0.0, directional) * MACRO_POINT_WEIGHT * weight
            fit = {
                "sector": row.get("sector"),
                "score": row.get("score"),
                "confidence": row.get("confidence"),
                "reason": row.get("reason"),
                "fit": "tailwind" if directional > 0 else "headwind" if directional < 0 else "neutral",
                "boost": round(boost, 4),
            }
        updated["macro_boost"] = round(boost, 4)
        updated["macro_fit"] = fit
        updated["final_score"] = round(float(candidate.get("agreement_score") or 0.0) + boost, 6)
        out.append(updated)
    return rank_candidates(out)


def split_tracked(
    candidates: list[dict[str, Any]], tracked: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Names already in Ideas or the portfolio don't use a review slot."""
    fresh: list[dict[str, Any]] = []
    already: list[dict[str, Any]] = []
    for candidate in candidates:
        source = tracked.get(candidate["ticker"])
        if source:
            already.append(
                {
                    "ticker": candidate["ticker"],
                    "direction": candidate["direction"],
                    "company": candidate.get("company"),
                    "tracked_as": source,
                    "presets": candidate.get("presets", []),
                    "final_score": candidate.get("final_score"),
                }
            )
        else:
            fresh.append(candidate)
    return fresh, already


def collect_near_misses(
    results: list[PresetResult], candidates: list[dict[str, Any]], frame: pd.DataFrame, *, limit: int
) -> list[dict[str, Any]]:
    taken = {(c["ticker"], c["direction"]) for c in candidates}
    seen: set[tuple[str, str]] = set()
    pool: list[dict[str, Any]] = []
    for result in results:
        for miss in result.near_misses:
            key = (miss["ticker"], miss["direction"])
            if key in taken or key in seen:
                continue
            seen.add(key)
            row = frame.loc[miss["ticker"]]
            pool.append(
                json_safe(
                    {
                        "ticker": miss["ticker"],
                        "direction": miss["direction"],
                        "company": row.get("company"),
                        "sector": row.get("sector"),
                        "preset_id": miss["preset_id"],
                        "preset_name": miss["preset_name"],
                        "failed_check": miss["failed"][0] if miss["failed"] else None,
                        "signals": miss["signals"],
                        "preset_score": miss["preset_score"],
                    }
                )
            )
    pool.sort(key=lambda m: m.get("preset_score") or 0.0, reverse=True)
    return pool[:limit]


def week_over_week(
    current: list[dict[str, Any]], previous: list[dict[str, Any]] | None
) -> dict[str, list[dict[str, str]]]:
    def key(item: dict[str, Any]) -> tuple[str, str]:
        return (str(item.get("ticker")), str(item.get("direction")))

    def summary(item: dict[str, Any]) -> dict[str, Any]:
        return {"ticker": item.get("ticker"), "direction": item.get("direction"), "company": item.get("company")}

    now_keys = {key(c): c for c in current}
    then_keys = {key(c): c for c in (previous or [])}
    return {
        "new": [summary(c) for k, c in now_keys.items() if k not in then_keys],
        "still": [summary(c) for k, c in now_keys.items() if k in then_keys],
        "dropped": [summary(c) for k, c in then_keys.items() if k not in now_keys],
    }
