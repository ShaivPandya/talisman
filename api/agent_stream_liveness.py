"""Database-visible liveness for chat streams that have no durable job."""

from __future__ import annotations

import logging
import threading
from contextvars import copy_context
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)
STREAM_LEASE_SECONDS = 45.0
STREAM_HEARTBEAT_SECONDS = 10.0


def stream_lease_metadata() -> dict[str, Any]:
    return {"stream_lease_expires_at": (datetime.now(UTC) + timedelta(seconds=STREAM_LEASE_SECONDS)).isoformat()}


def stream_lease_active(message: dict[str, Any]) -> bool:
    try:
        expires_at = datetime.fromisoformat(message.get("stream_lease_expires_at") or "")
        return expires_at > datetime.now(UTC)
    except (ValueError, TypeError):
        return False


class DirectStreamLease:
    """Renew independently of SSE frames, including during a blocked provider/tool call."""

    def __init__(self, session_id: str, client_turn_id: str):
        self.session_id = session_id
        self.client_turn_id = client_turn_id
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=copy_context().run,
            args=(self._heartbeat,),
            name=f"chat-stream-heartbeat-{client_turn_id}",
            daemon=True,
        )

    def renew(self) -> None:
        from api import memory_db

        try:
            memory_db.update_assistant_message(
                self.session_id, self.client_turn_id, stream_lease_metadata(), only_streaming=True
            )
        except Exception:
            # A transient write failure must not interrupt a healthy response.
            logger.warning("Chat stream heartbeat failed session_id=%s", self.session_id, exc_info=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _heartbeat(self) -> None:
        while not self._stop.wait(STREAM_HEARTBEAT_SECONDS):
            self.renew()
