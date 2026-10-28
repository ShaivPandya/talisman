"""Macro view, quick reviews and Scout records, with stubbed LLM responses."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import llm_utils
from api.idea_scan import macro_view as mv
from api.idea_scan import review as rv
from api.idea_scan.budget import RunBudget

SNAPSHOTS = [{"key": "liquidity:current:v1", "as_of": "2026-10-23", "stale": False, "text": "{}"}]


def _row(sector, score, *, evidence=None, explanation="", confidence="medium"):
    return {
        "sector": sector,
        "score": score,
        "confidence": confidence,
        "reason": f"{sector} reason",
        "evidence": evidence
        if evidence is not None
        else [{"type": "snapshot", "ref": "liquidity:current:v1", "detail": "x"}],
        "change_explanation": explanation,
    }


def test_validate_rows_requires_evidence_and_explained_changes():
    raw = [
        _row("Technology", 2),
        _row("Health Care", -1, evidence=[{"type": "search", "ref": "https://news.example.com/a/", "detail": "y"}]),
        _row("Energy", 1, evidence=[]),
        _row("Utilities", 1, evidence=[{"type": "snapshot", "ref": "made_up:key", "detail": "z"}]),
        _row("Financials", 2),
        _row("Industrials", 1, explanation="PMI turned up"),
        _row("Crypto", 1),
        _row("Technology", 1),
        _row("Real Estate", 5),
    ]
    rows, dropped = mv.validate_rows(
        raw,
        snapshot_keys={"liquidity:current:v1"},
        citation_urls=["https://news.example.com/a"],
        previous_scores={"Financial Services": 0, "Industrials": 0, "Technology": 2},
    )
    assert [(r["sector"], r["score"]) for r in rows] == [("Healthcare", -1), ("Industrials", 1), ("Technology", 2)]
    assert all(r["origin"] == "llm" and r["evidence"] for r in rows)
    assert rows[1]["change_explanation"] == "PMI turned up"
    assert rows[2]["change_explanation"] == "" and rows[2]["previous_score"] == 2
    reasons = {d["sector"]: d["reason"] for d in dropped}
    assert reasons["Energy"] == "no verifiable evidence"
    assert reasons["Utilities"] == "no verifiable evidence"
    assert reasons["Financial Services"] == "score changed without an explanation"
    assert reasons["Crypto"] == "unknown sector"
    assert reasons["Technology"] == "duplicate row"
    assert reasons["Real Estate"] == "score outside -2..+2"


def test_run_macro_view_with_stubbed_call():
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        llm_utils._notify_response_observer("anthropic", "claude-opus-5-5", _usage(20_000, 3_000, searches=2))
        return (
            {"summary": "Mixed backdrop.", "rows": [_row("Technology", 1), _row("Energy", -1, evidence=[])]},
            [("Story", "https://news.example.com/s")],
            None,
            {"status": "ok"},
        )

    budget = RunBudget(2.0)
    view = mv.run_macro_view(
        budget=budget,
        previous_view={"rows": [{"sector": "Technology", "score": 1}]},
        searches=5,
        reserve_usd=0.1,
        snapshots=SNAPSHOTS,
        call=fake,
    )
    assert view["status"] == "ok"
    assert [r["sector"] for r in view["rows"]] == ["Technology"]
    assert view["dropped"] == [{"sector": "Energy", "reason": "no verifiable evidence"}]
    assert view["sources"] == [{"title": "Story", "url": "https://news.example.com/s"}]
    assert calls[0]["max_web_search_uses"] == 5 and calls[0]["model"] == llm_utils.MODEL_HIGH
    assert "Technology: score 1" in calls[0]["prompt"]
    assert budget.spent_usd == pytest.approx(0.08 + 0.06 + 0.02)


def test_macro_view_skipped_when_budget_cannot_cover_it():
    budget = RunBudget(0.3)
    view = mv.run_macro_view(
        budget=budget, previous_view=None, searches=5, reserve_usd=0.1, snapshots=SNAPSHOTS, call=pytest.fail
    )
    assert view["status"] == "skipped"
    assert view["rows"] == []
    assert budget.skipped == [{"step": "macro", "label": "Sector macro view", "reason": "budget"}]


def test_gather_snapshots_compacts_and_skips_missing():
    payload = {
        "series": list(range(100)),
        "latest": 1.23456789,
        "_meta": {"snapshot": {"as_of": "2026-10-23", "stale": True}},
    }
    out = mv.gather_snapshots(read=lambda key: payload if key == "liquidity:current:v1" else None)
    assert [s["key"] for s in out] == ["liquidity:current:v1"]
    assert out[0]["stale"] is True
    assert '"series":[97,98,99]' in out[0]["text"] and "1.2346" in out[0]["text"]


@pytest.mark.parametrize(
    "text",
    [
        "We recommend buying the stock ahead of earnings.",
        "Investors should short this name.",
        "It is a buy at these levels.",
        "Our price target is $40.",
        "Consider going long into the print.",
        "Initiate a short position.",
    ],
)
def test_scrub_removes_recommendations(text):
    cleaned, flagged = rv.scrub_recommendation_language(f"Revenue fell 8%. {text}")
    assert flagged
    assert cleaned == "Revenue fell 8%."


@pytest.mark.parametrize(
    "text",
    [
        "Short interest is 18% of float with 6 days to cover.",
        "The company bought back 4% of shares last year.",
        "Insiders sold shares under 10b5-1 plans.",
        "The short screen flagged a negative operating margin.",
    ],
)
def test_scrub_keeps_research_language(text):
    assert rv.scrub_recommendation_language(text) == (text, False)


def test_sourced_headlines_drop_unreturned_urls():
    raw = [
        {"title": "Real", "url": "https://news.example.com/a/", "date": "2026-10-20"},
        {"title": "Invented", "url": "https://nowhere.example/b", "date": ""},
    ]
    assert rv.sourced_headlines(raw, [("Real story", "https://news.example.com/a")]) == [
        {"title": "Real", "url": "https://news.example.com/a", "date": "2026-10-20"}
    ]


def _usage(input_tokens, output_tokens, searches=0):
    return SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            server_tool_use=SimpleNamespace(web_search_requests=searches),
        )
    )


SHORT_CANDIDATE = {
    "ticker": "EXP",
    "direction": "short",
    "company": "Expensive Co",
    "sector": "Technology",
    "industry": "Software",
    "presets": [{"id": "short-expensive-deteriorating", "name": "Short · Expensive & deteriorating"}],
    "signals": [{"preset_id": "short-expensive-deteriorating", "label": "Operating Loss"}],
    "factor_ranks": {"composite_pct": 0.05},
    "metrics": {"return_52w": -30.0, "return_3m": -12.0, "price_to_book": 7.1},
    "short_data": {"short_percent_of_float": None, "short_ratio": None},
    "days_to_earnings": 9,
    "agreement_score": 1.9,
    "final_score": 2.1,
}
FILINGS = {
    "status": "ok",
    "eight_k": [
        {"date": "2026-10-01", "form": "8-K", "items": ["officer or director change"], "url": "https://www.sec.gov/x"}
    ],
    "form4": {"purchases": 0, "sales": 3, "other": 1, "rows": []},
}


def test_review_candidate_with_stubbed_call():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        llm_utils._notify_response_observer("anthropic", "claude-sonnet-5-5", _usage(12_000, 1_500, searches=2))
        return (
            {
                "trigger": "Operating losses with shrinking revenue.",
                "why_now": "Guidance cut last week. Investors should short this name.",
                "consensus": "Market expects a recovery in 2027.",
                "variant_view": "Cash burn suggests dilution first.",
                "headlines": [
                    {"title": "Guidance cut", "url": "https://news.example.com/g", "date": "2026-10-21"},
                    {"title": "Made up", "url": "https://fake.example.com/z", "date": ""},
                ],
                "macro_fit": "Sector headwind supports the short thesis.",
                "missing_inputs": ["Debt maturities"],
                "next_action": "watch",
            },
            [("Guidance cut", "https://news.example.com/g")],
            None,
            {"status": "ok"},
        )

    budget = RunBudget(2.0)
    review = rv.review_candidate(
        SHORT_CANDIDATE,
        macro_row={"sector": "Technology", "score": -1, "confidence": "high", "reason": "capex digestion"},
        budget=budget,
        searches=2,
        filings=FILINGS,
        call=fake,
    )
    assert review["status"] == "ok"
    assert review["why_now"] == "Guidance cut last week."
    assert review["language_flagged"] is True
    assert review["headlines"] == [{"title": "Guidance cut", "url": "https://news.example.com/g", "date": "2026-10-21"}]
    assert rv.BORROW_MISSING in review["missing_inputs"]
    assert "Short interest (not reported by the data source)" in review["missing_inputs"]
    assert "Recent news (fewer than two sourced headlines found)" in review["missing_inputs"]
    assert review["cost_usd"] == pytest.approx(0.024 + 0.015 + 0.02)
    assert captured["max_web_search_uses"] == 2 and captured["model"] == llm_utils.MODEL_MID
    prompt = captured["prompt"]
    assert "Days to next earnings: 9" in prompt and "officer or director change" in prompt
    assert "3 open-market sales" in prompt and "capex digestion" in prompt

    record = rv.build_scout_record(
        SHORT_CANDIDATE,
        review,
        run_id="r1",
        week="2026-W44",
        screen_kinds={"short-expensive-deteriorating": "short_screen"},
    )
    assert record is not None
    assert record["candidate_id"] == "idea_scan_2026w44_short_exp"
    assert record["next_action"] == "watch"
    assert record["opportunity_type"] == "unsustainable_process"
    assert record["opportunity_candidate_gate"]["status"] in {"pass", "downgraded"}
    assert "short this name" not in str(record).lower()
    assert any(ref.get("source_path") == "idea_scan_run:r1" for ref in record["source_refs"])


def test_review_failure_is_reported_not_raised():
    def broken(**_kwargs):
        raise TimeoutError("slow")

    review = rv.review_candidate(
        SHORT_CANDIDATE, macro_row=None, budget=RunBudget(2.0), searches=2, filings=FILINGS, call=broken
    )
    assert review["status"] == "failed"
    assert "TimeoutError" in review["error"]


def test_recent_filings_reads_8k_items(monkeypatch):
    from portfolio.momentum.fundamental_momentum import edgar_fetcher as edgar

    submissions = {
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q", "8-K", "4"],
                "filingDate": ["2026-10-20", "2026-10-10", "2025-01-01", "2026-10-15"],
                "accessionNumber": ["a1", "a2", "a3", "a4"],
                "primaryDocument": ["d1.htm", "d2.htm", "d3.htm", "d4.xml"],
                "items": ["2.02,9.01", "", "5.02", ""],
            }
        }
    }
    monkeypatch.setattr(edgar, "get_cik_for_ticker", lambda _t: "0000000001")
    monkeypatch.setattr(edgar, "fetch_submissions_by_cik", lambda _c: submissions)
    monkeypatch.setattr(
        "api.public_dataset_adapters.sec_form4",
        lambda _client, _p: {
            "snapshot": {"records": [{"transaction_code": "P"}, {"transaction_code": "S"}, {"transaction_code": "A"}]}
        },
    )
    from datetime import UTC, datetime

    out = rv.recent_filings("XYZ", now=datetime(2026, 10, 28, tzinfo=UTC))
    assert [f["items"] for f in out["eight_k"]] == [["results of operations", "9.01"]]
    assert out["form4"]["purchases"] == 1 and out["form4"]["sales"] == 1 and out["form4"]["other"] == 1


def test_macro_evidence_checks_against_search_hits_without_inline_citations():
    def fake(**_kwargs):
        response = _usage(10_000, 1_000, searches=1)
        response.content = [
            SimpleNamespace(
                type="web_search_tool_result",
                content=[SimpleNamespace(type="web_search_result", url="https://news.example.com/oil", title="Oil")],
            )
        ]
        llm_utils._notify_response_observer("anthropic", "claude-opus-5-5", response)
        rows = [
            _row(
                "Energy", 2, evidence=[{"type": "search", "ref": "https://news.example.com/oil", "detail": "Brent up"}]
            ),
            _row("Utilities", -1, evidence=[{"type": "search", "ref": "https://made.up/x", "detail": "?"}]),
        ]
        return {"summary": "s", "rows": rows}, [], None, {"status": "ok"}

    view = mv.run_macro_view(
        budget=RunBudget(2.0), previous_view=None, searches=5, reserve_usd=0.1, snapshots=SNAPSHOTS, call=fake
    )
    assert [r["sector"] for r in view["rows"]] == ["Energy"]
    assert view["dropped"] == [{"sector": "Utilities", "reason": "no verifiable evidence"}]
    assert view["sources"] == [{"title": "Oil", "url": "https://news.example.com/oil"}]


def test_review_headlines_check_against_search_hits():
    def fake(**_kwargs):
        response = _usage(10_000, 1_000, searches=2)
        response.content = [
            SimpleNamespace(
                type="web_search_tool_result",
                content=[
                    SimpleNamespace(type="web_search_result", url="https://news.example.com/g", title="Guidance cut"),
                    SimpleNamespace(type="web_search_result", url="https://news.example.com/h", title="Insider sale"),
                ],
            )
        ]
        llm_utils._notify_response_observer("anthropic", "claude-sonnet-5-5", response)
        parsed = {
            "trigger": "t",
            "why_now": "w",
            "consensus": "c",
            "variant_view": "v",
            "macro_fit": "m",
            "headlines": [
                {"title": "Guidance cut", "url": "https://news.example.com/g", "date": "2026-10-21"},
                {"title": "Insider sale", "url": "https://news.example.com/h/", "date": "2026-10-22"},
            ],
            "missing_inputs": [],
            "next_action": "research",
        }
        return parsed, [], None, {"status": "ok"}

    review = rv.review_candidate(
        SHORT_CANDIDATE, macro_row=None, budget=RunBudget(2.0), searches=2, filings=FILINGS, call=fake
    )
    assert [h["url"] for h in review["headlines"]] == ["https://news.example.com/g", "https://news.example.com/h"]
    assert "Recent news (fewer than two sourced headlines found)" not in review["missing_inputs"]


def test_borrow_gap_is_not_listed_twice():
    def fake(**_kwargs):
        parsed = {
            "trigger": "t",
            "why_now": "w",
            "consensus": "c",
            "variant_view": "v",
            "macro_fit": "m",
            "headlines": [],
            "missing_inputs": ["Borrow cost: 40% short interest suggests a hard-to-borrow name"],
            "next_action": "watch",
        }
        return parsed, [], None, {"status": "ok"}

    review = rv.review_candidate(
        SHORT_CANDIDATE, macro_row=None, budget=RunBudget(2.0), searches=2, filings=FILINGS, call=fake
    )
    assert sum("borrow" in item.lower() for item in review["missing_inputs"]) == 1
    assert rv.BORROW_MISSING not in review["missing_inputs"]
