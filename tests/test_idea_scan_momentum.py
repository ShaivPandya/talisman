"""Behavioral checks for categorical momentum, independent of the sampled universe."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from api.idea_scan import momentum as m
from api.idea_scan import screening as sc
from api.idea_scan.data import ScanDataset
from api.idea_scan.presets import IdeaScanPreset

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def evidence(stock_return=12.0, benchmark_return=8.0):
    dates = m._sessions("2026-10-23")
    stock = pd.Series(np.linspace(100, 100 + stock_return, len(dates)), index=dates)
    bench = pd.Series(np.linspace(100, 100 + benchmark_return, len(dates)), index=dates)
    return m.calculate_momentum(stock, bench, "IWM", now=NOW)


@pytest.mark.parametrize(
    "stock,benchmark,long_credit,short_credit",
    [
        (100, 10, 1, 0),
        (50, 10, 1, 0),
        (10, 20, 0.5, 0.5),
        (-10, -20, 0.5, 0.5),
        (-50, -10, 0, 1),
        (-80, -10, 0, 1),
        (0, 0, 0, 0),
        (10, 10, 0.5, 0),
        (0, -10, 0.5, 0),
    ],
)
def test_directional_credit(stock, benchmark, long_credit, short_credit):
    row = evidence(stock, benchmark)
    assert row["momentum_benchmark_return"] == pytest.approx(benchmark)
    assert row["momentum_excess_return"] == pytest.approx(stock - benchmark)
    assert m.momentum_evidence(row, "long")["credit"] == long_credit
    assert m.momentum_evidence(row, "short")["credit"] == short_credit
    assert m.momentum_check(pd.Series(row), "long", "either")[1] == (long_credit > 0)
    assert m.momentum_check(pd.Series(row), "short", "either")[1] == (short_credit > 0)


@pytest.mark.parametrize("direction,returns", [("long", [50, 100]), ("short", [-20, -80])])
def test_magnitude_cannot_change_ranking_or_preset_admission(direction, returns):
    rows = {
        ticker: {
            **evidence(ret, 0),
            "quality": 0.0,
            "revenue_momentum": 0.0,
            "eps_momentum": 0.0,
            "universes": ["russell2000"],
        }
        for ticker, ret in zip(["AAA", "BBB"], returns, strict=True)
    }
    frame = pd.DataFrame.from_dict(rows, orient="index")
    weights = {"quality": 0.33, "price_momentum": 0.33, "revenue_momentum": 0.2, "eps_momentum": 0.14}
    scores = sc.composite_scores(frame, weights, direction)
    assert scores["AAA"] == scores["BBB"] == pytest.approx(0.33)
    preset = IdeaScanPreset(
        id="signal",
        name="Signal",
        screen="percentile_rules",
        direction=direction,
        params={"momentum_requirement": "either"},
    )
    hits = sc.evaluate_preset(preset, frame.iloc[::-1]).hits
    assert [h["ticker"] for h in hits] == ["AAA", "BBB"], "ties are stable regardless of input order"
    assert hits[0]["preset_score"] == hits[1]["preset_score"]


@pytest.mark.parametrize(
    "defect", ["missing_benchmark", "stale_benchmark", "stale_stock", "short_history", "missing_start", "invalid_price"]
)
def test_unavailable_evidence_and_fixed_allocation(defect):
    dates = m._sessions("2026-10-23")
    stock = pd.Series(np.linspace(100, 120, len(dates)), index=dates)
    bench = pd.Series(np.linspace(100, 110, len(dates)), index=dates)
    if defect == "missing_benchmark":
        bench = None
    if defect == "stale_benchmark":
        bench = bench.iloc[:-1]
    if defect == "stale_stock":
        stock = stock.iloc[:-1]
    if defect == "short_history":
        stock = stock.iloc[2:]
    if defect == "missing_start":
        stock.iloc[0] = np.nan
    if defect == "invalid_price":
        stock.iloc[-1] = np.inf
    row = m.calculate_momentum(stock, bench, "IWM", now=NOW)
    assert row["momentum_relative_state"] == "unavailable"
    partial = defect in {"missing_benchmark", "stale_benchmark"}
    assert row["momentum_absolute_state"] == ("positive" if partial else "unavailable")
    frame = pd.DataFrame([row])
    score = sc.composite_scores(frame, {"price_momentum": 1.0})[0]
    assert score == 0.5 if partial else pd.isna(score)
    check = m.momentum_check(pd.Series(row), "long", "either")
    assert check[1] is partial and check[2] is partial
    assert m.momentum_check(pd.Series(row), "long", "both")[1:] == (False, False)


def test_flat_is_observed_not_missing_and_has_no_credit():
    frame = pd.DataFrame([evidence(0, 0)])
    credit, coverage = m.momentum_credit(frame, "long")
    assert credit[0] == 0 and coverage[0] == 1
    assert sc.composite_scores(frame, {"price_momentum": 1.0})[0] == 0


def test_market_calendar_weekend_holiday_and_partial_session():
    dates = m._sessions("2026-11-25")
    close = pd.Series(np.linspace(100, 120, len(dates)), index=dates.tz_localize("America/New_York"))
    # Thanksgiving is not a session; Friday morning still uses Wednesday's close.
    for now in (datetime(2026, 11, 26, 22, tzinfo=UTC), datetime(2026, 11, 27, 15, tzinfo=UTC)):
        row = m.calculate_momentum(close, close, "SPY", now=now)
        assert row["momentum_end_date"] == "2026-11-25"
        assert row["momentum_absolute_state"] == "positive"
        assert row["momentum_relative_state"] == "flat"


def test_benchmarks_and_overlap_precedence():
    membership = {
        "L": ["sp500"],
        "M": ["sp400"],
        "S": ["sp600"],
        "R": ["russell2000"],
        "BOTH": ["russell2000", "sp600"],
        "ALL": ["russell2000", "sp600", "sp400", "sp500"],
    }
    dataset = ScanDataset("test", membership, pd.DataFrame(), {}, {}, "")
    assert {t: dataset.primary_benchmark(t) for t in membership} == {
        "L": "SPY",
        "M": "MDY",
        "S": "IJR",
        "R": "IWM",
        "BOTH": "IJR",
        "ALL": "SPY",
    }


def test_no_data_is_not_an_ordinary_near_miss():
    row = evidence(-10, 0)
    row["momentum_relative_state"] = "unavailable"
    row.update(quality=1, eps_momentum=1, revenue_momentum=1, universes=["sp500"])
    frame = pd.DataFrame([row], index=["AAA"])
    preset = IdeaScanPreset(
        id="test", name="Test", screen="percentile_rules", direction="long", params={"momentum_requirement": "either"}
    )
    result = sc.evaluate_preset(preset, frame)
    assert result.hits == [] and result.near_misses == []


def test_empty_current_frame_is_compatible_but_unversioned_is_not():
    frame = pd.DataFrame()
    assert not m.compatible_frame(frame)
    frame.attrs["momentum_version"] = 2
    assert m.compatible_frame(frame)


def test_evidence_is_carried_into_review_and_promoted_notes():
    from api.idea_scan.review import build_prompt
    from api.routers.idea_scan import card_notes

    card = {
        "ticker": "AAA",
        "company": "Alpha",
        "direction": "short",
        "momentum": m.momentum_evidence(evidence(-12, -5), "short"),
    }
    prompt = build_prompt(card, macro_row=None, filings={}, searches=0)
    notes = card_notes({"week": "2026-W44", "run_id": "test"}, card)
    for content in (prompt, notes):
        assert "Down over 3 months: Yes (-12.00%)" in content
        assert "Underperforming IWM over 3 months: Yes (-7.00 percentage points)" in content
    assert "fixed half credit" in prompt
    assert "price momentum percentile" not in prompt.lower()
