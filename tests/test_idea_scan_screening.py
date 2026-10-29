from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from api.idea_scan import screening as sc
from api.idea_scan.data import ScanDataset, TickerFundamentals
from api.idea_scan.presets import IdeaScanPreset, default_presets
from equities.long_screen.long_screen import long_fundamentals_pass
from equities.short_screen.short_screen import compute_price_metrics, compute_quarterly_growth

ALL = ["sp500", "sp400", "sp600", "russell2000"]

DEFAULT_ROW = {
    "company": "Co",
    "sector": "Industrials",
    "industry": "Machinery",
    "universes": ["sp500"],
    "price_to_book": 2.0,
    "gross_profit": 100.0,
    "operating_income": 50.0,
    "market_cap": 1e9,
    "rev_yoy_avg": 2.0,
    "eps_yoy_avg": 2.0,
    "net_issuance": 0.0,
    "return_52w": 5.0,
    "drawdown_pct": -10.0,
    "return_3m": 1.0,
    "rel_return_2m": 0.0,
    "enterpriseToEbitda": 12.0,
    "forwardPE": 15.0,
    "trailingPE": 18.0,
    "priceToBook": 2.0,
    "short_percent_of_float": 0.05,
    "short_ratio": 2.0,
    "shares_short": 1e6,
    "date_short_interest": None,
    "days_to_earnings": 20,
}


def make_frame(rows: dict[str, dict]) -> pd.DataFrame:
    frame = pd.DataFrame.from_dict({t: {"ticker": t, **DEFAULT_ROW, **r} for t, r in rows.items()}, orient="index")
    for name in sc.FACTOR_COLUMNS:
        if name not in frame.columns:
            frame[name] = 0.0
        frame[name] = frame[name].astype(float)
        frame[f"{name}_pct"] = frame[name].rank(pct=True)
    frame["composite"] = sc.composite_scores(
        frame, {"quality": 0.33, "price_momentum": 0.33, "revenue_momentum": 0.2, "eps_momentum": 0.14}
    )
    frame["composite_pct"] = frame["composite"].rank(pct=True)
    return frame


def preset(pid: str) -> IdeaScanPreset:
    return next(p for p in default_presets() if p.id == pid)


def filler(n: int, **overrides) -> dict[str, dict]:
    return {f"F{i:02d}": {"quality": float(i % 5), "price_momentum": float(i % 7), **overrides} for i in range(n)}


# ---------------------------------------------------------------------------
# Extracted screen helpers
# ---------------------------------------------------------------------------


def _quarterly(revenues: list[float], eps: list[float]) -> pd.DataFrame:
    cols = pd.date_range("2024-03-31", periods=len(revenues), freq="QE")[::-1]
    return pd.DataFrame(
        {c: {"Total Revenue": r, "Diluted EPS": e} for c, r, e in zip(cols, revenues, eps, strict=True)}
    )


def test_quarterly_growth_matches_year_ago_quarters():
    q = _quarterly([110, 120, 130, 140, 100, 100, 100], [1.1, 1.2, 1.3, 1.4, 1.0, 1.0, 1.0])
    out = compute_quarterly_growth(q)
    assert out["rev_yoy_q0"] == pytest.approx(10.0)
    assert out["rev_yoy_q2"] == pytest.approx(30.0)
    assert out["rev_yoy_avg"] == pytest.approx(20.0)
    assert out["eps_yoy_avg"] == pytest.approx(20.0)


def test_quarterly_growth_needs_five_quarters():
    out = compute_quarterly_growth(_quarterly([1, 2, 3, 4], [1, 2, 3, 4]))
    assert all(np.isnan(v) for v in out.values())
    assert all(np.isnan(v) for v in compute_quarterly_growth(None).values())


def test_price_metrics_from_one_year_of_closes():
    close = pd.Series(np.linspace(100, 150, 252))
    bench = pd.Series(np.linspace(100, 110, 252))
    m = compute_price_metrics(close, bench)
    assert m["return_52w"] == pytest.approx(50.0)
    assert m["drawdown_pct"] == pytest.approx(0.0)
    assert m["return_3m"] > 0 and m["rel_return_2m"] > 0


def test_long_predicate_sets_ebit_multiple():
    data = {"operating_income": 100.0, "market_cap": 1500.0}
    assert long_fundamentals_pass(
        data, pb_threshold=None, profit_type=None, check_ebit_multiple=True, max_ebit_multiple=20
    )
    assert data["ebit_multiple"] == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


def test_long_cheap_improving_hits_and_near_miss():
    frame = make_frame(
        {
            "CHEAP": {"price_to_book": 1.0, "rev_yoy_avg": 12.0, "eps_yoy_avg": 8.0, "net_issuance": -5e6},
            "ALMOST": {"price_to_book": 1.0, "rev_yoy_avg": 12.0, "eps_yoy_avg": 8.0, "net_issuance": 3e6},
            "NODATA": {"price_to_book": 1.0, "rev_yoy_avg": np.nan, "eps_yoy_avg": 8.0, "net_issuance": 3e6},
            **filler(5),
        }
    )
    result = sc.evaluate_preset(preset("long-cheap-improving"), frame)
    assert [h["ticker"] for h in result.hits] == ["CHEAP"]
    assert result.hits[0]["signals"][0].startswith("P/B 1.00 (< 1.5)")
    assert [m["ticker"] for m in result.near_misses] == ["ALMOST"]
    assert result.near_misses[0]["failed"] == ["Net buybacks (last fiscal year)"]


def test_short_expensive_deteriorating():
    frame = make_frame(
        {
            "EXP": {"price_to_book": 6.0, "operating_income": -20.0, "rev_yoy_avg": -4.0},
            "OK": {"price_to_book": 6.0, "operating_income": 20.0, "rev_yoy_avg": -4.0},
            **filler(5),
        }
    )
    result = sc.evaluate_preset(preset("short-expensive-deteriorating"), frame)
    assert [h["ticker"] for h in result.hits] == ["EXP"]
    assert result.hits[0]["direction"] == "short"
    assert [m["ticker"] for m in result.near_misses] == ["OK"]


def test_quality_value_is_sector_relative():
    rows = {f"T{i}": {"quality": float(i), "sector": "Technology", "enterpriseToEbitda": 30.0 - i} for i in range(10)}
    rows["CHEAPHQ"] = {"quality": 50.0, "sector": "Technology", "enterpriseToEbitda": 5.0}
    rows["PRICEYHQ"] = {"quality": 49.0, "sector": "Technology", "enterpriseToEbitda": 90.0}
    result = sc.evaluate_preset(preset("long-quality-fair-price"), make_frame(rows))
    hits = [h["ticker"] for h in result.hits]
    assert "CHEAPHQ" in hits
    assert "PRICEYHQ" not in hits


def test_value_momentum_quality_needs_all_three():
    rows = {
        f"T{i:02d}": {
            "quality": float(i),
            "price_momentum": float(i),
            "sector": "Industrials",
            "enterpriseToEbitda": 10.0 + i,
        }
        for i in range(20)
    }
    rows["VMQ"] = {"quality": 30.0, "price_momentum": 30.0, "sector": "Industrials", "enterpriseToEbitda": 4.0}
    rows["NOMOM"] = {"quality": 31.0, "price_momentum": -5.0, "sector": "Industrials", "enterpriseToEbitda": 5.0}
    rows["PRICEY"] = {"quality": 32.0, "price_momentum": 32.0, "sector": "Industrials", "enterpriseToEbitda": 80.0}
    result = sc.evaluate_preset(preset("long-value-momentum-quality"), make_frame(rows))
    assert [h["ticker"] for h in result.hits] == ["VMQ"]
    assert len(result.hits[0]["signals"]) == 3
    assert result.hits[0]["signals"][2].startswith("Price momentum percentile")
    misses = {m["ticker"]: m["failed"] for m in result.near_misses}
    assert misses["NOMOM"][0].startswith("Price momentum percentile")
    assert misses["PRICEY"][0].startswith("enterpriseToEbitda 80.0")


def test_composite_top_decile_uses_preset_weights():
    rows = {f"T{i:02d}": {"quality": float(i), "price_momentum": float(i)} for i in range(20)}
    result = sc.evaluate_preset(preset("long-momentum-quality"), make_frame(rows))
    assert {h["ticker"] for h in result.hits} == {"T17", "T18", "T19"}

    weighted = preset("long-momentum-quality").model_copy(deep=True)
    weighted.weights.quality = 0
    weighted.weights.price_momentum = 0
    weighted.weights.eps_momentum = 0
    rows = {f"T{i:02d}": {"quality": float(i), "revenue_momentum": float(-i)} for i in range(20)}
    result = sc.evaluate_preset(weighted, make_frame(rows))
    assert {h["ticker"] for h in result.hits} == {"T00", "T01", "T02"}


def test_breakdown_needs_negative_revisions():
    rows = {f"T{i:02d}": {"price_momentum": float(i)} for i in range(20)}
    frame = make_frame(rows)
    assert sc.breakdown_revision_tickers(frame, [preset("short-breaking-down")]) == ["T00", "T01", "T02"]
    result = sc.evaluate_preset(preset("short-breaking-down"), frame, revisions={"T00": -0.04, "T01": 0.02})
    assert [h["ticker"] for h in result.hits] == ["T00"]
    assert result.hits[0]["revision_30d"] == -0.04
    assert [m["ticker"] for m in result.near_misses] == ["T01"]


def test_preset_universe_scope_and_max_names():
    rows = {
        f"T{i:02d}": {"price_to_book": 1.0, "rev_yoy_avg": 10.0, "eps_yoy_avg": 10.0, "net_issuance": -1.0}
        for i in range(6)
    }
    rows["T05"]["universes"] = ["russell2000"]
    custom = preset("long-cheap-improving").model_copy(update={"universes": ["sp500"], "max_names": 3})
    result = sc.evaluate_preset(custom, make_frame(rows))
    assert result.evaluated == 5
    assert result.hits_total == 5
    assert len(result.hits) == 3


def test_disabled_preset_returns_nothing():
    off = preset("long-cheap-improving").model_copy(update={"enabled": False})
    assert sc.evaluate_preset(off, make_frame({"A": {}})).hits == []


# ---------------------------------------------------------------------------
# Merge, macro, tracked, near-misses, week over week
# ---------------------------------------------------------------------------


def _three_preset_frame() -> pd.DataFrame:
    rows = {f"T{i:02d}": {"quality": float(i), "price_momentum": float(i), "sector": "Utilities"} for i in range(20)}
    rows["T19"].update(
        {"price_to_book": 1.0, "rev_yoy_avg": 10.0, "eps_yoy_avg": 10.0, "net_issuance": -1.0, "sector": "Technology"}
    )
    rows["T18"].update({"sector": "Energy"})
    rows["T00"].update({"price_to_book": 8.0, "operating_income": -1.0, "rev_yoy_avg": -3.0, "sector": "Energy"})
    return make_frame(rows)


def test_name_hitting_several_presets_becomes_one_candidate():
    frame = _three_preset_frame()
    results = [
        sc.evaluate_preset(preset(pid), frame)
        for pid in ("long-cheap-improving", "long-momentum-quality", "short-expensive-deteriorating")
    ]
    candidates = sc.merge_candidates(results, frame)
    by_key = {(c["ticker"], c["direction"]): c for c in candidates}
    multi = by_key[("T19", "long")]
    assert multi["preset_count"] == 2
    assert {p["id"] for p in multi["presets"]} == {"long-cheap-improving", "long-momentum-quality"}
    assert multi["agreement_score"] > by_key[("T18", "long")]["agreement_score"]
    assert candidates[0]["ticker"] == "T19"
    short = by_key[("T00", "short")]
    assert short["short_data"]["short_percent_of_float"] == 0.05
    assert short["short_data"]["borrow"] is None


def test_macro_only_raises_ranks():
    frame = _three_preset_frame()
    results = [
        sc.evaluate_preset(preset(pid), frame) for pid in ("long-momentum-quality", "short-expensive-deteriorating")
    ]
    candidates = sc.merge_candidates(results, frame)
    rows = [
        {"sector": "Energy", "score": -2, "confidence": "high", "reason": "oil glut"},
        {"sector": "Technology", "score": -1, "confidence": "high", "reason": "capex digestion"},
    ]
    adjusted = {(c["ticker"], c["direction"]): c for c in sc.apply_macro(candidates, rows)}
    assert len(adjusted) == len(candidates)
    energy_short = adjusted[("T00", "short")]
    assert energy_short["macro_boost"] == pytest.approx(0.5)
    assert energy_short["macro_fit"]["fit"] == "tailwind"
    energy_long = adjusted[("T18", "long")]
    assert energy_long["macro_boost"] == 0
    assert energy_long["final_score"] == pytest.approx(energy_long["agreement_score"])
    assert energy_long["macro_fit"]["fit"] == "headwind"


def test_tracked_names_are_split_out():
    frame = _three_preset_frame()
    candidates = sc.merge_candidates([sc.evaluate_preset(preset("long-momentum-quality"), frame)], frame)
    fresh, already = sc.split_tracked(candidates, {"T19": "position"})
    assert "T19" not in {c["ticker"] for c in fresh}
    assert already == [
        {
            "ticker": "T19",
            "direction": "long",
            "company": "Co",
            "tracked_as": "position",
            "presets": [{"id": "long-momentum-quality", "name": "Long · Momentum + quality"}],
            "final_score": candidates[0]["final_score"],
        }
    ]


def test_near_misses_exclude_candidates_and_dedupe():
    frame = _three_preset_frame()
    results = [sc.evaluate_preset(preset(pid), frame) for pid in ("long-cheap-improving", "long-momentum-quality")]
    candidates = sc.merge_candidates(results, frame)
    misses = sc.collect_near_misses(results, candidates, frame, limit=10)
    taken = {(c["ticker"], c["direction"]) for c in candidates}
    assert misses and not any((m["ticker"], m["direction"]) in taken for m in misses)
    assert len({(m["ticker"], m["direction"]) for m in misses}) == len(misses)
    assert all(m["failed_check"] for m in misses)


def test_week_over_week_changes():
    now = [{"ticker": "A", "direction": "long"}, {"ticker": "B", "direction": "short"}]
    before = [{"ticker": "B", "direction": "short"}, {"ticker": "C", "direction": "long"}]
    changes = sc.week_over_week(now, before)
    assert [c["ticker"] for c in changes["new"]] == ["A"]
    assert [c["ticker"] for c in changes["still"]] == ["B"]
    assert [c["ticker"] for c in changes["dropped"]] == ["C"]
    assert sc.week_over_week(now, None)["dropped"] == []


def test_json_safe_strips_nan_and_numpy():
    assert sc.json_safe({"a": np.float64("nan"), "b": [np.int64(3), float("inf")]}) == {"a": None, "b": [3, None]}


# ---------------------------------------------------------------------------
# Factor frame from statements
# ---------------------------------------------------------------------------


def _statements(seed: int, *, pb: float, grow: float, buyback: bool) -> TickerFundamentals:
    years = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"])
    quarters = pd.date_range("2024-03-31", periods=7, freq="QE")[::-1]
    base = 1000.0 + seed * 10
    annual = pd.DataFrame(
        {
            d: {
                "Total Revenue": base * (1 + grow) ** (3 - i),
                "Gross Profit": base * 0.4 * (1 + grow) ** (3 - i),
                "Operating Income": base * 0.1,
                "Net Income": base * 0.08 * (1 + grow) ** (3 - i),
                "Diluted EPS": 1.0 * (1 + grow) ** (3 - i),
            }
            for i, d in enumerate(years)
        }
    )
    quarterly = pd.DataFrame(
        {
            d: {
                "Total Revenue": base / 4 * (1 + grow) ** ((6 - i) / 4),
                "Diluted EPS": 0.25 * (1 + grow) ** ((6 - i) / 4),
            }
            for i, d in enumerate(quarters)
        }
    )
    balance = pd.DataFrame(
        {
            d: {
                "Total Assets": base * 2,
                "Stockholders Equity": base,
                "Total Current Assets": base / 2,
                "Total Current Liabilities": base / 4,
            }
            for d in years
        }
    )
    cashflow = pd.DataFrame(
        {
            d: {
                "Operating Cash Flow": base * 0.1,
                "Repurchase Of Capital Stock": -50.0 if buyback else 0.0,
                "Issuance Of Capital Stock": 0.0 if buyback else 80.0,
            }
            for d in years
        }
    )
    return TickerFundamentals(
        info={
            "longName": f"Co {seed}",
            "sector": "Technology",
            "priceToBook": pb,
            "marketCap": base * pb,
            "sharesOutstanding": 1000.0,
            "earningsTimestamp": 4102444800,
        },
        financials=annual,
        quarterly_financials=quarterly,
        balance_sheet=balance,
        cashflow=cashflow,
    )


def test_build_factor_frame_from_shared_statements():
    days = pd.bdate_range(end="2026-10-23", periods=800)
    rng = np.random.default_rng(1)
    tickers = [f"S{i}" for i in range(12)]
    prices = pd.DataFrame(
        {t: 100 * np.exp(np.cumsum(rng.normal(0.0005 * (i - 6), 0.01, len(days)))) for i, t in enumerate(tickers)},
        index=days,
    )
    for bench in ("SPY", "MDY", "IJR", "IWM"):
        prices[bench] = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, len(days))))
    fundamentals = {
        t: _statements(i, pb=0.8 + i * 0.3, grow=0.02 * i, buyback=i % 2 == 0) for i, t in enumerate(tickers)
    }
    fundamentals["BROKEN"] = TickerFundamentals(error="no data returned")
    # Quote data missing (expired crumb) but statements loaded: still scored, sector unknown.
    no_quote = _statements(5, pb=1.0, grow=0.05, buyback=True)
    fundamentals["NOQUOTE"] = TickerFundamentals(
        error="info: HTTP Error 401 Invalid Crumb",
        financials=no_quote.financials,
        quarterly_financials=no_quote.quarterly_financials,
        balance_sheet=no_quote.balance_sheet,
        cashflow=no_quote.cashflow,
    )
    dataset = ScanDataset(
        key="test",
        membership={t: ["sp500"] for t in [*tickers, "BROKEN", "NOQUOTE"]},
        prices=prices,
        fundamentals=fundamentals,
        failed={"BROKEN": "no data returned"},
        fetched_at="2026-10-24T00:00:00+00:00",
    )
    frame = sc.build_factor_frame(dataset, now=pd.Timestamp("2026-10-24", tz="UTC").to_pydatetime())
    assert set(frame.index) == {*tickers, "NOQUOTE"}
    assert frame.loc["NOQUOTE"]["sector"] == "Unknown" and frame.loc["NOQUOTE"]["quality_pct"] > 0
    for col in ("quality_pct", "price_momentum_pct", "eps_momentum_pct", "revenue_momentum_pct", "composite_pct"):
        assert frame.loc[tickers, col].notna().all(), col
    s0 = frame.loc["S0"]
    assert s0["price_to_book"] == pytest.approx(0.8)
    assert s0["net_issuance"] == pytest.approx(-50.0)
    assert frame.loc["S1"]["net_issuance"] == pytest.approx(80.0)
    assert frame.loc["S11"]["rev_yoy_avg"] > frame.loc["S1"]["rev_yoy_avg"]
    assert s0["days_to_earnings"] > 0
    # Strongest drift should rank above the weakest on price momentum.
    assert frame.loc["S11"]["price_momentum_pct"] > frame.loc["S0"]["price_momentum_pct"]
