"""Message identity, migration safety, structured history and narrow writes (TL-220)."""

from __future__ import annotations

import json
import os
import runpy
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from api import memory_db
from api.agent_models import AgentChatRequest
from api.conversation_messages import legacy_messages, sources_from
from api.routers.agent import _sse, _TurnTranscriptGuard

MIGRATION = Path(__file__).resolve().parents[1] / "migrations/versions/20261023_tl220_conversation_messages.py"


@pytest.fixture
def store(tmp_path, monkeypatch):
    if memory_db._conn is not None:
        memory_db._conn.close()
    memory_db._conn = None
    monkeypatch.setenv("STATE_DB_BACKEND", "sqlite")
    monkeypatch.setattr(memory_db, "_DB_PATH", tmp_path / "memory.db")
    yield memory_db
    if memory_db._conn is not None:
        memory_db._conn.close()
    memory_db._conn = None


def begin(store, sid=None, turn="turn"):
    sid = store.get_or_create_session(sid)["session_id"]
    user = {"id": f"{sid}-{turn}-user", "role": "user", "content": "question", "client_turn_id": turn}
    answer = {"id": f"{sid}-{turn}-answer", "role": "assistant", "content": "", "client_turn_id": turn}
    store.begin_turn(sid, user, answer)
    return sid, user, answer


def rows(store, sid):
    with store._get_conn() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM conversation_messages WHERE session_id = ? ORDER BY position",
                (sid,),
            )
        ]


def test_partial_and_final_writes_leave_every_other_message_untouched(store):
    sid, _, _ = begin(store, turn="first")
    store.update_assistant_message(sid, "first", {"content": "earlier", "status": "complete"})
    _, user, answer = begin(store, sid, "second")
    earlier = rows(store, sid)[:-1]
    statements = []
    store._conn.set_trace_callback(statements.append)
    assert store.update_assistant_message(sid, "second", {"content": "partial"}, only_streaming=True)
    store._conn.set_trace_callback(None)
    assert rows(store, sid)[:-1] == earlier
    writes = [sql for sql in statements if sql.startswith("UPDATE")]
    assert len(writes) == 1 and "UPDATE conversation_messages" in writes[0]
    assert "server_messages" not in " ".join(statements) and "transcript" not in " ".join(statements)
    assert all("client_turn_id" in sql for sql in statements if sql.lstrip().startswith("SELECT"))
    store.complete_turn_messages(sid, "second", user, {**answer, "content": "final"})
    assert rows(store, sid)[:-1] == earlier
    restored = store.get_session(sid)["transcript"]
    assert restored[-1]["id"] == answer["id"]
    assert restored[-1]["parent_id"] == user["id"]
    assert restored[-1]["status"] == "complete"
    store._conn.close()
    store._conn = None
    assert store.get_session(sid)["transcript"] == restored


def test_structured_content_and_unknown_metadata_survive_text_updates(store):
    sid, user, answer = begin(store)
    tool = {"id": "tool", "name": "search", "arguments": {"q": "liquidity"}, "result": {"value": 42}, "status": "ok"}
    source = {"url": "https://example.com/report", "title": "Report", "as_of": "2026-10-23"}
    attachment = {"id": "file", "mime_type": "application/pdf"}
    assert store.update_assistant_message(
        sid,
        "turn",
        {
            "tool_calls": [tool],
            "sources": [source],
            "attachments": [attachment],
            "routing_context": {"intent": "macro"},
        },
    )
    store.complete_turn_messages(sid, "turn", user, {**answer, "content": "answer"})
    message = store.get_session(sid)["transcript"][-1]
    assert message["tool_calls"] == [tool] and message["toolCalls"] == [tool]
    assert message["sources"] == [source] and message["attachments"] == [attachment]
    assert message["routing_context"] == {"intent": "macro"}
    assert {part["type"] for part in message["content_parts"]} == {"text", "tool_call", "source", "attachment"}


def test_content_parts_can_be_updated_without_legacy_text_fields(store):
    sid, _, _ = begin(store)
    parts = [{"type": "text", "text": "rich answer"}, {"type": "chart", "data": {"values": [1, 2]}}]
    store.update_assistant_message(sid, "turn", {"content_parts": parts})
    message = store.get_session(sid)["transcript"][-1]
    assert message["content_parts"] == parts and message["content"] == "rich answer"


def test_legacy_snapshot_save_updates_only_changed_messages_and_preserves_ids(store):
    messages = [{"role": "user", "content": "old question"}, {"role": "assistant", "content": "old answer"}]
    sid = store.save_session(messages)["session_id"]
    before = rows(store, sid)
    store.save_session([*messages, {"role": "user", "content": "new question"}], sid)
    assert rows(store, sid)[:2] == before
    store.save_session([messages[0], {"role": "assistant", "content": "changed answer"}], sid)
    after = rows(store, sid)
    assert after[0] == before[0] and after[1]["id"] == before[1]["id"]
    assert store.get_session(sid)["transcript"][1]["content"] == "changed answer"


def test_completing_a_legacy_orphan_user_does_not_duplicate_it(store):
    sid = store.get_or_create_session()["session_id"]
    user = {"role": "user", "content": "question", "client_turn_id": "orphan"}
    store.append_messages(sid, [user])
    assert (
        store.complete_turn_messages(
            sid, "orphan", user, {"role": "assistant", "content": "answer", "client_turn_id": "orphan"}
        )
        == 2
    )
    assert [message["role"] for message in store.get_session(sid)["transcript"]] == ["user", "assistant"]


def test_generated_message_ids_do_not_disable_active_job_deduplication():
    from api.agent_models import AgentChatJobRequest
    from api.routers.agent import _agent_chat_job_cache_key

    first = AgentChatJobRequest(session_id="session", message="same request")
    second = AgentChatJobRequest(session_id="session", message="same request")
    assert first.user_message_id != second.user_message_id
    assert _agent_chat_job_cache_key(first) == _agent_chat_job_cache_key(second)


@pytest.mark.parametrize("terminal", ["complete", "stopped", "failed"])
def test_terminal_state_rejects_late_partial_and_final_writes(store, terminal):
    sid, user, answer = begin(store)
    store.update_assistant_message(sid, "turn", {"content": "kept", "status": terminal})
    before = rows(store, sid)
    assert not store.update_assistant_message(
        sid, "turn", {"content": "late", "is_streaming": True}, only_streaming=True
    )
    store.complete_turn_messages(sid, "turn", user, {**answer, "content": "late final"})
    assert rows(store, sid) == before


def test_idempotency_and_retry_keep_stable_ids_and_parent_links(store):
    sid, user, answer = begin(store)
    assert store.begin_turn(sid, user, answer) == 2
    assert store.begin_job_turn(sid, "turn", "old-job")
    store.fail_turn(sid, "turn", status="failed", content="partial")
    assert store.begin_job_turn(sid, "turn", "new-job")
    assert not store.fail_turn(sid, "turn", job_id="old-job", status="failed")
    message = store.get_session(sid)["transcript"][-1]
    assert message["id"] == answer["id"] and message["parent_id"] == user["id"]
    assert message["status"] == "streaming" and message["content"] == ""


def test_parent_can_reference_earlier_message_but_never_another_session(store):
    sid, user, _ = begin(store)
    _, _, sibling = begin(store, sid, "next")
    store.append_messages(sid, [{"role": "assistant", "content": "another branch", "parent_id": user["id"]}])
    message = store.get_session(sid)["transcript"][-1]
    assert message["parent_id"] == user["id"] and message["id"] != sibling["id"]
    other = store.get_or_create_session()["session_id"]
    with pytest.raises(sqlite3.IntegrityError):
        store.append_messages(other, [{"role": "user", "content": "invalid", "parent_id": user["id"]}])
    assert store.get_session(other)["transcript"] == []
    assert store.delete_session(sid)
    assert rows(store, sid) == []


@pytest.mark.parametrize("server_only", [False, True])
def test_alembic_backfill_and_downgrade_preserve_legacy_content(server_only):
    migration = runpy.run_path(str(MIGRATION))
    engine = sa.create_engine("sqlite://")
    messages = [
        {"id": "user-id", "role": "user", "content": "Old question", "timestamp": 1000},
        {
            "role": "assistant",
            "content": "Old answer",
            "client_turn_id": "old-turn",
            "status": "failed",
            "toolCalls": [{"id": "tool", "name": "search", "status": "ok"}],
            "sources": [{"url": "https://example.com"}],
            "attachments": [{"id": "attachment"}],
            "routing_context": {"x": 1},
        },
        {"role": "assistant", "content": "Interrupted partial", "is_streaming": True},
    ]
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        conn.execute(
            sa.text(
                "CREATE TABLE conversation_sessions (session_id TEXT PRIMARY KEY, message_count INTEGER, transcript TEXT, server_messages TEXT)"
            )
        )
        conn.execute(
            sa.text("INSERT INTO conversation_sessions VALUES ('legacy', 3, :transcript, :server)"),
            {
                "transcript": "[]" if server_only else json.dumps(messages),
                "server": json.dumps(messages) if server_only else "[]",
            },
        )
        migration["upgrade"]()
        records = [
            dict(row)
            for row in conn.execute(sa.text("SELECT * FROM conversation_messages ORDER BY position")).mappings()
        ]
        assert len(records) == 3 and records[0]["id"] == "user-id"
        assert records[1]["parent_id"] == "user-id"
        assert records[1]["status"] == "failed" and records[2]["status"] == "stopped"
        assert not {"transcript", "server_messages"} & {
            c["name"] for c in sa.inspect(conn).get_columns("conversation_sessions")
        }
        migration["downgrade"]()
        restored = json.loads(conn.execute(sa.text("SELECT transcript FROM conversation_sessions")).scalar_one())
        for actual, original in zip(restored, messages, strict=True):
            for key, value in original.items():
                if key != "is_streaming":
                    assert actual[key] == value
        assert restored[2]["is_streaming"] is False
        migration["upgrade"]()
        assert [r[0] for r in conn.execute(sa.text("SELECT id FROM conversation_messages ORDER BY position"))] == [
            r["id"] for r in records
        ]
    engine.dispose()


def test_sqlite_migration_is_atomic_on_corrupt_legacy_data(store):
    with sqlite3.connect(store._DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE conversation_sessions (session_id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT, message_count INTEGER, key_tickers TEXT, key_topics TEXT, summary TEXT, transcript TEXT)"
        )
        conn.execute("INSERT INTO conversation_sessions (session_id, transcript) VALUES ('bad', 'corrupt')")
    with pytest.raises(ValueError, match="Cannot migrate"):
        store.get_session("bad")
    assert store._conn is None
    with sqlite3.connect(store._DB_PATH) as conn:
        assert conn.execute("SELECT transcript FROM conversation_sessions").fetchone()[0] == "corrupt"
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name = 'conversation_messages'").fetchall()


def test_legacy_fallback_never_silently_drops_corrupt_history():
    assert (
        legacy_messages({"server_messages": "invalid", "transcript": '[{"role":"user","content":"kept"}]'})[0][
            "content"
        ]
        == "kept"
    )
    with pytest.raises(ValueError):
        legacy_messages({"server_messages": "[1]", "transcript": "[]"})


def test_guard_persists_tools_sources_trace_and_exposes_ids(store, monkeypatch):
    monkeypatch.setattr("api.memory_manager._ensure_session_title", lambda *args: None)
    sid, user, answer = begin(store)
    req = AgentChatRequest(
        session_id=sid,
        client_turn_id="turn",
        message="question",
        finalize_synchronously=True,
        user_message_id=user["id"],
        assistant_message_id=answer["id"],
    )
    guard = _TurnTranscriptGuard(req)
    guard.session_id = sid
    payload = {
        "id": "search",
        "name": "web_search",
        "status": "ok",
        "arguments": {"q": "rates"},
        "result": json.dumps({"sources": [{"url": "https://example.com", "title": "Source"}]}),
    }
    guard.observe(_sse("tool_result", payload))
    guard.observe(_sse("delta", {"text": "answer"}))
    guard.finalize(sid, user, {**answer, "content": "answer"})
    done = guard.observe(_sse("done", {"decision_quality_chat": {"verdict": "watch"}}))
    assert json.loads(done.split("data: ")[1])["assistant_message_id"] == answer["id"]
    message = store.get_session(sid)["transcript"][-1]
    # The saved tool call holds a preview of the result, not the whole result.
    saved = {key: value for key, value in message["tool_calls"][0].items() if key != "as_of"}
    assert saved == {
        "id": "search",
        "name": "web_search",
        "status": "ok",
        "arguments": {"q": "rates"},
        "result_preview": payload["result"],
        "result_bytes": len(payload["result"]),
        "sources": [{"url": "https://example.com", "title": "Source"}],
    }
    assert message["tool_calls"][0]["as_of"]
    assert message["sources"] == [{"url": "https://example.com", "title": "Source"}]
    assert message["trace_snapshot"] == {"decision_quality_chat": {"verdict": "watch"}}


def test_normal_chat_roundtrip_returns_persisted_ids_tools_and_sources(store, auth_client, monkeypatch):
    import api.routers.agent as agent
    from tests.test_agent_streaming import _event_text_delta, _event_tool_use_start, _install_fake_anthropic, _parse_sse

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(agent, "_build_agent_instructions", lambda screen_context=None: "agent instructions")
    monkeypatch.setattr("api.memory_manager._ensure_session_title", lambda *args: None)
    source = {"url": "https://example.com/report", "title": "Report"}
    monkeypatch.setattr(agent, "execute_tool", lambda _name, _args: json.dumps({"sources": [source], "value": 42}))
    _install_fake_anthropic(
        monkeypatch,
        [
            (
                [_event_tool_use_start("query_ontology", "call-1")],
                SimpleNamespace(
                    content=[{"type": "tool_use", "name": "query_ontology", "id": "call-1", "input": {"query": "A"}}],
                    stop_reason="tool_use",
                    usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                ),
            ),
            (
                [_event_text_delta("Saved answer")],
                SimpleNamespace(
                    content=[{"type": "text", "text": "Saved answer"}],
                    stop_reason="end_turn",
                    usage=SimpleNamespace(input_tokens=1, output_tokens=2),
                ),
            ),
        ],
    )
    response = auth_client.post(
        "/api/agent/chat",
        json={
            "message": "portfolio test",
            "client_turn_id": "roundtrip",
            "finalize_synchronously": True,
            "user_message_id": "http-user",
            "assistant_message_id": "http-answer",
        },
    )
    done = next(payload for event, payload in _parse_sse(response.text) if event == "done")
    assert done["user_message_id"] == "http-user" and done["assistant_message_id"] == "http-answer"
    loaded = auth_client.get(f"/api/memory/sessions/{done['session_id']}").json()["transcript"]
    assert [message["id"] for message in loaded] == ["http-user", "http-answer"]
    assert loaded[-1]["content"] == "Saved answer" and loaded[-1]["sources"] == [source]
    tool_call = loaded[-1]["tool_calls"][0]
    assert tool_call["arguments"]["query"] == "A"
    assert json.loads(tool_call["result_preview"])["value"] == 42
    assert "result" not in tool_call and tool_call["result_bytes"] == len(tool_call["result_preview"])
    assert tool_call["as_of"] and tool_call["sources"] == [source]


def test_interrupted_tool_result_survives_with_partial_text(store):
    sid, user, answer = begin(store)
    req = AgentChatRequest(session_id=sid, client_turn_id="turn", message="question", finalize_synchronously=True)
    guard = _TurnTranscriptGuard(req)
    guard.session_id = sid
    guard.observe(_sse("tool_result", {"id": "tool", "name": "search", "status": "ok"}))
    guard.observe(_sse("delta", {"text": "partial"}))
    guard.settle()
    message = store.get_session(sid)["transcript"][-1]
    assert message["status"] == "stopped" and message["content"] == "partial"
    assert message["tool_calls"][0]["id"] == "tool"


def test_thinking_narration_and_tool_activity_survive_a_stopped_turn_and_reload(store):
    sid, user, answer = begin(store)
    req = AgentChatRequest(session_id=sid, client_turn_id="turn", message="question", finalize_synchronously=True)
    guard = _TurnTranscriptGuard(req)
    guard.session_id = sid
    tool = {
        "id": "tool",
        "name": "search_web",
        "status": "ok",
        "arguments": {"query": "fed"},
        "result_preview": '{"rows": 1}',
        "result_bytes": 11,
        "as_of": "2026-10-23T13:30:00+00:00",
        "elapsed_ms": 12.5,
        "sources": [{"url": "https://example.com/fed", "title": "Fed"}],
    }
    guard.observe(_sse("thinking", {"id": "thinking:agent_chat:0:0", "text": "First draft"}))
    # A retried model call sends its summary again under the same id.
    guard.observe(_sse("thinking", {"id": "thinking:agent_chat:0:0", "text": "Weighing the book"}))
    guard.observe(_sse("narration", {"id": "narration:0", "text": "Let me look."}))
    guard.observe(_sse("tool_result", tool))
    guard.observe(_sse("delta", {"text": "partial"}))
    guard.settle()

    message = store.get_session(sid)["transcript"][-1]

    assert message["status"] == "stopped" and message["content"] == "partial"
    assert message["thinking"] == [{"id": "thinking:agent_chat:0:0", "text": "Weighing the book"}]
    assert message["narration"] == [{"id": "narration:0", "text": "Let me look."}]
    assert message["tool_calls"] == [tool]
    assert message["sources"] == [{"url": "https://example.com/fed", "title": "Fed"}]
    kinds = [part["type"] for part in message["content_parts"]]
    assert sorted(set(kinds)) == ["narration", "source", "text", "thinking", "tool_call"]


def test_retrying_a_job_turn_clears_the_previous_attempts_activity(store):
    sid, user, answer = begin(store)
    store.update_assistant_message(
        sid,
        "turn",
        {"thinking": [{"id": "t", "text": "old"}], "narration": [{"id": "n", "text": "old"}], "async_job_id": "job-1"},
    )

    assert store.begin_job_turn(sid, "turn", "job-2")

    message = store.get_session(sid)["transcript"][-1]
    assert message["thinking"] == [] and message["narration"] == []


def test_sources_support_provider_annotations_and_dedupe_urls():
    value = {
        "output": [{"annotations": [{"type": "url_citation", "url": "https://example.com", "title": "Example"}]}],
        "citations": [{"url": "https://example.com"}],
    }
    assert sources_from(value) == [{"type": "url_citation", "url": "https://example.com", "title": "Example"}]


@pytest.fixture
def pg_store(monkeypatch):
    if not os.getenv("TEST_POSTGRES_URL"):
        pytest.skip("TEST_POSTGRES_URL must point at a disposable local Postgres database")
    from api import postgres
    from scripts.benchmark_agent_chat_streaming import disposable_job_database, test_database_url

    with disposable_job_database(test_database_url()) as dsn:
        postgres.close_pools()
        monkeypatch.setenv("DATABASE_URL", dsn)
        monkeypatch.setenv("STATE_DB_BACKEND", "postgres")
        monkeypatch.setenv("POSTGRES_POOL_MIN_SIZE", "0")
        monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "3")
        yield memory_db, dsn
        postgres.close_pools()


def test_postgres_row_lock_excludes_a_late_partial_write(pg_store):
    from api.postgres_state import PostgresStateConnection

    store, _ = pg_store
    sid, _, _ = begin(store)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with PostgresStateConnection() as terminal:
            row = store._turn_row(terminal, sid, "turn")
            store._patch_row(terminal, row, {"content": "finished", "status": "complete"})
            pending = executor.submit(
                store.update_assistant_message, sid, "turn", {"content": "late"}, only_streaming=True
            )
            time.sleep(0.05)
            assert not pending.done(), "a different connection must wait for the message row lock"
        assert pending.result(timeout=3) is False
    assert store.get_session(sid)["transcript"][-1]["content"] == "finished"


def test_postgres_migration_roundtrip_preserves_legacy_ids_and_parts(pg_store):
    import psycopg

    from api import postgres

    store, dsn = pg_store
    sid, user, answer = begin(store)
    store.update_assistant_message(
        sid, "turn", {"content": "answer", "status": "complete", "sources": [{"url": "https://example.com/report"}]}
    )
    before = store.get_session(sid)["transcript"]
    postgres.close_pools()
    engine = sa.create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn))
    migration = runpy.run_path(str(MIGRATION))
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration["downgrade"]()
        assert json.loads(conn.execute(sa.text("SELECT transcript FROM conversation_sessions")).scalar_one()) == before
        migration["upgrade"]()
    engine.dispose()
    assert store.get_session(sid)["transcript"] == before
