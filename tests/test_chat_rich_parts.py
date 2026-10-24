"""Inline charts, proposal cards and follow-up suggestions in chat messages (TL-226)."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import pytest

from api import chat_rich_parts as rich
from api import memory_db
from api.agent_models import AgentChatRequest
from api.routers.agent import _sse, _TurnTranscriptGuard


@pytest.fixture
def store(tmp_path, monkeypatch):
    if memory_db._conn is not None:
        memory_db._conn.close()
    memory_db._conn = None
    monkeypatch.setenv("STATE_DB_BACKEND", "sqlite")
    monkeypatch.setattr(memory_db, "_DB_PATH", tmp_path / "memory.db")
    monkeypatch.setattr("api.memory_manager._ensure_session_title", lambda *args: None)
    yield memory_db
    if memory_db._conn is not None:
        memory_db._conn.close()
    memory_db._conn = None


def _begin(store, turn="turn"):
    sid = store.get_or_create_session(None)["session_id"]
    user = {"id": f"{sid}-user", "role": "user", "content": "How is NVDA trading?", "client_turn_id": turn}
    answer = {"id": f"{sid}-answer", "role": "assistant", "content": "", "client_turn_id": turn}
    store.begin_turn(sid, user, answer)
    return sid, user, answer


def _price_result(rows: int = 520) -> dict:
    dates = pd.bdate_range("2024-01-01", periods=rows)
    return {
        "ticker": "NVDA",
        "name": "NVIDIA Corporation",
        "price_data": [
            {
                "Date": f"{day.date().isoformat()}T00:00:00",
                "Close": 100.0 + index,
                "100D SMA": None if index < 99 else 90.0 + index,
                "200D SMA": None,
                "40W SMA": 1.0,
            }
            for index, day in enumerate(dates)
        ],
        "summary": {},
    }


def test_price_chart_samples_rows_and_keeps_first_and_last():
    part = rich.build_chart_part("run_chart", {"ticker": "nvda", "lookback": "2y"}, _price_result())

    assert part["kind"] == "line"
    assert part["title"] == "NVIDIA Corporation (NVDA)"
    assert part["subtitle"] == "2Y daily close with moving averages"
    assert [s["key"] for s in part["series"]] == ["Close", "100D SMA"]  # 200D SMA never has a value
    assert len(part["rows"]) == rich.MAX_CHART_ROWS
    assert part["sampled_from"] == 520
    assert part["rows"][0]["date"] == "2024-01-01"
    assert part["rows"][-1]["Close"] == 619.0
    assert part["as_of"] == part["rows"][-1]["date"]
    assert len(json.dumps(part)) < 25_000


def test_small_result_is_not_sampled():
    part = rich.build_chart_part("run_chart", {}, _price_result(rows=30))

    assert len(part["rows"]) == 30
    assert "sampled_from" not in part


@pytest.mark.parametrize(
    "result", [{"error": "bad ticker"}, {"price_data": []}, {"ticker": "X", "price_data": [{}]}, "text"]
)
def test_chart_needs_data_to_plot(result):
    assert rich.build_chart_part("run_chart", {"ticker": "X"}, result) is None


def test_unknown_tool_has_no_chart():
    assert rich.build_chart_part("get_thesis", {}, _price_result()) is None


def test_ratio_chart_reports_change_and_average():
    result = {
        "ratio_label": "SI=F/GC=F",
        "ratio_data": [
            {"Date": f"2026-01-0{day}", "Price A": 1, "Price B": 2, "Ratio": 0.5 + day / 100} for day in range(1, 6)
        ],
        "stats": {"change_pct": 0.08, "historical_avg": 0.53},
    }

    part = rich.build_chart_part("run_ratio_chart", {}, result)

    assert part["title"] == "SI=F/GC=F ratio"
    assert part["subtitle"] == "+8.0% over the window · average 0.53"
    assert part["series"] == [{"key": "Ratio", "name": "SI=F/GC=F"}]
    assert part["y_format"] == "ratio"


def _curve_points(base: float) -> list[dict]:
    return [
        {"tenor": tenor, "current": base + index / 10, "historical": base - 0.2, "historical_1y": None}
        for index, tenor in enumerate(["2Y", "10Y", "30Y"])
    ]


def test_yield_curve_of_one_country_compares_with_earlier_curves():
    result = {
        "lookback_days": 90,
        "tenor_order": [{"tenor": "2Y"}, {"tenor": "10Y"}, {"tenor": "30Y"}],
        "countries": [
            {"code": "US", "name": "United States", "as_of_date": "2026-10-23", "points": _curve_points(4.0)}
        ],
    }

    part = rich.build_chart_part("get_yield_curve", {}, result)

    assert part["kind"] == "curve"
    assert part["title"] == "United States yield curve"
    assert part["series"] == [{"key": "current", "name": "Current"}, {"key": "historical", "name": "90d ago"}]
    assert [row["label"] for row in part["rows"]] == ["2Y", "10Y", "30Y"]
    assert part["as_of"] == "2026-10-23"


def test_yield_curve_of_several_countries_plots_current_curves_together():
    result = {
        "tenor_order": [{"tenor": "2Y"}, {"tenor": "10Y"}, {"tenor": "30Y"}],
        "countries": [
            {"code": "US", "name": "United States", "as_of_date": "2026-10-23", "points": _curve_points(4.0)},
            {"code": "JP", "name": "Japan", "as_of_date": "2026-10-22", "points": _curve_points(1.0)},
        ],
    }

    part = rich.build_chart_part("get_yield_curve", {}, result)

    assert part["title"] == "Government yield curves"
    assert [s["key"] for s in part["series"]] == ["US", "JP"]
    assert part["rows"][1] == {"label": "10Y", "US": 4.1, "JP": 1.1}
    assert part["as_of"] == "2026-10-23"


def test_commodity_curve_names_the_shape_and_unit():
    result = {
        "commodity_name": "WTI Crude",
        "unit": "$/bbl",
        "lookback_days": 30,
        "analysis": {"shape": "Contango"},
        "points": [
            {"label": "Dec 26", "current": 70.1, "historical": 68.0, "current_date": "2026-10-23"},
            {"label": "Jan 27", "current": 70.9, "historical": None, "current_date": "2026-10-23"},
        ],
    }

    part = rich.build_chart_part("get_commodities_curve", {}, result)

    assert part["title"] == "WTI Crude forward curve"
    assert part["subtitle"] == "Contango · $/bbl"
    assert part["unit"] == "$/bbl"
    assert part["rows"][1]["historical"] is None
    assert part["as_of"] == "2026-10-23"


def test_price_volume_signals_chart_lists_flagged_markets():
    result = {
        "latest_df": [
            {
                "Market": "S&P 500 (^GSPC)",
                "Date": "2026-10-23",
                "RetPct": -1.25,
                "HiVol_Churn": True,
                "DownsideRecordVol": False,
            },
            {"Market": "Nasdaq (^IXIC)", "Date": "2026-10-23", "RetPct": 0.4, "HiVol_Churn": False},
        ]
    }

    part = rich.build_chart_part("get_price_volume_signals", {}, result)

    assert part["kind"] == "bars"
    assert part["subtitle"] == "Signals: S&P 500 (^GSPC): high-volume churn"
    assert part["rows"] == [{"label": "S&P 500 (^GSPC)", "RetPct": -1.25}, {"label": "Nasdaq (^IXIC)", "RetPct": 0.4}]


def test_stashed_charts_are_kept_by_event_id_and_bounded():
    rich.stash_chart("first", {"title": "one"})
    assert rich.stashed_chart("first") == {"title": "one"}
    assert rich.stashed_chart("missing") is None
    for index in range(rich._MAX_PENDING_CHARTS + 1):
        rich.stash_chart(f"event-{index}", {"title": str(index)})
    assert rich.stashed_chart("first") is None
    assert rich.stashed_chart("event-0") is None
    assert rich.stashed_chart(f"event-{rich._MAX_PENDING_CHARTS}") is not None


def test_proposal_part_names_the_pending_approval():
    result = json.dumps(
        {
            "status": "pending_approval_created",
            "approval_id": 42,
            "entity_type": "thesis",
            "ticker": "NVDA",
            "_meta": {},
        }
    )

    assert rich.build_proposal_part("propose_thesis_status_change", result) == {
        "tool": "propose_thesis_status_change",
        "approval_id": "42",
        "entity_type": "thesis",
        "ticker": "NVDA",
    }
    assert rich.build_proposal_part("propose_catalyst", json.dumps({"error": "invalid"})) is None
    assert rich.build_proposal_part("propose_catalyst", "not json") is None
    assert rich.build_proposal_part("propose_catalyst", json.dumps({"status": "pending_approval_created"})) is None


def test_parse_suggestions_trims_dedupes_and_caps():
    text = 'Sure:\n{"suggestions": ["  What is the downside case? ", "what is the downside case?", "Size it?", "", 7, "A", "B"]}'

    assert rich.parse_suggestions(text, "Size it?") == ["What is the downside case?", "7", "A"]
    assert rich.parse_suggestions("no json here") == []
    assert rich.parse_suggestions('{"suggestions": "nope"}') == []
    assert rich.parse_suggestions("x" * 5) == []
    assert rich.parse_suggestions(json.dumps({"suggestions": ["q" * 200]})) == []


def test_generate_suggestions_skips_short_answers_and_calls_the_low_tier_model(monkeypatch):
    calls = []

    def fake_call(**kwargs):
        calls.append(kwargs)
        return '{"suggestions": ["How does NVDA compare with AMD?", "What would change the thesis?"]}', [], None

    monkeypatch.setattr("llm_utils.call_llm_text", fake_call)
    monkeypatch.setattr("llm_utils.has_llm_api_key", lambda: True)

    assert rich.generate_suggestions("How is NVDA?", "ok") == []
    assert calls == []
    answer = "NVDA is above its 200-day average with expanding volume. " * 3
    assert rich.generate_suggestions("How is NVDA?", answer) == [
        "How does NVDA compare with AMD?",
        "What would change the thesis?",
    ]
    assert calls[0]["model"] == "low"
    assert "How is NVDA?" in calls[0]["prompt"]


def test_run_chart_tool_returns_data_to_the_model_and_stashes_a_chart(monkeypatch):
    import portfolio.technical_analysis.technical_analysis as technical
    from api import cache
    from api.agent_tools import execute_tool
    from api.routers import chart

    idx = pd.bdate_range("2024-01-01", periods=300)
    close = pd.Series([100.0 + i for i in range(300)], index=idx, name="Close")
    monkeypatch.setattr(chart, "short_cache", cache.ApiCache(maxsize=8, ttl=300))
    monkeypatch.setattr(
        technical,
        "get_data",
        lambda ticker, lookback="2Y": {
            "ticker": ticker,
            "name": "Fake Co",
            "price_data": technical._moving_averages(close),
            "roc_data": technical._rate_of_change(close),
            "summary": {"last": 399.0},
            "timestamp": datetime(2026, 1, 2),
        },
    )

    result = json.loads(execute_tool("run_chart", {"ticker": "fake", "lookback": "2Y"}))

    # The route returns a JSON response object; the model must get its data, not the object's repr.
    assert "ORJSONResponse" not in json.dumps(result)
    assert result["ticker"] == "FAKE"
    event_id = result["_meta"]["provenance_event_id"]
    chart_part = rich.stashed_chart(event_id)
    assert chart_part["title"] == "Fake Co (FAKE)"
    assert chart_part["sampled_from"] == 300
    assert chart_part["rows"][-1]["Close"] == 399.0


def _guard(store):
    sid, user, answer = _begin(store)
    req = AgentChatRequest(
        session_id=sid,
        client_turn_id="turn",
        message=user["content"],
        finalize_synchronously=True,
        user_message_id=user["id"],
        assistant_message_id=answer["id"],
    )
    guard = _TurnTranscriptGuard(req)
    guard.session_id = sid
    return guard, sid, user, answer


def test_guard_attaches_the_chart_to_the_frame_and_saves_it_apart_from_the_tool_call(store):
    guard, sid, user, answer = _guard(store)
    rich.stash_chart("pv:chart-1", {"tool": "run_chart", "kind": "line", "title": "NVDA", "rows": [], "series": []})
    compacted = json.dumps({"summary": {"last": 1}, "_meta": {"provenance_event_id": "pv:chart-1"}})

    frame = guard.observe(
        _sse("tool_result", {"id": "call-1", "name": "run_chart", "status": "ok", "arguments": {}, "result": compacted})
    )

    sent = json.loads(frame.split("\ndata: ", 1)[1])
    assert sent["chart"]["id"] == "call-1"
    assert sent["chart"]["title"] == "NVDA"
    assert "chart" not in guard.tools["call-1"]
    guard.observe(_sse("delta", {"text": "NVDA is rising."}))
    guard.finalize(sid, user, {**answer, "content": "NVDA is rising."})
    done = json.loads(guard.observe(_sse("done", {})).split("\ndata: ", 1)[1])
    assert "charts" not in done

    message = store.get_session(sid)["transcript"][-1]
    assert [c["title"] for c in message["charts"]] == ["NVDA"]
    assert [p["type"] for p in message["content_parts"]].count("chart") == 1
    assert "chart" not in message["tool_calls"][0]


def test_guard_skips_a_chart_for_a_failed_tool_or_a_missing_snapshot(store):
    guard, *_ = _guard(store)
    rich.stash_chart("pv:chart-2", {"tool": "run_chart", "title": "T"})
    result = json.dumps({"_meta": {"provenance_event_id": "pv:chart-2"}})
    failed = guard.observe(_sse("tool_result", {"id": "a", "name": "run_chart", "status": "error", "result": result}))
    unknown = guard.observe(
        _sse(
            "tool_result",
            {
                "id": "b",
                "name": "run_chart",
                "status": "ok",
                "result": json.dumps({"_meta": {"provenance_event_id": "gone"}}),
            },
        )
    )

    assert "chart" not in json.loads(failed.split("\ndata: ", 1)[1])
    assert "chart" not in json.loads(unknown.split("\ndata: ", 1)[1])
    assert guard.charts == {}


def test_guard_caps_charts_per_message(store):
    guard, *_ = _guard(store)
    for index in range(rich.MAX_CHARTS_PER_MESSAGE + 2):
        rich.stash_chart(f"pv:cap-{index}", {"tool": "run_chart", "title": str(index)})
        guard.observe(
            _sse(
                "tool_result",
                {
                    "id": f"call-{index}",
                    "name": "run_chart",
                    "status": "ok",
                    "result": json.dumps({"_meta": {"provenance_event_id": f"pv:cap-{index}"}}),
                },
            )
        )

    assert len(guard.charts) == rich.MAX_CHARTS_PER_MESSAGE


def test_guard_turns_a_created_approval_into_a_proposal_part_that_survives_reload(store):
    guard, sid, user, answer = _guard(store)
    result = json.dumps(
        {"status": "pending_approval_created", "approval_id": "7", "entity_type": "thesis", "ticker": "NVDA"}
    )

    frame = guard.observe(
        _sse("tool_result", {"id": "call-p", "name": "propose_thesis_status_change", "status": "ok", "result": result})
    )

    assert json.loads(frame.split("\ndata: ", 1)[1])["proposal"]["approval_id"] == "7"
    guard.observe(_sse("delta", {"text": "I proposed it."}))
    guard.finalize(sid, user, {**answer, "content": "I proposed it."})
    done = json.loads(guard.observe(_sse("done", {})).split("\ndata: ", 1)[1])
    assert done["proposals"][0]["approval_id"] == "7"
    message = store.get_session(sid)["transcript"][-1]
    assert message["proposals"] == [
        {
            "id": "call-p",
            "tool": "propose_thesis_status_change",
            "approval_id": "7",
            "entity_type": "thesis",
            "ticker": "NVDA",
        }
    ]


def test_partial_save_keeps_charts_when_the_turn_is_stopped(store):
    guard, sid, *_ = _guard(store)
    rich.stash_chart("pv:stop", {"tool": "run_chart", "title": "Kept"})
    guard.observe(
        _sse(
            "tool_result",
            {
                "id": "call-s",
                "name": "run_chart",
                "status": "ok",
                "result": json.dumps({"_meta": {"provenance_event_id": "pv:stop"}}),
            },
        )
    )
    guard.observe(_sse("delta", {"text": "Partial"}))
    guard.settle()

    message = store.get_session(sid)["transcript"][-1]
    assert message["status"] == "stopped"
    assert [c["title"] for c in message["charts"]] == ["Kept"]


def test_suggestions_are_written_after_the_answer_and_read_back(store, monkeypatch):
    from api.agent_turn_followup import AgentTurnFollowupRequest, run_agent_turn_followup

    monkeypatch.setenv("AGENT_FOLLOWUP_SUGGESTIONS", "true")
    sid, user, answer = _begin(store)
    store.update_assistant_message(
        sid, "turn", {"content": "NVDA is above its 200-day average. " * 4, "status": "complete"}
    )
    monkeypatch.setattr(
        "api.chat_rich_parts.generate_suggestions", lambda question, text: ["What could go wrong?", "Compare with AMD?"]
    )

    result = run_agent_turn_followup(
        AgentTurnFollowupRequest(session_id=sid, client_turn_id="turn", suggest_followups=True)
    )

    assert result["steps"]["suggestions"] == "written"
    assert store.message_suggestions(sid, answer["id"]) == [
        {"text": "What could go wrong?"},
        {"text": "Compare with AMD?"},
    ]
    message = store.get_session(sid)["transcript"][-1]
    assert message["content"].startswith("NVDA is above")
    # A second run leaves the saved suggestions alone.
    again = run_agent_turn_followup(
        AgentTurnFollowupRequest(session_id=sid, client_turn_id="turn", suggest_followups=True)
    )
    assert again["steps"]["suggestions"] == "skipped"


def test_suggestions_are_skipped_for_unfinished_turns_and_failures_do_not_break_the_followup(store, monkeypatch):
    from api import agent_turn_followup as followup

    monkeypatch.setenv("AGENT_FOLLOWUP_SUGGESTIONS", "true")
    sid, _user, answer = _begin(store)
    monkeypatch.setattr(followup, "SUGGESTIONS_WAIT_S", 0.0)
    called = []
    monkeypatch.setattr("api.chat_rich_parts.generate_suggestions", lambda q, a: called.append(1) or ["x?"])

    # The answer is still streaming.
    assert followup._write_suggestions(sid, "turn") == "skipped"
    assert called == []

    store.update_assistant_message(sid, "turn", {"content": "A long enough answer. " * 6, "status": "complete"})
    monkeypatch.setattr(
        "api.chat_rich_parts.generate_suggestions", lambda q, a: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    result = followup.run_agent_turn_followup(
        followup.AgentTurnFollowupRequest(session_id=sid, client_turn_id="turn", suggest_followups=True)
    )
    assert result["steps"]["suggestions"] == "failed"
    assert store.message_suggestions(sid, answer["id"]) == []


@pytest.mark.parametrize("value", ["false", "0", "off", "No"])
def test_suggestions_can_be_switched_off(store, monkeypatch, value):
    from api import agent_turn_followup as followup

    sid, _user, answer = _begin(store)
    store.update_assistant_message(sid, "turn", {"content": "A long enough answer. " * 6, "status": "complete"})
    monkeypatch.setenv("AGENT_FOLLOWUP_SUGGESTIONS", value)
    monkeypatch.setattr("api.chat_rich_parts.generate_suggestions", lambda q, a: pytest.fail("no model call when off"))

    assert followup._write_suggestions(sid, "turn") == "disabled"
    assert store.message_suggestions(sid, answer["id"]) == []


def test_suggestions_are_on_unless_switched_off(monkeypatch):
    monkeypatch.delenv("AGENT_FOLLOWUP_SUGGESTIONS", raising=False)
    assert rich.suggestions_enabled() is True


def test_suggestions_endpoint_returns_the_questions_or_none_yet(store, auth_client):
    sid, _user, answer = _begin(store)
    url = f"/api/memory/sessions/{sid}/messages/{answer['id']}/suggestions"

    assert auth_client.get(url).json() == {"suggestions": []}
    store.update_assistant_message(sid, "turn", {"suggestions": [{"text": "What next?"}]})
    assert auth_client.get(url).json() == {"suggestions": ["What next?"]}
    assert auth_client.get(f"/api/memory/sessions/{sid}/messages/unknown/suggestions").json() == {"suggestions": []}
