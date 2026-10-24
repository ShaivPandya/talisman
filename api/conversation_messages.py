"""Portable message records shared by the memory store and legacy imports."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

MESSAGE_COLUMNS = (
    "id",
    "session_id",
    "parent_id",
    "position",
    "role",
    "status",
    "content_parts",
    "client_turn_id",
    "created_at",
    "updated_at",
    "metadata_json",
)

CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES conversation_sessions(session_id) ON DELETE CASCADE,
    parent_id TEXT,
    position INTEGER NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('streaming', 'complete', 'stopped', 'failed')),
    content_parts TEXT NOT NULL DEFAULT '[]',
    client_turn_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (session_id, position),
    UNIQUE (session_id, id),
    FOREIGN KEY (session_id, parent_id) REFERENCES conversation_messages(session_id, id)
)
"""
CREATE_TURN_INDEX = """
CREATE INDEX IF NOT EXISTS idx_conversation_messages_turn
ON conversation_messages(session_id, client_turn_id, role, position)
"""


def legacy_messages(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Prefer server memory, with the same transcript fallback as the old writer.

    Refuse malformed nonempty blobs instead of silently discarding history when
    the migration drops the old columns.
    """
    errors = []
    for field in ("server_messages", "transcript"):
        raw = session.get(field)
        if not raw:
            continue
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(value, list) or any(not isinstance(m, dict) for m in value):
                raise ValueError(f"Invalid {field}")
            if value:
                return value
        except (ValueError, TypeError) as exc:
            errors.append(exc)
    if errors:
        raise ValueError(f"Cannot migrate conversation {session.get('session_id')}") from errors[0]
    return []


def _parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    parts = [dict(p) for p in message.get("content_parts", []) if isinstance(p, dict)]
    if "content" in message:
        parts = [p for p in parts if p.get("type") != "text"]
        parts.insert(0, {"type": "text", "text": str(message.get("content") or "")})
    for kind, keys in (
        ("tool_call", ("tool_calls", "toolCalls")),
        ("source", ("sources",)),
        ("attachment", ("attachments",)),
        ("thinking", ("thinking",)),
        ("narration", ("narration",)),
        ("chart", ("charts",)),
        ("proposal", ("proposals",)),
        ("suggestion", ("suggestions",)),
    ):
        for key in keys:
            if key not in message:
                continue
            parts = [p for p in parts if p.get("type") != kind]
            parts.extend({"type": kind, "data": item} for item in message[key] or [])
            break
    return parts


def message_record(
    session_id: str,
    message: dict[str, Any],
    position: int,
    parent_id: str | None,
    *,
    legacy: bool = False,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    status = message.get("status")
    streaming = message.get("is_streaming", message.get("isStreaming", False))
    if status in {"cancelled", "canceled", "interrupted"}:
        status = "stopped"
    if status not in {"streaming", "complete", "stopped", "failed"}:
        status = "streaming" if streaming else "complete"
    # Old rows may have a stale streaming flag alongside a valid terminal state.
    if legacy and status == "streaming":
        status = "stopped"
    created_at = message.get("created_at")
    timestamp = message.get("timestamp")
    if not created_at and isinstance(timestamp, (int, float)):
        created_at = datetime.fromtimestamp(
            timestamp / 1000 if timestamp > 100_000_000_000 else timestamp, UTC
        ).isoformat()
    identity = message.get("id") or str(uuid.uuid5(uuid.NAMESPACE_URL, f"talisman:{session_id}:{position}"))
    reserved = {
        "id",
        "session_id",
        "parent_id",
        "position",
        "role",
        "status",
        "content_parts",
        "content",
        "client_turn_id",
        "clientTurnId",
        "created_at",
        "updated_at",
        "is_streaming",
        "isStreaming",
        "tool_calls",
        "toolCalls",
        "sources",
        "attachments",
        "thinking",
        "narration",
        "charts",
        "proposals",
        "suggestions",
    }
    return {
        "id": identity,
        "session_id": session_id,
        "parent_id": message.get("parent_id", parent_id),
        "position": position,
        "role": message.get("role", "user"),
        "status": status,
        "content_parts": json.dumps(_parts(message), default=str),
        "client_turn_id": message.get("client_turn_id") or message.get("clientTurnId"),
        "created_at": created_at or now,
        "updated_at": message.get("updated_at") or now,
        "metadata_json": json.dumps({k: v for k, v in message.items() if k not in reserved}, default=str),
    }


def record_message(row: Any) -> dict[str, Any]:
    parts = json.loads(row["content_parts"])
    message = {
        **json.loads(row["metadata_json"]),
        "id": row["id"],
        "parent_id": row["parent_id"],
        "role": row["role"],
        "status": row["status"],
        "is_streaming": row["status"] == "streaming",
        "content_parts": parts,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "content": "".join(str(p.get("text") or "") for p in parts if p.get("type") == "text"),
    }
    if row["client_turn_id"]:
        message["client_turn_id"] = row["client_turn_id"]
    for kind, key in (
        ("tool_call", "tool_calls"),
        ("source", "sources"),
        ("attachment", "attachments"),
        ("thinking", "thinking"),
        ("narration", "narration"),
        ("chart", "charts"),
        ("proposal", "proposals"),
        ("suggestion", "suggestions"),
    ):
        message[key] = [p.get("data", {}) for p in parts if p.get("type") == kind]
    # Older callers use the camelCase spelling.
    message["toolCalls"] = message["tool_calls"]
    return message


def message_path(messages: list[dict[str, Any]], leaf_id: str | None) -> list[dict[str, Any]]:
    """The chain of messages from the root down to ``leaf_id``; empty when it names no message."""
    by_id = {m["id"]: m for m in messages if m.get("id")}
    path: list[dict[str, Any]] = []
    seen: set[str] = set()
    node = by_id.get(leaf_id) if leaf_id else None
    while node is not None and node["id"] not in seen:
        seen.add(node["id"])
        path.append(node)
        parent_id = node.get("parent_id")
        node = by_id.get(parent_id) if parent_id else None
    path.reverse()
    return path


def latest_leaf_id(messages: list[dict[str, Any]]) -> str | None:
    """The newest message nothing replies to: the branch a turn continues when it names no parent."""
    parents = {m.get("parent_id") for m in messages}
    return next((m["id"] for m in reversed(messages) if m.get("id") and m["id"] not in parents), None)


def has_forks(messages: list[dict[str, Any]]) -> bool:
    """True when some message (or the root) has more than one child."""
    seen: set[str | None] = set()
    for message in messages:
        parent_id = message.get("parent_id")
        if parent_id in seen:
            return True
        seen.add(parent_id)
    return False


@dataclass(frozen=True)
class TurnLineage:
    """Where a chat turn attaches in the message tree.

    ``explicit`` is False when the request names no parent: the turn then continues from the
    latest leaf. ``reused_user`` is the stored user message a regenerated answer replies to.
    """

    parent_id: str | None = None
    explicit: bool = False
    reused_user: dict[str, Any] | None = None

    def history(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The messages before this turn's user message, root first."""
        if any(not m.get("id") for m in messages):  # no tree to follow: a plain list of messages
            return list(messages)
        if self.explicit:
            return message_path(messages, self.parent_id)
        return message_path(messages, latest_leaf_id(messages))


def resolve_turn_lineage(
    messages: list[dict[str, Any]],
    *,
    user_message_id: str | None = None,
    client_turn_id: str | None = None,
    parent_message_id: str | None = None,
    edit_of_message_id: str | None = None,
    regenerate_of_message_id: str | None = None,
) -> TurnLineage:
    """Work out a turn's parent from its request. Ids that name no stored message are ignored."""
    by_id = {m["id"]: m for m in messages if m.get("id")}

    def stored(message_id: str | None, role: str) -> dict[str, Any] | None:
        message = by_id.get(message_id) if message_id else None
        return message if message is not None and message.get("role") == role else None

    answer = stored(regenerate_of_message_id, "assistant")
    prompt = stored(answer.get("parent_id"), "user") if answer else None
    if prompt is not None:
        return TurnLineage(prompt.get("parent_id"), True, prompt)
    # A retried turn: its user message is already stored, so its parent is known.
    begun = next(
        (
            m
            for m in messages
            if client_turn_id and m.get("role") == "user" and str(m.get("client_turn_id")) == client_turn_id
        ),
        None,
    )
    for message in (stored(user_message_id, "user"), begun, stored(edit_of_message_id, "user")):
        if message is not None:
            return TurnLineage(message.get("parent_id"), True)
    if parent_message_id in by_id:
        return TurnLineage(parent_message_id, True)
    return TurnLineage()


def sources_from(value: Any) -> list[dict[str, Any]]:
    """Extract citations emitted by providers and tools, retaining URL/title metadata."""
    found: dict[str, dict[str, Any]] = {}

    def visit(node: Any, source: bool = False) -> None:
        if isinstance(node, str):
            if node.lstrip().startswith(("{", "[")):
                try:
                    visit(json.loads(node), source)
                except ValueError:
                    pass
        elif isinstance(node, list):
            for item in node:
                visit(item, source)
        elif isinstance(node, dict):
            url = node.get("url")
            if isinstance(url, str) and (source or node.get("type") in {"url_citation", "web_search_result"}):
                found[url] = {**found.get(url, {}), **node}
            for key, item in node.items():
                visit(item, source or key in {"sources", "citations", "url_citation"})

    visit(value)
    return list(found.values())
