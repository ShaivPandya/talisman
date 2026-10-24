"""Cross-chat memory is relevant, editable, optional and identical to the reply's snapshot."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from api import memory_context as memory
from api import memory_db, memory_manager
from tests import test_agent_turn_terminal_state as agent_fixtures
from tests import test_postgres_pool_integration as pg_fixtures
from tests.test_agent_stream_retry import _run_turn
from tests.test_agent_streaming import _event_text_delta, _install_fake_anthropic

_final_message = agent_fixtures._final_message
agent_env = agent_fixtures.agent_env
temp_memory_db = agent_fixtures.temp_memory_db
migrated_database = pg_fixtures.migrated_database
pg_state = pg_fixtures.pg_state

MIGRATION = Path(__file__).resolve().parents[1] / "migrations/versions/20261024_tl215_conversation_memory.py"


def seed(sid, summary, *, rolling=False):
    session = memory_db.save_session([{"role": "user", "content": f"Original conversation {sid}"}], session_id=sid)
    if rolling:
        memory_db.update_rolling_summary(sid, summary)
    else:
        memory_db.update_summary(sid, summary, ["NVDA"] if sid == "old" else None)
    return session


def test_selects_old_relevant_summary_instead_of_recent_unrelated_ones(temp_memory_db):
    seed("old", "NVDA semiconductor demand is constrained by packaging")
    for index in range(35):
        seed(f"new-{index}", "Wheat harvest and aluminum smelting")
    assert "old" not in [row["session_id"] for row in memory_db.get_recent_summaries()]
    context = memory.select_memory_context({"session_id": "current"}, "Review NVDA semiconductor demand")
    assert [entry["session_id"] for entry in context["memories"]] == ["old"]
    assert "Wheat" not in context["prompt"]
    assert memory.select_memory_context({"session_id": "current"}, "Lithium reserves")["prompt"] == ""
    assert memory.select_memory_context({"session_id": "old"}, "NVDA")["prompt"] == ""


def test_short_followup_uses_branch_subject_and_screen_ticker(temp_memory_db):
    seed("old", "NVDA packaging constraints")
    context = memory.select_memory_context(
        {"session_id": "current"}, "Tell me more", history=[{"role": "user", "content": "NVDA outlook"}]
    )
    assert context["memories"][0]["session_id"] == "old"
    assert memory.select_memory_context({"session_id": "current"}, "Thoughts?", ticker="NVDA")["memories"]
    assert memory.select_memory_context({"session_id": "current"}, "Tell me more")["memories"] == []


def test_edits_and_deletes_survive_both_summary_writers_without_changing_history(temp_memory_db):
    seed("old", "NVDA prior conclusion")
    seed("rolling", "Cobalt supply constraints", rolling=True)
    original = memory_db.get_session("old")["transcript"]
    assert memory.edit_memory("old", "Lithium revised conclusion")
    memory_db.update_summary("old", "NVDA regenerated", ["NVDA"], ["packaging"])
    memory_db.update_rolling_summary("old", "NVDA regenerated rolling")
    assert memory.list_memories(query="NVDA") == []  # Old tags cannot override an edit.
    assert memory.list_memories(query="lithium")[0]["summary"] == "Lithium revised conclusion"
    assert memory.list_memories(query="cobalt")[0]["session_id"] == "rolling"
    assert memory.delete_memory("old")
    assert memory.delete_memory("rolling")
    memory_db.update_summary("old", "NVDA regenerated again")
    memory_db.update_rolling_summary("rolling", "Cobalt regenerated")
    assert memory.list_memories() == []
    assert memory_db.get_session("old")["transcript"] == original


def test_off_skips_selection_and_preserves_same_chat_history_and_research(temp_memory_db, monkeypatch):
    seed("current", "NVDA current conversation")
    memory_db.update_rolling_summary("current", "Current chat rolling history")
    assert memory.set_memory_enabled("current", False)
    session = memory_db.get_or_create_session("current")
    monkeypatch.setattr(memory, "list_memories", lambda **kw: pytest.fail("Memory off must not query other sessions"))
    assert memory.select_memory_context(session, "NVDA") == {"enabled": False, "memories": [], "prompt": ""}
    seen = []
    monkeypatch.setattr("api.retrieval.search", lambda **kw: seen.append(kw) or [])
    conversation, _ = memory_manager.build_conversation_context("current", "Question", session=session)
    assert "Current chat rolling history" in json.dumps(conversation)
    assert "Original conversation current" in json.dumps(conversation)
    assert seen[0]["doc_types"] == ["thesis", "news_digest"]


def test_memory_api_validates_and_persists_edits_settings_and_deletion(temp_memory_db, auth_client):
    seed("old", "NVDA packaging")
    assert auth_client.get("/api/memory/sessions/old/memory").json() == {"enabled": True}
    assert auth_client.patch("/api/memory/sessions/old/memory", json={"enabled": False}).json() == {"enabled": False}
    assert not memory_db.get_or_create_session("old")["memory_enabled"]
    assert auth_client.patch("/api/memory/entries/old", json={"summary": "  "}).status_code == 422
    assert auth_client.patch("/api/memory/entries/old", json={"summary": "x" * 12001}).status_code == 422
    assert auth_client.patch("/api/memory/entries/old", json={"summary": "Revised cobalt view"}).status_code == 200
    assert auth_client.get("/api/memory/entries?q=cobalt").json()["entries"][0]["summary"] == "Revised cobalt view"
    assert auth_client.delete("/api/memory/entries/old").status_code == 200
    assert auth_client.get("/api/memory/entries").json() == {"entries": [], "has_more": False}
    assert memory_db.get_session("old")["transcript"]
    assert auth_client.patch("/api/memory/entries/old", json={"summary": "Cannot resurrect"}).status_code == 404
    assert auth_client.get("/api/memory/sessions/missing/memory").status_code == 404
    assert auth_client.patch("/api/memory/sessions/missing/memory", json={"enabled": False}).status_code == 404
    assert auth_client.get("/api/memory/entries?limit=0").status_code == 422


@pytest.mark.parametrize("enabled", [True, False])
def test_real_stream_prompt_matches_snapshot_and_persisted_message(agent_env, monkeypatch, enabled):
    seed("old", "NVDA semiconductor packaging demand")
    seed("unrelated", "Wheat production")
    fake = _install_fake_anthropic(monkeypatch, [([_event_text_delta("Answer")], _final_message("Answer"))])
    turn = _run_turn(monkeypatch, "Review NVDA semiconductor packaging demand", memory_enabled=enabled)
    assert turn.error is None
    snapshot = next(payload for event, payload in turn.parsed if event == "memory_context")
    snapshot.pop("session_id")
    system = fake.messages.kwargs_history[0]["system"]
    system_text = system if isinstance(system, str) else "".join(block["text"] for block in system)
    if enabled:
        assert snapshot["prompt"] in system_text
        assert snapshot["memories"][0]["summary"] == "NVDA semiconductor packaging demand"
    else:
        assert snapshot["prompt"] == "" and snapshot["memories"] == []
        assert "Relevant Conversation Memory" not in system_text
    assert "Wheat production" not in system_text
    assert turn.saved["memory_context"] == snapshot
    assert next(payload for event, payload in turn.parsed if event == "done")["memory_context"] == snapshot
    assert bool(memory_db.get_or_create_session(turn.session_id)["memory_enabled"]) is enabled


def test_migration_preserves_existing_summaries_and_roundtrips_on_sqlite(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        conn.exec_driver_sql("CREATE TABLE conversation_sessions (session_id TEXT PRIMARY KEY, summary TEXT)")
        conn.exec_driver_sql("INSERT INTO conversation_sessions VALUES ('old', 'Existing summary')")
        module = runpy.run_path(str(MIGRATION))
        module["upgrade"]()
        row = conn.exec_driver_sql(
            "SELECT summary, memory_enabled, memory_excluded, memory_summary FROM conversation_sessions"
        ).one()
        assert tuple(row) == ("Existing summary", 1, 0, None)
        module["downgrade"]()
        assert conn.exec_driver_sql("SELECT summary FROM conversation_sessions").scalar() == "Existing summary"
    engine.dispose()


def test_postgres_ranks_entire_corpus_and_honors_live_edits_and_exclusions(pg_state):
    seed("old", "NVDA semiconductor packaging")
    with memory_db._get_conn() as conn:
        for index in range(1200):
            conn.execute(
                "INSERT INTO conversation_sessions (session_id, started_at, summary) VALUES (?, ?, ?)",
                (f"new-{index}", "2026-10-24", "Wheat harvest"),
            )
        conn.commit()
    assert [row["session_id"] for row in memory.list_memories(query="NVDA semiconductor")] == ["old"]
    memory.edit_memory("old", "Cobalt logistics")
    assert memory.list_memories(query="NVDA") == []
    assert memory.list_memories(query="cobalt")[0]["summary"] == "Cobalt logistics"
    memory.delete_memory("old")
    assert memory.list_memories(query="cobalt") == []


@pytest.mark.parametrize("ticker", ["ON", "IT", "F"])
def test_short_tickers_are_not_removed_as_stop_words(temp_memory_db, ticker):
    seed("ticker", f"{ticker} earnings outlook")
    assert memory.select_memory_context({"session_id": "current"}, "Thoughts?", ticker=ticker)["memories"]


@pytest.mark.parametrize("enabled", [True, False])
def test_durable_worker_replays_and_persists_the_same_memory_snapshot(agent_env, monkeypatch, enabled):
    from api import agent_chat_worker
    from api.agent_models import AgentChatJobRequest
    from ontology.policy import admin_actor

    seed("old", "NVDA semiconductor packaging demand")
    session = memory_db.get_or_create_session(None)
    _install_fake_anthropic(monkeypatch, [([_event_text_delta("Answer")], _final_message("Answer"))])
    events = []
    monkeypatch.setattr(
        agent_chat_worker, "append_job_event", lambda jid, kind, payload: events.append((kind, payload))
    )
    monkeypatch.setattr(agent_chat_worker, "get_job_status", lambda jid: "running")
    monkeypatch.setattr("ontology.policy.actor_from_dict", lambda data: admin_actor())
    result = agent_chat_worker._run_agent_chat_turn_job(
        AgentChatJobRequest(
            session_id=session["session_id"],
            client_turn_id="worker-turn",
            message="Review NVDA semiconductor packaging demand",
            memory_enabled=enabled,
        ),
        job_id="memory-worker",
    )
    streamed = next(payload for kind, payload in events if kind == "memory_context")
    streamed.pop("session_id")
    assert streamed["enabled"] is enabled
    assert bool(streamed["memories"]) is enabled
    assert result["memory_context"] == streamed
    assistant = memory_db.get_session(session["session_id"])["transcript"][-1]
    assert assistant["memory_context"] == streamed


def test_knowledge_base_tool_cannot_bypass_memory_controls(monkeypatch):
    from api import agent_tools

    calls = []
    monkeypatch.setattr("api.retrieval.search", lambda **kw: calls.append(kw) or [])
    # This internal dispatch isolates the tool from external dependencies; public execution adds governance.
    agent_tools._dispatch("search_knowledge_base", {"query": "NVDA"})
    assert "conversation_summary" not in calls[0]["doc_types"]
    agent_tools._dispatch("search_knowledge_base", {"query": "NVDA", "doc_types": "conversation_summary"})
    assert len(calls) == 1
