"""
Conversation memory endpoints for the AI agent.

Provides persistence, summarization, and retrieval of past agent
conversations so the agent can maintain continuity across sessions.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator

from api import memory_db
from api.agent_stream_liveness import stream_lease_active
from api.conversation_messages import latest_leaf_id, message_path
from llm_utils import MODEL_LOW, call_llm_text, has_llm_api_key

router = APIRouter()
logger = logging.getLogger("api.memory")

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SaveSessionRequest(BaseModel):
    messages: list[dict[str, Any]]
    session_id: str | None = None


class SaveSessionResponse(BaseModel):
    session_id: str
    started_at: str
    ended_at: str
    message_count: int


class SummarizeResponse(BaseModel):
    session_id: str
    summary: str
    key_tickers: list[str]
    key_topics: list[str]


class SessionListItem(BaseModel):
    session_id: str
    started_at: str | None
    ended_at: str | None
    message_count: int
    key_tickers: list[str] | None
    key_topics: list[str] | None
    summary: str | None
    title: str | None = None
    title_source: str | None = None
    title_updated_at: str | None = None
    has_active_job: bool = False
    pinned_at: str | None = None


class SessionHistoryPage(BaseModel):
    sessions: list[SessionListItem]
    next_cursor: str | None = None


class UpdateSessionRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class MemorySettingsRequest(BaseModel):
    enabled: bool


class EditMemoryRequest(BaseModel):
    summary: str = Field(min_length=1, max_length=12000)

    @field_validator("summary")
    @classmethod
    def nonempty_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Memory cannot be empty")
        return value.strip()


@router.get("/memory/entries")
def list_memory_entries(
    q: str = Query("", max_length=200), limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)
):
    from api.memory_context import list_memories

    entries = list_memories(query=q, limit=limit + 1, offset=offset)
    return {"entries": entries[:limit], "has_more": len(entries) > limit}


@router.patch("/memory/entries/{session_id}")
def edit_memory_entry(session_id: str, req: EditMemoryRequest):
    from api.memory_context import edit_memory

    if not edit_memory(session_id, req.summary):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "updated"}


@router.delete("/memory/entries/{session_id}")
def delete_memory_entry(session_id: str):
    from api.memory_context import delete_memory

    if not delete_memory(session_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted"}


@router.get("/memory/sessions/{session_id}/memory")
def get_memory_settings(session_id: str):
    with memory_db._get_conn(read_only=True) as conn:
        row = conn.execute(
            "SELECT memory_enabled FROM conversation_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"enabled": bool(row["memory_enabled"])}


@router.patch("/memory/sessions/{session_id}/memory")
def update_memory_settings(session_id: str, req: MemorySettingsRequest):
    from api.memory_context import set_memory_enabled

    if not set_memory_enabled(session_id, req.enabled):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"enabled": req.enabled}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/memory/sessions", response_model=SaveSessionResponse)
def save_session(req: SaveSessionRequest):
    """Save a conversation transcript."""
    if not req.messages:
        raise HTTPException(status_code=400, detail="No messages to save")
    result = memory_db.save_session(
        messages=req.messages,
        session_id=req.session_id,
    )
    return SaveSessionResponse(**result)


@router.post("/memory/sessions/{session_id}/summarize", response_model=SummarizeResponse)
def summarize_session(session_id: str):
    """Generate an AI summary for a saved session."""
    session = memory_db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    transcript = session.get("transcript", [])
    if not transcript:
        raise HTTPException(status_code=400, detail="Session has no transcript")

    summary, tickers, topics = _summarize_transcript(transcript)

    memory_db.update_summary(
        session_id=session_id,
        summary=summary,
        key_tickers=tickers,
        key_topics=topics,
    )

    # Index summary for semantic search (best-effort)
    try:
        from api.retrieval import index_document

        index_content = summary
        if tickers:
            index_content = f"Tickers: {', '.join(tickers)}\n\n{index_content}"
        if topics:
            index_content = f"Topics: {', '.join(topics)}\n\n{index_content}"
        index_document(
            doc_type="conversation_summary",
            content=index_content,
            ticker=tickers[0] if tickers else None,
            doc_id=f"conversation-{session_id}",
        )
    except Exception:
        logger.debug("Failed to index conversation summary for retrieval", exc_info=True)

    return SummarizeResponse(
        session_id=session_id,
        summary=summary,
        key_tickers=tickers,
        key_topics=topics,
    )


def _agent_job_session_id(row: dict[str, Any]) -> str | None:
    payload = row.get("payload_json") if isinstance(row, dict) else None
    if isinstance(payload, dict):
        session_id = payload.get("session_id")
        if isinstance(session_id, str) and session_id:
            return session_id
    return None


def _active_agent_chat_session_ids() -> set[str]:
    from api.job_queue import list_active_jobs

    active: set[str] = set()
    for row in list_active_jobs():
        if str(row.get("job_type") or "") != "agent_chat_turn":
            continue
        sid = _agent_job_session_id(row)
        if sid:
            active.add(sid)
    return active


@router.get("/memory/sessions", response_model=SessionHistoryPage | list[SessionListItem])
def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    q: str = Query(default="", max_length=200),
    cursor: str | None = Query(default=None, max_length=2048),
    paginated: bool = False,
):
    """Search nonempty sessions, with optional cursor pagination."""
    try:
        rows = memory_db.list_sessions(limit=limit + int(paginated), query=q, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    next_cursor = memory_db.session_history_cursor(rows[limit - 1]) if len(rows) > limit else None
    active_sessions = _active_agent_chat_session_ids()
    sessions = [SessionListItem(**{**r, "has_active_job": r["session_id"] in active_sessions}) for r in rows[:limit]]
    return SessionHistoryPage(sessions=sessions, next_cursor=next_cursor) if paginated else sessions


@router.get("/memory/sessions/{session_id}/export", response_class=PlainTextResponse)
def export_session(session_id: str):
    """Export the latest saved branch as Markdown without generating any content."""
    session = memory_db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    title = session.get("title") or "Untitled conversation"
    messages = session.get("transcript") or []
    sections = [f"# {title}"]
    for message in message_path(messages, latest_leaf_id(messages)):
        role = "Stan" if message.get("role") == "assistant" else "User"
        sections.append(f"## {role}\n\n{message.get('content') or ''}")
        sources = message.get("sources") or []
        links = [
            f"- [{source.get('title') or source['url']}]({source['url']})" for source in sources if source.get("url")
        ]
        if links:
            sections.append("### Sources\n\n" + "\n".join(links))
    return PlainTextResponse("\n\n".join(sections) + "\n", media_type="text/markdown")


@router.get("/memory/sessions/{session_id}")
def get_session(session_id: str):
    """Load a full session including transcript and any active agent job metadata."""
    session = memory_db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    from api.job_queue import list_active_jobs

    active_jobs: list[dict[str, Any]] = []
    for row in list_active_jobs():
        if str(row.get("job_type") or "") != "agent_chat_turn":
            continue
        if _agent_job_session_id(row) != session_id:
            continue
        payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
        active_jobs.append(
            {
                "job_id": row.get("job_id"),
                "status": row.get("status"),
                "client_turn_id": payload.get("client_turn_id") if isinstance(payload, dict) else None,
            }
        )
    # Direct streams have no durable job. Their lease survives reads from other API
    # processes and expires after a crash; generator cleanup handles normal disconnects.
    live_turn_ids = {job["client_turn_id"] for job in active_jobs if job["client_turn_id"]}
    for msg in session.get("transcript") or []:
        if not (isinstance(msg, dict) and msg.get("role") == "assistant" and msg.get("is_streaming")):
            continue
        client_turn_id = msg.get("client_turn_id")
        if client_turn_id in live_turn_ids or stream_lease_active(msg):
            continue
        if isinstance(client_turn_id, str) and client_turn_id:
            current = memory_db.recover_interrupted_turn(
                session_id, client_turn_id, expected_updated_at=msg.get("updated_at")
            )
            if current is not None:
                msg.update(current)
        else:
            msg.update(is_streaming=False, status="stopped")
    return {**session, "active_jobs": active_jobs}


@router.get("/memory/sessions/{session_id}/messages/{message_id}/suggestions")
def get_message_suggestions(session_id: str, message_id: str):
    """The follow-up questions saved under an answer. They are written after the turn's "done", so this is empty at first."""
    return {
        "suggestions": [s.get("text") for s in memory_db.message_suggestions(session_id, message_id) if s.get("text")]
    }


@router.patch("/memory/sessions/{session_id}", response_model=SessionListItem)
def update_session(session_id: str, req: UpdateSessionRequest):
    """Update user-editable session metadata."""
    if req.title is None and req.pinned is None:
        raise HTTPException(status_code=400, detail="Provide a title or pinned status")
    session = None
    try:
        if req.title is not None:
            session = memory_db.rename_session(session_id, req.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if req.pinned is not None:
        session = memory_db.pin_session(session_id, req.pinned)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionListItem(**session)


@router.delete("/memory/sessions/{session_id}")
def delete_session(session_id: str):
    """Delete a session."""
    if session_id in _active_agent_chat_session_ids():
        raise HTTPException(status_code=409, detail="Stop the running conversation before deleting it")
    deleted = memory_db.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "session_id": session_id}


# ---------------------------------------------------------------------------
# Summarization (Haiku)
# ---------------------------------------------------------------------------

_SUMMARIZE_PROMPT = """\
Summarize this investment research conversation in 150-200 words.

Extract:
- Key tickers discussed (as uppercase symbols, e.g. CRWD, AAPL)
- Key topics (2-5 short phrases, e.g. "thesis review", "macro risk", "earnings prep")
- Decisions made or conclusions reached
- Open questions or action items

Be specific about numbers, dates, and conclusions.
Return strict JSON with keys: summary (string), key_tickers (array of strings), key_topics (array of strings).
No markdown, no extra text.

Conversation transcript:
"""


def _summarize_transcript(
    transcript: list[dict[str, Any]],
) -> tuple[str, list[str], list[str]]:
    """Use Haiku to summarize a conversation. Falls back to deterministic extraction."""
    # Build a compact text representation
    lines: list[str] = []
    for msg in transcript:
        role = msg.get("role", "?")
        content = str(msg.get("content", "")).strip()
        if content:
            lines.append(f"[{role}] {content[:2000]}")

    text = "\n".join(lines[-40:])  # Last 40 messages max

    if has_llm_api_key():
        try:
            return _summarize_with_haiku(text)
        except Exception:
            logger.warning("LLM summarization failed, using fallback", exc_info=True)

    return _summarize_deterministic(transcript)


def _summarize_with_haiku(text: str) -> tuple[str, list[str], list[str]]:
    import json as json_mod

    response_text, _citations, _resp = call_llm_text(
        prompt=_SUMMARIZE_PROMPT + text,
        model=MODEL_LOW,
        api_key=None,
        max_tokens=1024,
    )

    if not response_text:
        raise ValueError("Empty LLM response")

    # Parse JSON from response
    parsed = _parse_json(response_text)
    if not isinstance(parsed, dict):
        raise ValueError("Non-dict Haiku response")

    summary = str(parsed.get("summary", "")).strip()
    tickers = [str(t).upper() for t in parsed.get("key_tickers", []) if isinstance(t, str)]
    topics = [str(t) for t in parsed.get("key_topics", []) if isinstance(t, str)]

    if not summary:
        raise ValueError("Empty summary from Haiku")

    return summary, tickers, topics


def _summarize_deterministic(
    transcript: list[dict[str, Any]],
) -> tuple[str, list[str], list[str]]:
    """Fallback: extract tickers and build a basic summary without LLM."""
    import re

    ticker_re = re.compile(r"\b[A-Z][A-Z0-9.]{1,9}\b")
    stop_words = {
        "AND",
        "THE",
        "WITH",
        "FROM",
        "THAT",
        "WHAT",
        "WHICH",
        "SHOW",
        "PORTFOLIO",
        "RISK",
        "EXPOSURE",
        "SIGNAL",
        "SIGNALS",
    }

    all_text = " ".join(str(m.get("content", "")) for m in transcript)
    tickers = sorted(set(ticker_re.findall(all_text)) - stop_words)[:10]

    user_msgs = [str(m.get("content", "")).strip() for m in transcript if m.get("role") == "user"]
    topics = [msg[:80] for msg in user_msgs[:5] if msg]

    msg_count = len(transcript)
    summary = f"Conversation with {msg_count} messages."
    if tickers:
        summary += f" Tickers discussed: {', '.join(tickers[:5])}."
    if user_msgs:
        summary += f" First question: {user_msgs[0][:120]}"

    return summary, tickers, [t[:60] for t in topics]


def _parse_json(text: str) -> Any:
    import json as json_mod

    try:
        return json_mod.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json_mod.loads(text[start : end + 1])
        except Exception:
            pass
    return None
