"""
Persistent conversation memory for the AI agent.

Stores conversation sessions and summaries so the agent can reference past
research across sessions.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from api.conversation_messages import (
    CREATE_MESSAGES,
    CREATE_TURN_INDEX,
    MESSAGE_COLUMNS,
    legacy_messages,
    message_record,
    record_message,
)
from api.postgres import retry_read, use_postgres_state
from api.postgres_state import PostgresStateConnection

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DB_PATH = _REPO_ROOT / "data_cache" / "memory" / "memory.db"

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None  # SQLite fallback only; Postgres is always scoped.

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_id   TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    message_count INTEGER DEFAULT 0,
    key_tickers  TEXT,          -- JSON array
    key_topics   TEXT,          -- JSON array
    summary      TEXT,
    title        TEXT,
    title_source TEXT,
    title_updated_at TEXT,
    rolling_summary TEXT,
    rolling_summary_through_id TEXT,
    pinned_at TEXT
)
"""

_CREATE_SESSIONS_IDX = """
CREATE INDEX IF NOT EXISTS idx_sessions_ended_at
ON conversation_sessions(ended_at DESC)
"""

_CREATE_HISTORY_IDX = """
CREATE INDEX IF NOT EXISTS idx_sessions_history
ON conversation_sessions(COALESCE(pinned_at, '') DESC, COALESCE(ended_at, started_at, '') DESC, session_id DESC)
WHERE message_count > 0
"""

SESSION_TITLE_MAX_CHARS = 80

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


@contextmanager
def _get_conn(*, read_only: bool = False) -> Iterator[sqlite3.Connection | PostgresStateConnection]:
    global _conn
    with _lock:
        if use_postgres_state():
            with PostgresStateConnection(read_only=read_only) as conn:
                yield conn
        else:
            if _conn is None:
                _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
                _conn.execute("PRAGMA journal_mode=WAL")
                _conn.execute("PRAGMA foreign_keys=ON")
                _conn.row_factory = sqlite3.Row
                try:
                    _init_db(_conn)
                except BaseException:
                    _conn.rollback()
                    _conn.close()
                    _conn = None
                    raise
            try:
                yield _conn
            except BaseException:
                _conn.rollback()
                raise


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN")
    conn.execute(_CREATE_SESSIONS)
    conn.execute(_CREATE_SESSIONS_IDX)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(conversation_sessions)")}
    for col in (
        "rolling_summary",
        "title",
        "title_source",
        "title_updated_at",
        "rolling_summary_through_id",
        "pinned_at",
    ):
        if col not in columns:
            conn.execute(f"ALTER TABLE conversation_sessions ADD COLUMN {col} TEXT")
    conn.execute(_CREATE_HISTORY_IDX)
    conn.execute(CREATE_MESSAGES)
    conn.execute(CREATE_TURN_INDEX)
    if columns & {"transcript", "server_messages"}:
        for row in conn.execute("SELECT * FROM conversation_sessions").fetchall():
            sid = row["session_id"]
            parent = None
            messages = legacy_messages(dict(row))
            for position, msg in enumerate(messages):
                record = message_record(sid, msg, position, parent, legacy=True)
                _insert_record(conn, record)
                parent = record["id"]
            conn.execute(
                "UPDATE conversation_sessions SET message_count = ? WHERE session_id = ?", (len(messages), sid)
            )
        for col in ("transcript", "server_messages"):
            if col in columns:
                conn.execute(f"ALTER TABLE conversation_sessions DROP COLUMN {col}")
    _backfill_missing_titles(conn)
    conn.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_session(
    messages: list[dict[str, Any]],
    session_id: str | None = None,
) -> dict[str, Any]:
    """Import a transcript snapshot; ordinary turns use targeted message writes."""
    sid = get_or_create_session(session_id)["session_id"]
    now = datetime.now(UTC).isoformat()
    with _get_conn() as conn:
        session = _session_for_write(conn, sid)
        previous_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM conversation_messages WHERE session_id = ? ORDER BY position",
                (sid,),
            ).fetchall()
        ]
        existing = [record_message(row) for row in previous_rows]
        by_id = {row["id"]: row for row in previous_rows}
        records = []
        parent = None
        for position, message in enumerate(messages):
            msg = dict(message)
            if not msg.get("id") and position < len(existing) and existing[position]["role"] == msg.get("role"):
                msg["id"] = existing[position]["id"]
            old = by_id.get(msg.get("id"))
            if old:
                msg = {**record_message(old), **msg}
                if "toolCalls" in message and "tool_calls" not in message:
                    msg["tool_calls"] = message["toolCalls"]
            record = message_record(sid, msg, position, parent)
            if old and any(record[key] != old[key] for key in ("position", "role", "parent_id")):
                raise ValueError("Existing message identity and ancestry are immutable")
            records.append(record)
            parent = record["id"]
        if len({record["id"] for record in records}) != len(records):
            raise ValueError("Message ids must be unique within a transcript")
        retained = {record["id"] for record in records}
        removed = [row["id"] for row in previous_rows if row["id"] not in retained]
        if removed:
            conn.execute(
                f"DELETE FROM conversation_messages WHERE session_id = ? AND id IN ({', '.join('?' for _ in removed)})",
                (sid, *removed),
            )
        for record in records:
            old = by_id.get(record["id"])
            if old is None:
                _insert_record(conn, record)
            elif any(
                (
                    json.loads(record[key]) != json.loads(old[key])
                    if key in {"content_parts", "metadata_json"}
                    else record[key] != old[key]
                )
                for key in MESSAGE_COLUMNS
                if key != "updated_at"
            ):
                _patch_row(conn, old, record_message(record))
        conn.execute(
            "UPDATE conversation_sessions SET message_count = ?, ended_at = ? WHERE session_id = ?",
            (len(records), now, sid),
        )
        conn.commit()
    first_user = _first_user_content(messages)
    if first_user:
        set_deterministic_title_if_missing(sid, first_user)
    return {"session_id": sid, "started_at": session["started_at"], "ended_at": now, "message_count": len(messages)}


def update_summary(
    session_id: str,
    summary: str,
    key_tickers: list[str] | None = None,
    key_topics: list[str] | None = None,
) -> bool:
    """Attach a summary to a session. Returns True if session exists."""
    with _get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE conversation_sessions
            SET summary = ?,
                key_tickers = ?,
                key_topics = ?
            WHERE session_id = ?
            """,
            (
                summary,
                json.dumps(key_tickers) if key_tickers else None,
                json.dumps(key_topics) if key_topics else None,
                session_id,
            ),
        )
        conn.commit()
        return cur.rowcount > 0


def list_sessions(limit: int = 20, *, query: str = "", cursor: str | None = None) -> list[dict[str, Any]]:
    """List nonempty sessions, pinned first, without loading their transcripts.

    The cursor contains the last row's complete sort key. A new conversation
    arriving between pages therefore cannot shift the remaining rows.
    """
    filters = [
        "s.message_count > 0",
        "EXISTS (SELECT 1 FROM conversation_messages m WHERE m.session_id = s.session_id)",
    ]
    params: list[Any] = []
    if query.strip():
        pattern = "%" + query.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        if use_postgres_state():
            parts = "conversation_messages m CROSS JOIN LATERAL jsonb_array_elements(m.content_parts::jsonb) part"
            text_part = "part->>'type' = 'text' AND lower(part->>'text') LIKE ? ESCAPE '\\'"
        else:
            parts = "conversation_messages m JOIN json_each(m.content_parts) part"
            text_part = "json_extract(part.value, '$.type') = 'text' AND lower(json_extract(part.value, '$.text')) LIKE ? ESCAPE '\\'"
        filters.append(
            "(lower(COALESCE(s.title, '')) LIKE ? ESCAPE '\\' "
            "OR lower(COALESCE(s.summary, '')) LIKE ? ESCAPE '\\' "
            f"OR EXISTS (SELECT 1 FROM {parts} WHERE m.session_id = s.session_id AND {text_part}))"
        )
        params.extend([pattern] * 3)
    if cursor:
        try:
            key = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
            if not isinstance(key, list) or len(key) != 3 or any(not isinstance(item, str) for item in key):
                raise ValueError
        except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
            raise ValueError("Invalid history cursor") from exc
        filters.append("(COALESCE(s.pinned_at, ''), COALESCE(s.ended_at, s.started_at, ''), s.session_id) < (?, ?, ?)")
        params.extend(key)
    params.append(limit)

    def _read() -> list[dict[str, Any]]:
        with _get_conn(read_only=True) as conn:
            rows = conn.execute(
                f"""
                SELECT session_id, started_at, ended_at, message_count,
                       key_tickers, key_topics, summary,
                       title, title_source, title_updated_at, pinned_at
                FROM conversation_sessions s
                WHERE {" AND ".join(filters)}
                ORDER BY COALESCE(pinned_at, '') DESC, COALESCE(ended_at, started_at, '') DESC, session_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [_row_to_dict(r) for r in rows]

    return retry_read(_read)


def session_history_cursor(session: dict[str, Any]) -> str:
    key = [
        session.get("pinned_at") or "",
        session.get("ended_at") or session.get("started_at") or "",
        session["session_id"],
    ]
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode("ascii")


def pin_session(session_id: str, pinned: bool) -> dict[str, Any] | None:
    with _get_conn() as conn:
        cur = conn.execute(
            "UPDATE conversation_sessions SET pinned_at = COALESCE(pinned_at, ?) WHERE session_id = ?"
            if pinned
            else "UPDATE conversation_sessions SET pinned_at = ? WHERE session_id = ?",
            (datetime.now(UTC).isoformat() if pinned else None, session_id),
        )
        conn.commit()
    return get_session_summary(session_id) if cur.rowcount > 0 else None


def get_session(session_id: str) -> dict[str, Any] | None:
    """Assemble the compatibility transcript from ordered message rows."""

    def _read() -> dict[str, Any] | None:
        with _get_conn(read_only=True) as conn:
            row = conn.execute("SELECT * FROM conversation_sessions WHERE session_id = ?", (session_id,)).fetchone()
            if row is None:
                return None
            return {**_row_to_dict(row), "transcript": _load_session_messages(conn, session_id)}

    return retry_read(_read)


def delete_session(session_id: str) -> bool:
    """Delete a session. Returns True if it existed."""
    with _get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM conversation_sessions WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()
        return cur.rowcount > 0


def get_recent_summaries(
    limit: int = 5,
    tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent session summaries for agent context injection.

    If *tickers* is provided, prefer sessions mentioning those tickers,
    but still fall back to the most recent if none match.
    """

    def _read() -> list[dict[str, Any]]:
        with _get_conn(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT session_id, started_at, ended_at, message_count,
                       key_tickers, key_topics, summary,
                       title, title_source, title_updated_at
                FROM conversation_sessions
                WHERE summary IS NOT NULL AND summary != ''
                ORDER BY ended_at DESC
                LIMIT ?
                """,
                (limit * 3,),
            ).fetchall()

            results = [_row_to_dict(r) for r in rows]

            if tickers:
                upper = {t.upper() for t in tickers}
                relevant = [r for r in results if _tickers_overlap(r.get("key_tickers"), upper)]
                if relevant:
                    return relevant[:limit]

            return results[:limit]

    return retry_read(_read)


# ---------------------------------------------------------------------------
# Server-managed session state (rolling memory)
# ---------------------------------------------------------------------------


def get_or_create_session(session_id: str | None = None) -> dict[str, Any]:
    """Return metadata and a server-memory view assembled from message rows."""
    sid = session_id or str(uuid.uuid4())
    if session_id:
        session = get_session(sid)
        if session is not None:
            messages = session.pop("transcript")
            return {**session, "server_messages": messages}
    now = datetime.now(UTC).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO conversation_sessions (session_id, started_at, ended_at, message_count) "
            "VALUES (?, ?, ?, 0)",
            (sid, now, now),
        )
        conn.commit()
    return {
        "session_id": sid,
        "started_at": now,
        "rolling_summary": None,
        "server_messages": [],
        "message_count": 0,
        "title": None,
        "title_source": None,
        "title_updated_at": None,
    }


def _load_session_messages(conn: Any, session_id: str) -> list[dict[str, Any]]:
    return [
        record_message(row)
        for row in conn.execute(
            "SELECT * FROM conversation_messages WHERE session_id = ? ORDER BY position",
            (session_id,),
        ).fetchall()
    ]


def _session_for_write(conn: Any, session_id: str) -> Any:
    from api.agent_job_recovery import fence_transcript_write

    fence_transcript_write(conn)
    lock = " FOR UPDATE" if isinstance(conn, PostgresStateConnection) else ""
    row = conn.execute(f"SELECT * FROM conversation_sessions WHERE session_id = ?{lock}", (session_id,)).fetchone()
    if row is None:
        raise ValueError(f"Session {session_id} not found")
    return row


def _insert_record(conn: Any, record: dict[str, Any]) -> None:
    conn.execute(
        f"INSERT INTO conversation_messages ({', '.join(MESSAGE_COLUMNS)}) VALUES ({', '.join('?' for _ in MESSAGE_COLUMNS)})",
        tuple(record[col] for col in MESSAGE_COLUMNS),
    )


def _turn_row(conn: Any, session_id: str, turn_id: str, role: str = "assistant") -> Any:
    lock = " FOR UPDATE" if isinstance(conn, PostgresStateConnection) else ""
    return conn.execute(
        "SELECT * FROM conversation_messages WHERE session_id = ? AND client_turn_id = ? AND role = ? "
        f"ORDER BY position DESC LIMIT 1{lock}",
        (session_id, turn_id, role),
    ).fetchone()


def _message_row(conn: Any, session_id: str, message_id: Any, role: str | None = None) -> Any:
    if not message_id:
        return None
    row = conn.execute(
        "SELECT * FROM conversation_messages WHERE session_id = ? AND id = ?", (session_id, message_id)
    ).fetchone()
    return row if row is not None and (role is None or row["role"] == role) else None


def _with_valid_parent(conn: Any, session_id: str, message: dict[str, Any]) -> dict[str, Any]:
    """Drop a named parent that isn't stored in this session, so the message continues the latest branch."""
    if message.get("parent_id") and _message_row(conn, session_id, message["parent_id"]) is None:
        return {key: value for key, value in message.items() if key != "parent_id"}
    return message


def _patch_row(conn: Any, row: Any, patch: dict[str, Any]) -> None:
    message = {**record_message(row), **patch}
    if "content_parts" in patch:
        for key in ("content", "tool_calls", "toolCalls", "sources", "attachments", "thinking", "narration"):
            if key not in patch:
                message.pop(key, None)
    # Identity and ancestry never change during streaming/finalization.
    message.update(
        id=row["id"], parent_id=row["parent_id"], created_at=row["created_at"], updated_at=datetime.now(UTC).isoformat()
    )
    if "is_streaming" in patch and "status" not in patch:
        message["status"] = "streaming" if patch["is_streaming"] else "complete"
    if "toolCalls" in patch and "tool_calls" not in patch:
        message["tool_calls"] = patch["toolCalls"]
    record = message_record(row["session_id"], message, row["position"], row["parent_id"])
    conn.execute(
        "UPDATE conversation_messages SET status = ?, content_parts = ?, metadata_json = ?, updated_at = ? WHERE id = ? AND session_id = ?",
        (
            record["status"],
            record["content_parts"],
            record["metadata_json"],
            record["updated_at"],
            row["id"],
            row["session_id"],
        ),
    )


def _append(conn: Any, session_id: str, messages: list[dict[str, Any]], count: int) -> int:
    previous = conn.execute(
        "SELECT id, position FROM conversation_messages WHERE session_id = ? ORDER BY position DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    position = previous["position"] + 1 if previous else 0
    parent = previous["id"] if previous else None
    for message in messages:
        record = message_record(session_id, message, position, parent)
        _insert_record(conn, record)
        parent, position = record["id"], position + 1
    total = count + len(messages)
    conn.execute(
        "UPDATE conversation_sessions SET message_count = ?, ended_at = ? WHERE session_id = ?",
        (total, datetime.now(UTC).isoformat(), session_id),
    )
    return total


def turn_exists(session_id: str, client_turn_id: str) -> bool:
    if not client_turn_id:
        return False

    def _read() -> bool:
        with _get_conn(read_only=True) as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM conversation_messages WHERE session_id = ? AND client_turn_id = ? LIMIT 1",
                    (session_id, client_turn_id),
                ).fetchone()
                is not None
            )

    return retry_read(_read)


def attachment_ids_in_use() -> set[str]:
    """Ids of every uploaded file a stored message cites, across all sessions.

    A row that cannot be read raises instead of being skipped: the caller uses this to decide what
    is safe to delete, and a missed citation would delete a file a message still shows.
    """

    def _read() -> list[str]:
        with _get_conn(read_only=True) as conn:
            rows = conn.execute(
                "SELECT content_parts FROM conversation_messages WHERE content_parts LIKE ?", ('%"attachment"%',)
            ).fetchall()
            return [row["content_parts"] for row in rows]

    ids: set[str] = set()
    for raw in retry_read(_read):
        for part in json.loads(raw):
            data = part.get("data") if isinstance(part, dict) and part.get("type") == "attachment" else None
            if isinstance(data, dict) and isinstance(data.get("id"), str):
                ids.add(data["id"])
    return ids


def begin_turn(session_id: str, user_message: dict[str, Any], assistant_placeholder: dict[str, Any]) -> int:
    """Insert the user and streaming assistant once per client turn.

    A user message that is already stored (regenerating its answer) is not inserted again:
    the new streaming assistant becomes another reply to it.
    """
    turn_id = str(user_message.get("client_turn_id") or assistant_placeholder.get("client_turn_id") or "")
    with _get_conn() as conn:
        session = _session_for_write(conn, session_id)
        if turn_id and any(_turn_row(conn, session_id, turn_id, role) is not None for role in ("user", "assistant")):
            return int(session["message_count"] or 0)
        placeholder = {"is_streaming": True, **assistant_placeholder}
        stored_user = _message_row(conn, session_id, user_message.get("id"), "user")
        new_messages = [_with_valid_parent(conn, session_id, user_message), placeholder]
        if stored_user is not None:
            new_messages = [{**placeholder, "parent_id": stored_user["id"]}]
        total = _append(conn, session_id, new_messages, int(session["message_count"] or 0))
        conn.commit()
        return total


def begin_job_turn(session_id: str, client_turn_id: str | None, job_id: str) -> bool:
    if not client_turn_id:
        return False
    with _get_conn() as conn:
        try:
            _session_for_write(conn, session_id)
        except ValueError:
            return False
        row = _turn_row(conn, session_id, client_turn_id)
        if row is None:
            return False
        message = record_message(row)
        previous = message.get("async_job_id")
        if previous == job_id:
            return True
        patch: dict[str, Any] = {"async_job_id": job_id}
        if previous or row["status"] != "streaming":
            patch.update(
                content="", is_streaming=True, status="streaming", tool_calls=[], sources=[], thinking=[], narration=[]
            )
        _patch_row(conn, row, patch)
        conn.commit()
        return True


def update_assistant_message(
    session_id: str,
    client_turn_id: str,
    patch: dict[str, Any],
    *,
    only_streaming: bool = False,
    expected_job_id: str | None = None,
) -> bool:
    """Lock and update just the target row, fenced against stale workers/writes."""
    if not client_turn_id:
        return False
    from api.agent_job_recovery import fence_transcript_write

    with _get_conn() as conn:
        fence_transcript_write(conn)
        row = _turn_row(conn, session_id, client_turn_id)
        if row is None or (only_streaming and row["status"] != "streaming"):
            return False
        if expected_job_id and record_message(row).get("async_job_id") not in {None, expected_job_id}:
            return False
        _patch_row(conn, row, patch)
        conn.commit()
        return True


def complete_turn_messages(
    session_id: str,
    client_turn_id: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
) -> int:
    final = {**assistant_message, "status": "complete", "is_streaming": False}
    if not client_turn_id:
        return append_messages(session_id, [user_message, final])
    with _get_conn() as conn:
        session = _session_for_write(conn, session_id)
        row = _turn_row(conn, session_id, client_turn_id)
        if row is None:
            user = _turn_row(conn, session_id, client_turn_id, "user") or _message_row(
                conn, session_id, user_message.get("id"), "user"
            )
            new_messages = (
                [_with_valid_parent(conn, session_id, user_message), final]
                if user is None
                else [{**final, "parent_id": user["id"]}]
            )
            total = _append(conn, session_id, new_messages, int(session["message_count"] or 0))
        else:
            # Stop/failure and already completed messages are terminal. Only an
            # explicit retry in begin_job_turn may reopen a terminal message.
            if row["status"] == "streaming":
                _patch_row(conn, row, final)
            total = int(session["message_count"] or 0)
            conn.execute(
                "UPDATE conversation_sessions SET ended_at = ? WHERE session_id = ?",
                (datetime.now(UTC).isoformat(), session_id),
            )
        conn.commit()
        return total


def fail_turn(
    session_id: str,
    client_turn_id: str,
    *,
    status: str = "stopped",
    content: str | None = None,
    job_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    patch: dict[str, Any] = {**(metadata or {}), "is_streaming": False, "status": status}
    if content is not None:
        patch["content"] = content
    return update_assistant_message(session_id, client_turn_id, patch, only_streaming=True, expected_job_id=job_id)


def append_messages(session_id: str, messages: list[dict[str, Any]]) -> int:
    with _get_conn() as conn:
        session = _session_for_write(conn, session_id)
        for message in messages:
            turn_id = message.get("client_turn_id") or message.get("clientTurnId")
            if (
                turn_id
                and conn.execute(
                    "SELECT 1 FROM conversation_messages WHERE session_id = ? AND client_turn_id = ? LIMIT 1",
                    (session_id, turn_id),
                ).fetchone()
                is not None
            ):
                return int(session["message_count"] or 0)
        total = _append(conn, session_id, messages, int(session["message_count"] or 0))
        conn.commit()
        return total


def update_rolling_summary(
    session_id: str, summary: str, *, expected: str | None = None, through_id: str | None = None
) -> bool:
    """Update the rolling summary for a session. Returns True if the row was updated.

    ``through_id`` is the last message the summary covers. A conversation with branches uses
    it to tell whether the summary belongs to the branch being continued.

    With ``expected``, the update applies only while the stored summary still equals it
    (an empty string matches no summary), so concurrent summarizers can't overwrite
    each other.
    """
    with _get_conn() as conn:
        if expected is None:
            cur = conn.execute(
                "UPDATE conversation_sessions SET rolling_summary = ?, rolling_summary_through_id = ? "
                "WHERE session_id = ?",
                (summary, through_id, session_id),
            )
        else:
            cur = conn.execute(
                "UPDATE conversation_sessions SET rolling_summary = ?, rolling_summary_through_id = ? "
                "WHERE session_id = ? AND COALESCE(rolling_summary, '') = ?",
                (summary, through_id, session_id, expected),
            )
        conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Session titles
# ---------------------------------------------------------------------------


def normalize_session_title(value: str) -> str:
    """Collapse and validate a user-visible conversation title."""
    title = re.sub(r"\s+", " ", str(value or "")).strip()
    if not title:
        raise ValueError("Title cannot be empty")
    if len(title) > SESSION_TITLE_MAX_CHARS:
        raise ValueError(f"Title must be {SESSION_TITLE_MAX_CHARS} characters or fewer")
    return title


def deterministic_title_from_text(value: str | None) -> str | None:
    """Build a useful fallback title from the first user prompt."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return None

    workflow_match = re.match(r"^/workflow:([A-Za-z0-9_]+)(?::([A-Za-z0-9._=-]+))?(?:\s+(.*))?$", text)
    if workflow_match:
        workflow = workflow_match.group(1).replace("_", " ").strip().title()
        ticker = (workflow_match.group(2) or "").strip().upper()
        trailing = (workflow_match.group(3) or "").strip()
        if trailing:
            text = trailing
        elif ticker:
            text = f"{ticker} {workflow}"
        else:
            text = workflow

    text = re.sub(r"\s+", " ", text).strip(" \t\r\n-:,.!?")
    if not text:
        return None
    return _truncate_title(text)


def set_deterministic_title_if_missing(session_id: str, first_user_message: str | None) -> bool:
    title = deterministic_title_from_text(first_user_message)
    if not title:
        return False
    now = datetime.now(UTC).isoformat()
    with _get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE conversation_sessions
            SET title = ?,
                title_source = ?,
                title_updated_at = ?
            WHERE session_id = ?
              AND (title IS NULL OR trim(title) = '')
              AND (title_source IS NULL OR title_source != 'manual')
            """,
            (title, "deterministic", now, session_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_generated_title(session_id: str, title: str) -> bool:
    normalized = normalize_session_title(title)
    now = datetime.now(UTC).isoformat()
    with _get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE conversation_sessions
            SET title = ?,
                title_source = ?,
                title_updated_at = ?
            WHERE session_id = ?
              AND (title_source IS NULL OR title_source = 'deterministic')
            """,
            (normalized, "generated", now, session_id),
        )
        conn.commit()
        return cur.rowcount > 0


def rename_session(session_id: str, title: str) -> dict[str, Any] | None:
    normalized = normalize_session_title(title)
    now = datetime.now(UTC).isoformat()
    with _get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE conversation_sessions
            SET title = ?,
                title_source = ?,
                title_updated_at = ?
            WHERE session_id = ?
            """,
            (normalized, "manual", now, session_id),
        )
        conn.commit()
    if cur.rowcount <= 0:
        return None
    return get_session_summary(session_id)


def get_session_summary(session_id: str) -> dict[str, Any] | None:
    def _read() -> dict[str, Any] | None:
        with _get_conn(read_only=True) as conn:
            row = conn.execute(
                """
                SELECT session_id, started_at, ended_at, message_count,
                       key_tickers, key_topics, summary,
                       title, title_source, title_updated_at, pinned_at
                FROM conversation_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return _row_to_dict(row)

    return retry_read(_read)


def get_session_title_metadata(session_id: str) -> dict[str, Any] | None:
    def _read() -> dict[str, Any] | None:
        with _get_conn(read_only=True) as conn:
            row = conn.execute(
                """
                SELECT session_id, title, title_source, title_updated_at
                FROM conversation_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return cast(dict[str, Any], dict(row))

    return retry_read(_read)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = cast(dict[str, Any], dict(row))
    for key in ("key_tickers", "key_topics"):
        raw = d.get(key)
        if isinstance(raw, str):
            try:
                d[key] = json.loads(raw)
            except Exception:
                d[key] = None
    d.pop("transcript", None)
    return d


def _truncate_title(value: str) -> str:
    if len(value) <= SESSION_TITLE_MAX_CHARS:
        return value
    candidate = value[:SESSION_TITLE_MAX_CHARS].rstrip()
    word_boundary = candidate.rfind(" ")
    if word_boundary >= 40:
        candidate = candidate[:word_boundary]
    return candidate.rstrip(" -:,.!?")


def _first_user_content(messages: list[dict[str, Any]]) -> str | None:
    for msg in messages:
        if msg.get("role") == "user":
            content = str(msg.get("content", "")).strip()
            if content:
                return content
    return None


def _backfill_missing_titles(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT session_id FROM conversation_sessions WHERE title IS NULL OR trim(title) = ''",
    ).fetchall()

    now = datetime.now(UTC).isoformat()
    for row in rows:
        messages = _load_session_messages(conn, row["session_id"])
        title = deterministic_title_from_text(_first_user_content(messages))
        if not title:
            continue
        conn.execute(
            """
            UPDATE conversation_sessions
            SET title = ?,
                title_source = ?,
                title_updated_at = ?
            WHERE session_id = ?
              AND (title IS NULL OR trim(title) = '')
            """,
            (title, "deterministic", now, row["session_id"]),
        )


def _tickers_overlap(
    stored: list[str] | str | None,
    wanted: set[str],
) -> bool:
    if stored is None:
        return False
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except Exception:
            return False
    if not isinstance(stored, list):
        return False
    return bool(wanted & {str(t).upper() for t in stored})
