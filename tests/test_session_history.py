from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from api import memory_db
from tests import test_memory_db as memory_fixtures
from tests import test_postgres_pool_integration as postgres_fixtures

temp_memory_db = memory_fixtures.temp_memory_db
migrated_database = postgres_fixtures.migrated_database
pg_state = postgres_fixtures.pg_state


def saved(sid: str, text: str = "Saved message") -> dict:
    memory_db.save_session([{"id": f"{sid}-user", "role": "user", "content": text}], session_id=sid)
    memory_db.rename_session(sid, f"Research {sid}")
    return memory_db.get_session_summary(sid)


def test_history_excludes_empty_sessions_even_with_stale_counts(temp_memory_db):
    empty = memory_db.get_or_create_session(None)["session_id"]
    stale = memory_db.get_or_create_session(None)["session_id"]
    with memory_db._get_conn() as conn:
        conn.execute("UPDATE conversation_sessions SET message_count = 4 WHERE session_id = ?", (stale,))
        conn.commit()
    saved("nonempty")

    rows = memory_db.list_sessions(30)
    assert [row["session_id"] for row in rows] == ["nonempty"]
    assert memory_db.get_session(empty) is not None  # Filtering is not destructive.


def test_cursor_pagination_handles_ties_and_new_sessions(temp_memory_db):
    for index in range(35):
        saved(f"session-{index:02}")
    with memory_db._get_conn() as conn:
        conn.execute("UPDATE conversation_sessions SET ended_at = '2026-10-01T00:00:00+00:00'")
        conn.commit()
    first = memory_db.list_sessions(7)
    saved("arrived-between-pages")
    seen = [row["session_id"] for row in first]
    cursor = memory_db.session_history_cursor(first[-1])
    while page := memory_db.list_sessions(7, cursor=cursor):
        seen.extend(row["session_id"] for row in page)
        cursor = memory_db.session_history_cursor(page[-1])
    assert seen == [f"session-{index:02}" for index in reversed(range(35))]


def test_pins_are_persistent_idempotent_and_sort_before_recency(temp_memory_db):
    saved("old")
    saved("new")
    pinned = memory_db.pin_session("old", True)
    assert pinned["pinned_at"]
    assert memory_db.pin_session("old", True)["pinned_at"] == pinned["pinned_at"]
    first = memory_db.list_sessions(1)
    assert first[0]["session_id"] == "old"
    assert memory_db.list_sessions(1, cursor=memory_db.session_history_cursor(first[0]))[0]["session_id"] == "new"
    assert memory_db.pin_session("old", False)["pinned_at"] is None
    assert memory_db.list_sessions(1)[0]["session_id"] == "new"
    assert memory_db.pin_session("missing", True) is None


@pytest.mark.parametrize(
    "query", ["research hidden", "COBALT", "cash runway", "50%", "analysis_2", "café", "\\forecast"]
)
def test_searches_titles_summaries_and_message_text_literally(temp_memory_db, query):
    saved("hidden", "cobalt café analysis_2 is up 50% \\forecast")
    memory_db.update_summary("hidden", "cash runway")
    saved("other", "analysisX2 is up 500 percent forecast")
    assert [row["session_id"] for row in memory_db.list_sessions(query=query)] == ["hidden"]


def test_search_ignores_tool_and_source_metadata(temp_memory_db):
    memory_db.save_session(
        [{"role": "assistant", "content": "Visible answer", "sources": [{"url": "https://example.com/hidden-source"}]}],
        session_id="source",
    )
    assert memory_db.list_sessions(query="hidden-source") == []


def test_history_response_is_bounded_and_never_loads_transcripts(temp_memory_db, monkeypatch):
    for index in range(100):
        saved(str(index))

    def unexpected_load(*args):
        pytest.fail("History must not assemble transcripts")

    monkeypatch.setattr(memory_db, "_load_session_messages", unexpected_load)
    assert len(memory_db.list_sessions(30)) == 30


def test_history_search_and_cursor_on_postgres(pg_state):
    saved("pg-old", "cobalt café analysis_2 is up 50%")
    saved("pg-new", "unrelated message")
    memory_db.get_or_create_session(None)
    memory_db.pin_session("pg-old", True)
    first = memory_db.list_sessions(1)
    assert first[0]["session_id"] == "pg-old"
    second = memory_db.list_sessions(1, cursor=memory_db.session_history_cursor(first[0]))
    assert second[0]["session_id"] == "pg-new"
    assert memory_db.list_sessions(1, cursor=memory_db.session_history_cursor(second[0])) == []
    for query in ["COBALT", "café", "50%", "analysis_2", "research pg-old"]:
        assert [row["session_id"] for row in memory_db.list_sessions(query=query)] == ["pg-old"]


def test_paginated_api_preserves_legacy_list_and_validates_inputs(temp_memory_db, auth_client):
    for index in range(4):
        saved(str(index))
    assert isinstance(auth_client.get("/api/memory/sessions").json(), list)
    response = auth_client.get("/api/memory/sessions", params={"paginated": "true", "limit": 2})
    assert response.status_code == 200
    first = response.json()
    assert len(first["sessions"]) == 2 and first["next_cursor"]
    second = auth_client.get(
        "/api/memory/sessions", params={"paginated": "true", "limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert len(second["sessions"]) == 2 and second["next_cursor"] is None
    assert len({row["session_id"] for row in first["sessions"] + second["sessions"]}) == 4
    assert auth_client.get("/api/memory/sessions?cursor=invalid").status_code == 400
    assert auth_client.get("/api/memory/sessions?limit=0").status_code == 422
    assert auth_client.get("/api/memory/sessions?limit=101").status_code == 422
    assert auth_client.get("/api/memory/sessions", params={"q": "x" * 201}).status_code == 422


def test_pin_api_preserves_title_and_search_returns_old_matches(temp_memory_db, auth_client):
    saved("old", "rare platinum insight")
    for index in range(35):
        saved(f"recent-{index}")
    response = auth_client.patch("/api/memory/sessions/old", json={"pinned": True})
    assert response.status_code == 200
    assert response.json()["title"] == "Research old"
    assert response.json()["pinned_at"]
    assert auth_client.get("/api/memory/sessions").json()[0]["session_id"] == "old"
    assert auth_client.patch("/api/memory/sessions/old", json={"pinned": False}).json()["pinned_at"] is None
    assert auth_client.patch("/api/memory/sessions/old", json={}).status_code == 400
    assert auth_client.patch("/api/memory/sessions/missing", json={"pinned": True}).status_code == 404
    found = auth_client.get("/api/memory/sessions", params={"q": "platinum", "paginated": "true"}).json()
    assert [row["session_id"] for row in found["sessions"]] == ["old"]


def test_running_sessions_cannot_be_deleted(temp_memory_db, auth_client, monkeypatch):
    from api.routers import memory

    saved("running")
    monkeypatch.setattr(memory, "_active_agent_chat_session_ids", lambda: {"running"})
    assert auth_client.delete("/api/memory/sessions/running").status_code == 409
    assert memory_db.get_session("running")["transcript"]


def test_markdown_export_preserves_latest_branch_text_and_sources(temp_memory_db, auth_client):
    memory_db.save_session(
        [
            {"id": "question", "parent_id": None, "role": "user", "content": "Review **liquidity**"},
            {"id": "old", "parent_id": "question", "role": "assistant", "content": "Superseded answer"},
            {
                "id": "new",
                "parent_id": "question",
                "role": "assistant",
                "content": "### Latest answer\n\n```python\nrisk = 2\n```",
                "sources": [{"url": "https://example.com/report", "title": "Report"}],
            },
        ],
        session_id="export",
    )
    memory_db.rename_session("export", "Liquidity research")
    response = auth_client.get("/api/memory/sessions/export/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("# Liquidity research\n\n## User")
    assert "Review **liquidity**" in response.text and "risk = 2" in response.text
    assert "[Report](https://example.com/report)" in response.text
    assert "Superseded answer" not in response.text
    assert auth_client.get("/api/memory/sessions/missing/export").status_code == 404


def test_history_migration_cleans_only_empty_inactive_sessions(tmp_path):
    migration = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "migrations/versions/20261024_tl214_session_history.py")
    )
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        conn.execute(
            sa.text(
                "CREATE TABLE conversation_sessions (session_id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT, message_count INTEGER)"
            )
        )
        conn.execute(sa.text("CREATE TABLE conversation_messages (id TEXT PRIMARY KEY, session_id TEXT)"))
        conn.execute(sa.text("CREATE TABLE async_jobs (job_type TEXT, status TEXT, payload_json TEXT)"))
        for sid, count in [
            ("empty", 0),
            ("stale-count", 3),
            ("nonempty", 0),
            ("queued", 0),
            ("running", 0),
            ("finished", 0),
        ]:
            conn.execute(
                sa.text("INSERT INTO conversation_sessions VALUES (:sid, 'old', 'old', :count)"),
                {"sid": sid, "count": count},
            )
        conn.execute(sa.text("INSERT INTO conversation_messages VALUES ('message', 'nonempty')"))
        for sid, status in [("queued", "queued"), ("running", "running"), ("finished", "done")]:
            conn.execute(
                sa.text("INSERT INTO async_jobs VALUES ('agent_chat_turn', :status, :payload)"),
                {"status": status, "payload": json.dumps({"session_id": sid})},
            )
        migration["upgrade"]()
        assert {row[0] for row in conn.execute(sa.text("SELECT session_id FROM conversation_sessions"))} == {
            "nonempty",
            "queued",
            "running",
        }
        assert "pinned_at" in {column["name"] for column in sa.inspect(conn).get_columns("conversation_sessions")}
        migration["downgrade"]()
        assert "pinned_at" not in {column["name"] for column in sa.inspect(conn).get_columns("conversation_sessions")}
        assert conn.execute(sa.text("SELECT count(*) FROM conversation_messages")).scalar_one() == 1
