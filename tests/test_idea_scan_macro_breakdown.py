"""Four macro lenses retain source coverage and fail closed on invented evidence."""

import json

import llm_utils
from api import snapshot_keys as keys
from api.idea_scan import macro_inputs
from api.idea_scan import macro_view as mv
from api.idea_scan.budget import RunBudget
from macro.industry import industry_monitor as im
from tests.test_idea_scan_llm_steps import _usage


def monitor(*, stale=False, usable=True):
    return {
        "last_updated": "2026-11-02",
        "by_sector": {
            "Trucking": {
                "companies": [
                    {
                        "ticker": "ODFL",
                        "call_date": "2026-10-20",
                        "is_stale": stale,
                        "summary_available": usable,
                        "missing_data": False,
                        "demand_trends": "Freight volumes slowing",
                        "summary_headline": "Cautious guidance",
                    }
                ]
            }
        },
    }


def test_fresh_monitor_uses_transcript_date_without_refresh():
    calls = []

    def load(**kwargs):
        calls.append(kwargs)
        return monitor()

    result = macro_inputs.gather_industry_monitor(RunBudget(2), reserve_usd=0.7, load=load)
    assert calls == [{"refresh": False}]
    assert result["as_of"] == "2026-10-20"
    assert result["available"] and not result["refreshed"] and not result["stale"]
    assert "Freight volumes slowing" in result["text"]


def test_stale_monitor_refreshes_before_evidence_is_read_and_accounts_for_cost(monkeypatch):
    def summarize(text, meta):
        llm_utils._notify_response_observer("anthropic", "claude-sonnet-5-5", _usage(1000, 500))
        return {"summary_headline": "New commentary"}

    monkeypatch.setattr(im, "summarize_with_llm", summarize)

    def load(**kwargs):
        if kwargs["refresh"]:
            assert kwargs["summarize"]("transcript", {"ticker": "ODFL"})["summary_headline"] == "New commentary"
            return monitor()
        return monitor(stale=True)

    budget = RunBudget(2)
    result = macro_inputs.gather_industry_monitor(budget, reserve_usd=0.7, load=load)
    assert result["refreshed"] and not result["stale"]
    assert budget.summary()["by_step"]["industry"] > 0


def test_refresh_budget_does_not_spend_reserved_macro_budget(monkeypatch):
    monkeypatch.setattr(im, "summarize_with_llm", lambda *args: (_ for _ in ()).throw(AssertionError("spent budget")))

    def load(**kwargs):
        if kwargs["refresh"]:
            assert kwargs["summarize"]("transcript", {"ticker": "ODFL"}) is None
        return monitor(usable=False)

    budget = RunBudget(0.8)
    result = macro_inputs.gather_industry_monitor(budget, reserve_usd=0.7, load=load)
    assert not result["available"] and result["stale"]
    assert "Freight volumes slowing" not in result["text"]
    assert budget.skipped[0]["step"] == "industry"
    assert budget.can_start("macro", reserve_usd=0.1)


def test_refresh_failure_preserves_old_evidence_with_explicit_warning():
    def load(**kwargs):
        if kwargs["refresh"]:
            raise TimeoutError("slow")
        return monitor(stale=True)

    result = macro_inputs.gather_industry_monitor(RunBudget(2), reserve_usd=0.7, load=load)
    assert result["stale"] and result["available"] and not result["refreshed"]
    assert "Refresh failed" in result["warning"]
    assert result["as_of"] == "2026-10-20"


def test_snapshot_compaction_keeps_all_asset_classes_and_early_indicator_readings():
    data = {
        keys.SNAPSHOT_ECONOMIC_GROWTH: {
            "equities": {f"Index {i}": {"1-mo": i, "3-mo": 2, "6-mo": 3, "1-yr": 4} for i in range(40)},
            "equity_relative_returns": {f"Index {i}": {"1-mo": i, "3-mo": 2} for i in range(40)},
            "currencies": {"AUD/JPY": {"1-mo": 1.2}},
            "commodities": {"Copper": {"1-mo": -2}},
        },
        keys.SNAPSHOT_ECONOMIC_BACKDROP: {
            "readings": [
                {"key": f"indicator-{i}", "as_of": "2026-10-01", "value": i, "kind": "observation"} for i in range(25)
            ]
        },
    }
    snapshots = {s["key"]: json.loads(s["text"]) for s in mv.gather_snapshots(read=data.get)}
    growth = snapshots[keys.SNAPSHOT_ECONOMIC_GROWTH]
    assert growth["equities"]["Index 0"]["1-mo"] == 0
    assert growth["currencies"]["AUD/JPY"]["1-mo"] == 1.2
    assert growth["commodities"]["Copper"]["1-mo"] == -2
    assert len(snapshots[keys.SNAPSHOT_ECONOMIC_BACKDROP]["readings"]) == 25


def breakdown():
    refs = [macro_inputs.INDUSTRY_KEY, keys.SNAPSHOT_ECONOMIC_GROWTH, keys.SNAPSHOT_ECONOMIC_BACKDROP]
    evidence = [{"type": "snapshot", "ref": ref, "detail": "Dated source fact"} for ref in refs]
    evidence.append({"type": "search", "ref": "https://news.example.com/oil", "detail": "Supply disruption"})
    return {
        "approaches": {
            key: {
                "signal": "Observed fact",
                "interpretation": "Conditional inference",
                "confidence": "high",
                "caveats": "Evidence has limitations",
                "evidence": [evidence[index]],
            }
            for index, key in enumerate(mv.APPROACHES)
        },
        "synthesis": {
            "outlook": "Slower growth with supply-driven inflation",
            "horizon": "Next quarter",
            "confidence": "high",
            "agreements": "Demand weakening",
            "conflicts": "Copper diverges",
            "watchpoints": ["Reassess if industrial production accelerates"],
            "evidence": evidence,
        },
    }, [{"key": ref, "stale": False, "as_of": "2026-10-20", "text": "{}"} for ref in refs]


def test_breakdown_validates_every_lens_and_preserves_conditional_synthesis():
    parsed, snapshots = breakdown()
    sections, synthesis = mv.validate_breakdown(
        parsed, snapshots=snapshots, urls=["https://news.example.com/oil"], stories=[]
    )
    assert [s["key"] for s in sections] == list(mv.APPROACHES)
    assert all(s["status"] == "ok" for s in sections)
    assert synthesis["confidence"] == "high"
    assert synthesis["conflicts"] == "Copper diverges"
    assert synthesis["watchpoints"]


def test_wrong_family_invented_urls_and_stale_sources_reduce_confidence():
    parsed, snapshots = breakdown()
    parsed["approaches"]["industry_monitor"]["evidence"][0]["ref"] = keys.SNAPSHOT_ECONOMIC_GROWTH
    parsed["approaches"]["news"]["evidence"][0]["ref"] += "/invented"
    snapshots[1]["stale"] = True
    sections, synthesis = mv.validate_breakdown(
        parsed, snapshots=snapshots, urls=["https://news.example.com/oil"], stories=[]
    )
    assert sections[0]["status"] == sections[3]["status"] == "unavailable"
    assert sections[0]["interpretation"] == ""
    assert sections[1]["confidence"] == synthesis["confidence"] == "low"
    assert "stale" in sections[1]["caveats"]


def test_missing_breakdown_is_explicit_and_never_fabricated():
    sections, synthesis = mv.validate_breakdown({}, snapshots=[], urls=[], stories=[])
    assert len(sections) == 4 and all(s["status"] == "unavailable" for s in sections)
    assert synthesis is None


def test_run_persists_breakdown_and_requests_all_four_approaches():
    parsed, snapshots = breakdown()
    parsed.update({"summary": "Conditional macro view", "rows": []})

    def call(**kwargs):
        assert "approaches" in kwargs["json_schema"]["required"]
        assert "synthesis" in kwargs["json_schema"]["required"]
        for key in mv.APPROACHES:
            assert key in kwargs["prompt"]
        return parsed, [("Oil", "https://news.example.com/oil")], None, {}

    result = mv.run_macro_view(
        budget=RunBudget(2), previous_view=None, searches=1, reserve_usd=0.1, snapshots=snapshots, call=call
    )
    assert result["status"] == "ok"
    assert len(result["approaches"]) == 4
    assert result["synthesis"]["outlook"] == parsed["synthesis"]["outlook"]


def test_declined_industry_summary_is_retried_on_next_refresh(monkeypatch):
    from datetime import UTC, datetime

    from tests.test_industry_monitor import _make_mem_db

    monkeypatch.setattr(
        im, "SECTORS", {"Housing": {"type": "leading", "companies": [("DHI", "D.R. Horton", "Homebuilder", "BMO")]}}
    )
    monkeypatch.setattr(im, "_load_pdf_bytes", lambda *args: (b"pdf", datetime(2026, 10, 20, tzinfo=UTC)))
    monkeypatch.setattr(im, "_extract_text_from_bytes", lambda _: "Q3 2026 Earnings Call October 20, 2026")
    conn = _make_mem_db()
    im._fetch_and_store(conn, summarize=lambda *args: None)
    assert conn.execute("SELECT summary_json FROM transcripts").fetchone()["summary_json"] is None
    im._fetch_and_store(conn, summarize=lambda *args: {"summary_headline": "Orders declining"})
    assert "Orders declining" in conn.execute("SELECT summary_json FROM transcripts").fetchone()["summary_json"]
    # Replacing a PDF for the same reporting period must not reuse its old
    # summary when the new summarization has to wait for a future budget.
    monkeypatch.setattr(
        im, "_extract_text_from_bytes", lambda _: "Q3 2026 Earnings Call October 20, 2026 Revised orders"
    )
    im._fetch_and_store(conn, summarize=lambda *args: None)
    assert conn.execute("SELECT summary_json FROM transcripts").fetchone()["summary_json"] is None
    conn.close()
