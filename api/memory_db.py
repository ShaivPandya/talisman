"""
Persistent conversation memory for the AI agent.

Stores conversation sessions and summaries so the agent can reference past
research across sessions.
"""

from __future__ import annotations

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
    transcript   TEXT NOT NULL  -- JSON array of messages
)
"""

_CREATE_SESSIONS_IDX = """
CREATE INDEX IF NOT EXISTS idx_sessions_ended_at
ON conversation_sessions(ended_at DESC)
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
                _conn.row_factory = sqlite3.Row
                _init_db(_conn)
            try:
                yield _conn
            except BaseException:
                _conn.rollback()
                raise


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_SESSIONS)
    conn.execute(_CREATE_SESSIONS_IDX)
    # Migrate: add columns for server-managed rolling memory
    for col, typedef in [
        ("rolling_summary", "TEXT"),
        ("server_messages", "TEXT NOT NULL DEFAULT '[]'"),
        ("title", "TEXT"),
        ("title_source", "TEXT"),
        ("title_updated_at", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE conversation_sessions ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass  # column already exists
    _backfill_missing_titles(conn)
    conn.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_session(
    messages: list[dict[str, Any]],
    session_id: str | None = None,
) -> dict[str, Any]:
    """Save a conversation transcript. Returns the session record."""
    with _get_conn() as conn:
        sid = session_id or str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()

        timestamps: list[float] = [m["timestamp"] for m in messages if m.get("timestamp") is not None]
        started_at = datetime.fromtimestamp(min(timestamps) / 1000, tz=UTC).isoformat() if timestamps else now

        transcript_json = json.dumps(messages, default=str)

        conn.execute(
            """
            INSERT INTO conversation_sessions
                (session_id, started_at, ended_at, message_count, transcript, server_messages)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                ended_at = excluded.ended_at,
                message_count = excluded.message_count,
                transcript = excluded.transcript,
                server_messages = excluded.server_messages
            """,
            (sid, started_at, now, len(messages), transcript_json, transcript_json),
        )
        conn.commit()

    first_user = _first_user_content(messages)
    if first_user:
        set_deterministic_title_if_missing(sid, first_user)

    return {
        "session_id": sid,
        "started_at": started_at,
        "ended_at": now,
        "message_count": len(messages),
    }


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


def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
    """List recent sessions (without full transcripts)."""

    def _read() -> list[dict[str, Any]]:
        with _get_conn(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT session_id, started_at, ended_at, message_count,
                       key_tickers, key_topics, summary,
                       title, title_source, title_updated_at
                FROM conversation_sessions
                ORDER BY ended_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]

    return retry_read(_read)


def get_session(session_id: str) -> dict[str, Any] | None:
    """Load a full session including transcript."""

    def _read() -> dict[str, Any] | None:
        with _get_conn(read_only=True) as conn:
            row = conn.execute(
                """
                    SELECT session_id, started_at, ended_at, message_count,
                       key_tickers, key_topics, summary,
                       title, title_source, title_updated_at,
                       transcript, server_messages
                FROM conversation_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            result = _row_to_dict(row)
            try:
                result["transcript"] = json.loads(row["transcript"])
            except Exception:
                result["transcript"] = []
            if not result["transcript"]:
                try:
                    result["transcript"] = json.loads(row["server_messages"]) if row["server_messages"] else []
                except Exception:
                    result["transcript"] = []
            result.pop("server_messages", None)
            return result

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
    """Load an existing session or create a new one.

    Returns a dict with parsed ``server_messages`` (list) and
    ``rolling_summary`` (str | None).
    """
    sid = session_id or str(uuid.uuid4())

    if session_id:

        def _read():
            with _get_conn(read_only=True) as conn:
                row = conn.execute(
                    """
                    SELECT session_id, started_at, ended_at, message_count,
                           rolling_summary, server_messages, transcript,
                           title, title_source, title_updated_at
                    FROM conversation_sessions
                    WHERE session_id = ?
                    """,
                    (sid,),
                ).fetchone()
            return row

        row = retry_read(_read)
        if row is not None:
            try:
                msgs = json.loads(row["server_messages"]) if row["server_messages"] else []
            except Exception:
                msgs = []
            if not msgs:
                try:
                    msgs = json.loads(row["transcript"]) if row["transcript"] else []
                except Exception:
                    msgs = []
            return {
                "session_id": row["session_id"],
                "started_at": row["started_at"],
                "rolling_summary": row["rolling_summary"],
                "server_messages": msgs,
                "message_count": row["message_count"] or 0,
                "title": row["title"],
                "title_source": row["title_source"],
                "title_updated_at": row["title_updated_at"],
            }

    # Create a new session
    now = datetime.now(UTC).isoformat()
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO conversation_sessions
                (session_id, started_at, ended_at, message_count, transcript, server_messages)
            VALUES (?, ?, ?, 0, '[]', '[]')
            """,
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


def _load_session_messages(
    conn: sqlite3.Connection | PostgresStateConnection,
    session_id: str,
    *,
    for_update: bool = False,
) -> list[dict[str, Any]]:
    """Read a session's messages. ``for_update`` locks the Postgres row until commit.

    In one process ``_lock`` already serializes writers; the row lock also keeps the
    API process and a worker from interleaving read-modify-write cycles on one turn.
    """
    lock = " FOR UPDATE" if for_update and isinstance(conn, PostgresStateConnection) else ""
    row = conn.execute(
        f"SELECT server_messages, transcript FROM conversation_sessions WHERE session_id = ?{lock}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Session {session_id} not found")
    try:
        existing = json.loads(row["server_messages"]) if row["server_messages"] else []
    except Exception:
        existing = []
    if not existing:
        try:
            existing = json.loads(row["transcript"]) if row["transcript"] else []
        except Exception:
            existing = []
    return [m for m in existing if isinstance(m, dict)]


def _save_session_messages(
    conn: sqlite3.Connection | PostgresStateConnection,
    session_id: str,
    messages: list[dict[str, Any]],
) -> int:
    from api.agent_job_recovery import fence_transcript_write

    fence_transcript_write(conn)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        UPDATE conversation_sessions
        SET server_messages = ?, transcript = ?, message_count = ?, ended_at = ?
        WHERE session_id = ?
        """,
        (json.dumps(messages, default=str), json.dumps(messages, default=str), len(messages), now, session_id),
    )
    return len(messages)


def turn_exists(session_id: str, client_turn_id: str) -> bool:
    """Return True if any message in the session carries this client_turn_id."""
    if not client_turn_id:
        return False

    def _read() -> bool:
        with _get_conn(read_only=True) as conn:
            try:
                messages = _load_session_messages(conn, session_id)
            except ValueError:
                return False
            return any(str(m.get("client_turn_id")) == client_turn_id for m in messages)

    return retry_read(_read)


def begin_turn(
    session_id: str,
    user_message: dict[str, Any],
    assistant_placeholder: dict[str, Any],
) -> int:
    """Append user + streaming assistant for a turn. Idempotent per client_turn_id."""
    client_turn_id = str(user_message.get("client_turn_id") or assistant_placeholder.get("client_turn_id") or "")
    with _get_conn() as conn:
        messages = _load_session_messages(conn, session_id)
        if client_turn_id and any(str(m.get("client_turn_id")) == client_turn_id for m in messages):
            return len(messages)
        messages.append(user_message)
        messages.append(assistant_placeholder)
        total = _save_session_messages(conn, session_id, messages)
        conn.commit()
        return total


def begin_job_turn(session_id: str, client_turn_id: str | None, job_id: str) -> bool:
    """Bind a claimed job to its placeholder and reopen an explicit retry."""
    if not client_turn_id:
        return False
    with _get_conn() as conn:
        try:
            messages = _load_session_messages(conn, session_id, for_update=True)
        except ValueError:
            return False
        for msg in messages:
            if msg.get("role") != "assistant" or str(msg.get("client_turn_id")) != client_turn_id:
                continue
            previous = msg.get("async_job_id")
            if previous == job_id:
                return True
            if previous or not msg.get("is_streaming"):
                msg.update(content="", is_streaming=True, status="streaming")
            msg["async_job_id"] = job_id
            _save_session_messages(conn, session_id, messages)
            conn.commit()
            return True
    return False


def update_assistant_message(
    session_id: str,
    client_turn_id: str,
    patch: dict[str, Any],
    *,
    only_streaming: bool = False,
    expected_job_id: str | None = None,
) -> bool:
    """Patch the assistant message for a turn. Returns True if updated.

    With ``only_streaming``, the patch applies only while the message is still
    streaming, so a late write can never change a finished turn.
    """
    if not client_turn_id:
        return False
    with _get_conn() as conn:
        try:
            messages = _load_session_messages(conn, session_id, for_update=True)
        except ValueError:
            return False
        updated = False
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            if str(msg.get("client_turn_id")) != client_turn_id:
                continue
            if expected_job_id and msg.get("async_job_id") not in {None, expected_job_id}:
                return False
            if only_streaming and not msg.get("is_streaming"):
                return False
            for key, value in patch.items():
                msg[key] = value
            updated = True
            break
        if not updated:
            return False
        _save_session_messages(conn, session_id, messages)
        conn.commit()
        return True


def complete_turn_messages(
    session_id: str,
    client_turn_id: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
) -> int:
    """Finalize an incremental turn in place. Idempotent if already complete."""
    if not client_turn_id:
        return append_messages(session_id, [user_message, assistant_message])
    with _get_conn() as conn:
        messages = _load_session_messages(conn, session_id, for_update=True)
        found_turn = any(str(m.get("client_turn_id")) == client_turn_id for m in messages)
        if not found_turn:
            messages.extend([user_message, assistant_message])
            total = _save_session_messages(conn, session_id, messages)
            conn.commit()
            return total

        new_messages: list[dict[str, Any]] = []
        replaced = False
        for msg in messages:
            if str(msg.get("client_turn_id")) != client_turn_id:
                new_messages.append(msg)
                continue
            if msg.get("role") == "user":
                merged = {**msg, **user_message}
                new_messages.append(merged)
            elif msg.get("role") == "assistant":
                merged = {**msg, **assistant_message, "is_streaming": False}
                new_messages.append(merged)
                replaced = True
        if not replaced:
            new_messages.append(assistant_message)
        total = _save_session_messages(conn, session_id, new_messages)
        conn.commit()
        return total


def fail_turn(
    session_id: str,
    client_turn_id: str,
    *,
    status: str = "stopped",
    content: str | None = None,
    job_id: str | None = None,
) -> bool:
    """Mark a still-streaming assistant turn as stopped or failed. Never touches a finished turn."""
    patch: dict[str, Any] = {"is_streaming": False, "status": status}
    if content is not None:
        patch["content"] = content
    return update_assistant_message(session_id, client_turn_id, patch, only_streaming=True, expected_job_id=job_id)


def append_messages(session_id: str, messages: list[dict[str, Any]]) -> int:
    """Append messages to a session's server_messages. Returns new total count."""
    with _get_conn() as conn:
        now = datetime.now(UTC).isoformat()
        turn_ids = {str(m.get("client_turn_id")) for m in messages if m.get("client_turn_id")}
        row = conn.execute(
            "SELECT server_messages, transcript FROM conversation_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Session {session_id} not found")
        try:
            existing = json.loads(row["server_messages"]) if row["server_messages"] else []
        except Exception:
            existing = []
        if not existing:
            try:
                existing = json.loads(row["transcript"]) if row["transcript"] else []
            except Exception:
                existing = []
        if turn_ids and any(str(m.get("client_turn_id")) in turn_ids for m in existing if isinstance(m, dict)):
            return len(existing)
        existing.extend(messages)
        conn.execute(
            """
            UPDATE conversation_sessions
            SET server_messages = ?, transcript = ?, message_count = ?, ended_at = ?
            WHERE session_id = ?
            """,
            (json.dumps(existing, default=str), json.dumps(existing, default=str), len(existing), now, session_id),
        )
        conn.commit()
        return len(existing)


def update_rolling_summary(session_id: str, summary: str, *, expected: str | None = None) -> bool:
    """Update the rolling summary for a session. Returns True if the row was updated.

    With ``expected``, the update applies only while the stored summary still equals it
    (an empty string matches no summary), so concurrent summarizers can't overwrite
    each other.
    """
    with _get_conn() as conn:
        if expected is None:
            cur = conn.execute(
                "UPDATE conversation_sessions SET rolling_summary = ? WHERE session_id = ?",
                (summary, session_id),
            )
        else:
            cur = conn.execute(
                "UPDATE conversation_sessions SET rolling_summary = ? "
                "WHERE session_id = ? AND COALESCE(rolling_summary, '') = ?",
                (summary, session_id, expected),
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
                       title, title_source, title_updated_at
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
    try:
        rows = conn.execute(
            """
            SELECT session_id, transcript, server_messages
            FROM conversation_sessions
            WHERE title IS NULL OR trim(title) = ''
            """
        ).fetchall()
    except Exception:
        return
    now = datetime.now(UTC).isoformat()
    for row in rows:
        messages: list[dict[str, Any]] = []
        for field in ("transcript", "server_messages"):
            try:
                raw = row[field]
                parsed = json.loads(raw) if raw else []
                if isinstance(parsed, list) and parsed:
                    messages = [m for m in parsed if isinstance(m, dict)]
                    break
            except Exception:
                continue
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
