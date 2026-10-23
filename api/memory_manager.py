"""
Rolling memory manager for agent chat.

Replaces the "full transcript every turn" pattern with:
  - A verbatim window of recent messages
  - A rolling summary of older turns (incrementally updated via the configured low-tier LLM)
  - Retrieval-augmented context from past sessions / theses

The frontend sends only the new message + session_id; this module
assembles the optimal context window for the configured LLM.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from contextvars import copy_context
from typing import Any

from api import memory_db
from api.agent_governance import estimate_tokens
from api.conversation_messages import TurnLineage, has_forks, message_path, resolve_turn_lineage
from api.tool_result_memory import tool_memory_context

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

VERBATIM_TOKEN_BUDGET = 6000  # estimated tokens, independent of message count
RETRIEVAL_TOP_K = 3  # semantic retrieval hits to include
TURN_MESSAGE_COUNT = 2  # a finished turn adds one user and one assistant message

# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def _include_in_verbatim(msg: dict[str, Any]) -> bool:
    """Exclude in-progress assistant placeholders, and turns stopped before any text, from LLM context."""
    if msg.get("role") == "assistant" and (msg.get("is_streaming") or not str(msg.get("content") or "").strip()):
        return False
    return True


def _verbatim_start(messages: list[dict[str, Any]]) -> int:
    """Return the start of the most recent whole-message suffix within budget."""
    used = 0
    start = len(messages)
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not _include_in_verbatim(message):
            continue
        cost = estimate_tokens({"role": message["role"], "content": message.get("content", "")})
        if used + cost > VERBATIM_TOKEN_BUDGET:
            break
        used += cost
        start = index
    return start


def _summary_usable(session: dict[str, Any], branch: list[dict[str, Any]]) -> bool:
    """Whether the session's rolling summary describes ``branch``, the messages a turn continues from.

    A summary records the last message it covers. A conversation with branches can only use it
    when that message is on the branch; one written before branches existed is trusted only while
    the conversation has none.
    """
    if not session.get("rolling_summary"):
        return False
    through = session.get("rolling_summary_through_id")
    if through:
        return any(m["id"] == through for m in branch)
    return not has_forks(session.get("server_messages") or [])


def build_conversation_context(
    session_id: str | None,
    new_user_message: str,
    *,
    enable_retrieval: bool = True,
    client_turn_id: str | None = None,
    session: dict[str, Any] | None = None,
    lineage: TurnLineage | None = None,
) -> tuple[list[dict[str, object]], str]:
    """Build the ``messages`` list for a Claude API call.

    Returns ``(conversation, session_id)`` where *conversation* contains:
      1. An optional context preamble (rolling summary + retrieval hits)
      2. Recent tool facts and a token-budgeted suffix of the verbatim messages of the branch the turn continues
      3. The new user message

    Pass *session* when the turn already loaded it, to skip a second read, and *lineage* to
    continue a branch other than the latest. The caller should pass *conversation* directly
    to ``client.messages.stream()``.
    """
    if session is None:
        session = memory_db.get_or_create_session(session_id)
    sid = session["session_id"]
    server_msgs: list[dict[str, Any]] = session["server_messages"]

    # The branch this turn continues, without this turn's own persisted user message and placeholder.
    history = (lineage or resolve_turn_lineage(server_msgs, client_turn_id=client_turn_id)).history(server_msgs)
    rolling_summary: str | None = session.get("rolling_summary") if _summary_usable(session, history) else None
    recent = [m for m in history[_verbatim_start(history) :] if _include_in_verbatim(m)]

    # --- Build optional context preamble ---
    preamble_parts: list[str] = []

    if rolling_summary:
        preamble_parts.append("## Conversation History (summarised)\n" + rolling_summary)

    tool_context = tool_memory_context(history)
    if tool_context:
        preamble_parts.append(tool_context)

    if enable_retrieval:
        retrieval_context = _retrieve_relevant(new_user_message)
        if retrieval_context:
            preamble_parts.append(retrieval_context)

    # --- Assemble conversation ---
    conversation: list[dict[str, object]] = []

    if preamble_parts:
        context_text = "\n\n".join(preamble_parts)
        # Inject as a user/assistant pair so it doesn't confuse role alternation
        conversation.append(
            {
                "role": "user",
                "content": f"[Context from earlier in this conversation and past research]\n\n{context_text}",
            }
        )
        conversation.append(
            {"role": "assistant", "content": "Understood — I have this context available and will use it as needed."}
        )

    # Verbatim recent messages
    for msg in recent:
        conversation.append({"role": msg["role"], "content": msg["content"]})

    conversation.append({"role": "user", "content": new_user_message})

    return conversation, sid


def messages_before_turn(
    session: dict[str, Any], client_turn_id: str | None, lineage: TurnLineage | None = None
) -> int:
    """Count the messages on the turn's branch that precede its own messages."""
    messages = session.get("server_messages") or []
    if lineage is not None:
        return len(lineage.history(messages))
    if client_turn_id:
        for index, msg in enumerate(messages):
            if isinstance(msg, dict) and str(msg.get("client_turn_id")) == client_turn_id:
                return index
    return len(messages)


# ---------------------------------------------------------------------------
# Post-turn finalization
# ---------------------------------------------------------------------------


def begin_turn(
    session_id: str,
    user_message: dict[str, Any],
    assistant_placeholder: dict[str, Any],
) -> None:
    """Persist user message and streaming assistant placeholder at turn start."""
    client_turn_id = str(user_message.get("client_turn_id") or "")
    if not client_turn_id:
        return
    try:
        placeholder = {
            **assistant_placeholder,
            "is_streaming": assistant_placeholder.get("is_streaming", True),
        }
        memory_db.begin_turn(session_id, user_message, placeholder)
    except Exception:
        logger.exception("Failed to begin turn for session %s", session_id)


def begin_turn_async(
    session_id: str,
    user_message: dict[str, Any],
    assistant_placeholder: dict[str, Any],
) -> None:
    t = threading.Thread(
        target=begin_turn,
        args=(session_id, user_message, assistant_placeholder),
        daemon=True,
    )
    t.start()


def save_partial_turn(
    session_id: str, client_turn_id: str | None, content: str, *, metadata: dict[str, Any] | None = None
) -> None:
    """Save the text streamed so far. Applies only while the turn is still streaming."""
    if not client_turn_id:
        return
    try:
        memory_db.update_assistant_message(
            session_id, client_turn_id, {**(metadata or {}), "content": content}, only_streaming=True
        )
    except Exception:
        logger.debug("Failed to save partial turn for session %s", session_id, exc_info=True)


def save_partial_turn_async(
    session_id: str, client_turn_id: str | None, content: str, *, metadata: dict[str, Any] | None = None
) -> None:
    t = threading.Thread(
        target=copy_context().run,
        args=(save_partial_turn, session_id, client_turn_id, content),
        kwargs={"metadata": metadata},
        daemon=True,
    )
    t.start()


def complete_turn(
    session_id: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
) -> None:
    """Finalize a turn, using in-place update when incremental persistence exists.

    Rolling summarization is not done here: it runs in the turn's follow-up job
    (``api.agent_turn_followup``) after the client has the answer.
    """
    client_turn_id = str(user_message.get("client_turn_id") or assistant_message.get("client_turn_id") or "")
    final_assistant = {**assistant_message, "is_streaming": False, "status": "complete"}
    try:
        if client_turn_id:
            # Completes the begun turn in place, or appends it when it was never begun.
            total = memory_db.complete_turn_messages(
                session_id,
                client_turn_id,
                user_message,
                final_assistant,
            )
        else:
            total = memory_db.append_messages(session_id, [user_message, final_assistant])
    except Exception:
        logger.exception("Failed to complete turn for session %s", session_id)
        return

    _ensure_session_title(session_id, user_message, final_assistant, total)


def complete_turn_async(
    session_id: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
) -> None:
    t = threading.Thread(
        target=complete_turn,
        args=(session_id, user_message, assistant_message),
        daemon=True,
    )
    t.start()


def fail_turn(
    session_id: str,
    client_turn_id: str | None,
    *,
    status: str = "stopped",
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """End a still-streaming turn as ``stopped`` or ``failed``. A finished turn is left alone."""
    if not client_turn_id:
        return
    try:
        memory_db.fail_turn(session_id, client_turn_id, status=status, content=content, metadata=metadata)
    except Exception:
        logger.debug("Failed to mark turn failed for session %s", session_id, exc_info=True)


def fail_turn_async(
    session_id: str,
    client_turn_id: str | None,
    *,
    status: str = "stopped",
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    t = threading.Thread(
        target=fail_turn,
        args=(session_id, client_turn_id),
        kwargs={"status": status, "content": content, "metadata": metadata},
        daemon=True,
    )
    t.start()


def finalize_turn(
    session_id: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
) -> None:
    """Persist the turn. Rolling summarization runs later, in the turn's follow-up job."""
    complete_turn(session_id, user_message, assistant_message)


def finalize_turn_async(
    session_id: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
) -> None:
    """Fire-and-forget wrapper that runs finalize_turn in a daemon thread."""
    t = threading.Thread(
        target=finalize_turn,
        args=(session_id, user_message, assistant_message),
        daemon=True,
    )
    t.start()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _retrieve_relevant(query: str) -> str | None:
    """Run semantic retrieval for past sessions / theses. Non-blocking."""
    try:
        from api.retrieval import search as retrieval_search

        hits = retrieval_search(
            query=query,
            doc_types=["conversation_summary", "thesis", "news_digest"],
            top_k=RETRIEVAL_TOP_K,
        )
        if not hits:
            return None

        lines = ["## Relevant Past Research"]
        for h in hits:
            ticker = h.get("ticker") or ""
            score = h.get("relevance_score", 0.0)
            snippet = h.get("content_snippet", "")
            lines.append(f"- [{h['doc_type']}] {ticker} (score={score:.2f}): {snippet}")
        return "\n".join(lines)
    except Exception:
        logger.debug("Retrieval failed, skipping", exc_info=True)
        return None


def _ensure_session_title(
    session_id: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
    total_messages: int,
) -> None:
    """Set a quick deterministic title, then schedule first-turn LLM refinement."""
    user_text = str(user_message.get("content") or "")
    memory_db.set_deterministic_title_if_missing(session_id, user_text)

    if total_messages > 2:
        return
    meta = memory_db.get_session_title_metadata(session_id)
    if not meta or meta.get("title_source") != "deterministic":
        return
    _refine_session_title_async(session_id, user_message, assistant_message)


def _refine_session_title_async(
    session_id: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
) -> None:
    t = threading.Thread(
        target=_refine_session_title,
        args=(session_id, user_message, assistant_message),
        daemon=True,
    )
    t.start()


def _refine_session_title(
    session_id: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
) -> None:
    try:
        meta = memory_db.get_session_title_metadata(session_id)
        if not meta or meta.get("title_source") != "deterministic":
            return

        from llm_utils import MODEL_LOW, call_llm_text, has_llm_api_key

        if not has_llm_api_key():
            return

        user_text = str(user_message.get("content") or "").strip()
        assistant_text = str(assistant_message.get("content") or "").strip()
        if not user_text:
            return

        prompt = f"""\
Generate a concise title for this investment research chat.

Rules:
- 2 to 6 words.
- 80 characters maximum.
- Preserve important tickers.
- Return only the title, with no quotes, labels, markdown, or punctuation wrapper.

User:
{user_text[:1500]}

Assistant:
{assistant_text[:1500]}
"""
        response_text, _citations, _resp = call_llm_text(
            prompt=prompt,
            model=MODEL_LOW,
            api_key=None,
            max_tokens=64,
        )
        title = _clean_generated_title(response_text)
        if not title:
            return
        memory_db.update_generated_title(session_id, title)
    except Exception:
        logger.debug("Failed to refine conversation title for session %s", session_id, exc_info=True)


def _clean_generated_title(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.splitlines()[0].strip()
    text = re.sub(r"^title\s*:\s*", "", text, flags=re.IGNORECASE).strip()
    text = text.strip(" \"'`*_-.")
    if not text:
        return None
    try:
        return memory_db.normalize_session_title(text)
    except ValueError:
        fallback = memory_db.deterministic_title_from_text(text)
        if not fallback:
            return None
        try:
            return memory_db.normalize_session_title(fallback)
        except ValueError:
            return None


def _turn_branch(messages: list[dict[str, Any]], client_turn_id: str | None) -> list[dict[str, Any]]:
    """The messages from the root through a finished turn's answer, or all of them when it isn't found."""
    if client_turn_id:
        for message in reversed(messages):
            if message.get("role") == "assistant" and str(message.get("client_turn_id")) == client_turn_id:
                return message_path(messages, message["id"])
    return messages


def summarize_departed_messages(
    session_id: str, *, messages_before_turn: int, client_turn_id: str | None = None
) -> bool:
    """Fold the messages a finished turn pushed out of the verbatim window into the summary.

    Only those messages go to the LLM, since everything older is already summarized.
    The first summary covers every message older than the window. The turn's branch only
    appends, so this can run any time after the turn. A summary that covers a different
    branch is replaced by one built from the start of this one.
    Returns True when the summary changed.
    """
    total = messages_before_turn + TURN_MESSAGE_COUNT

    from llm_utils import has_llm_api_key

    if not has_llm_api_key():
        logger.debug("No valid API key for rolling summarization")
        return False

    from api.routers.memory import _summarize_with_haiku

    # A second pass only happens when another summarizer changed the summary meanwhile.
    for _attempt in range(2):
        session = memory_db.get_or_create_session(session_id)
        branch = _turn_branch(session["server_messages"], client_turn_id)
        messages = branch[:total]
        window_start = _verbatim_start(messages)
        stored_summary = session.get("rolling_summary") or ""
        through = session.get("rolling_summary_through_id")
        # Where the stored summary leaves off on this branch, or None when it belongs to another one.
        covered: int | None = None
        if stored_summary and through:
            covered = next((i + 1 for i, m in enumerate(messages) if m.get("id") == through), None)
        elif stored_summary and not has_forks(session["server_messages"]):
            covered = _verbatim_start(messages[:messages_before_turn])
        existing_summary = stored_summary if covered is not None else ""
        departed: list[dict[str, Any]] = messages[covered or 0 : window_start]

        lines: list[str] = []
        if existing_summary:
            lines.append(f"[Previous summary]\n{existing_summary}\n")
        lines.append("[New messages to incorporate]")
        new_lines = 0
        for msg in departed:
            if not _include_in_verbatim(msg):
                continue
            role = msg.get("role", "?")
            content = str(msg.get("content", "")).strip()
            if content:
                lines.append(f"[{role}] {content[:2000]}")
                new_lines += 1
        if not new_lines:
            return False

        text = "\n".join(lines[-60:])  # cap input
        summary, tickers, _topics = _summarize_with_haiku(text)
        through_id = departed[-1]["id"] if departed[-1].get("id") else None
        if memory_db.update_rolling_summary(session_id, summary, expected=stored_summary, through_id=through_id):
            _index_rolling_summary(session_id, summary, tickers)
            return True
    logger.warning("Rolling summary for session %s kept changing; skipped this turn's messages", session_id)
    return False


def _index_rolling_summary(session_id: str, summary: str, tickers: list[str]) -> None:
    """Index the summary for retrieval in later sessions."""
    try:
        from api.retrieval import index_document

        ticker_str = ", ".join(tickers) if tickers else ""
        index_document(
            doc_type="conversation_summary",
            content=f"Tickers: {ticker_str}\n\n{summary}" if ticker_str else summary,
            ticker=tickers[0] if tickers else None,
            doc_id=f"rolling-{session_id}",
        )
    except Exception:
        logger.debug("Failed to index rolling summary", exc_info=True)
