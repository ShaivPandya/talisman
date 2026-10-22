"""Observe executed chat streams without changing their SSE payloads."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from api.performance import TimingState, current_timings, emit, enabled, timing_context

_current_chat: ContextVar[ChatObservation | None] = ContextVar("performance_chat", default=None)


class ChatObservation:
    def __init__(self):
        self.started = time.perf_counter()
        self.state = current_timings.get() or TimingState(
            scope={"method": "worker", "route_template": "/api/agent/chat"}
        )
        self.first_token_ms: float | None = None
        self.outcome = "cancelled"
        self.terminal = False
        self.round_index: int | None = None
        self.round_started = self.started
        self.round_first_token_ms: float | None = None
        self.buffer = ""
        self.finished = False

    @contextmanager
    def activate(self):
        token = _current_chat.set(self)
        try:
            with timing_context(self.state):
                yield
        finally:
            _current_chat.reset(token)

    def begin_round(self, index: int) -> None:
        self.finish_round("completed")
        self.round_index = index
        self.round_started = time.perf_counter()
        self.round_first_token_ms = None

    def finish_round(self, outcome: str) -> None:
        if self.round_index is not None:
            emit(
                "chat_round",
                round_index=self.round_index,
                outcome=outcome,
                duration_ms=(time.perf_counter() - self.round_started) * 1000,
                first_token_ms=self.round_first_token_ms,
            )
            self.round_index = None

    def feed(self, chunk: str | bytes) -> None:
        self.buffer += chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else chunk
        frames = self.buffer.split("\n\n")
        self.buffer = frames.pop()
        for frame in frames:
            event = None
            data = []
            for line in frame.splitlines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
            try:
                payload = json.loads("\n".join(data)) if data else {}
            except ValueError:
                continue
            if event == "delta" and isinstance(payload, dict) and payload.get("text"):
                now = time.perf_counter()
                if self.first_token_ms is None:
                    self.first_token_ms = (now - self.started) * 1000
                if self.round_index is not None and self.round_first_token_ms is None:
                    self.round_first_token_ms = (now - self.round_started) * 1000
            elif event in {"error", "blocked", "cancelled", "handoff"}:
                self.outcome = "failed" if event == "error" else event
                self.terminal = True
            elif event == "done" and not self.terminal:
                self.outcome = "completed"
                self.terminal = True

    def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        if self.outcome == "handoff":
            return  # The worker's execution owns the turn observation.
        with self.activate():
            self.finish_round(self.outcome)
            emit(
                "chat_turn",
                duration_ms=(time.perf_counter() - self.started) * 1000,
                first_token_ms=self.first_token_ms,
                outcome=self.outcome,
                **self.state.snapshot(),
            )


def observe_chat_response(call):
    observation = ChatObservation()
    if not enabled():
        return call(observation.started)
    try:
        with observation.activate():
            response = call(observation.started)
    except BaseException:
        observation.outcome = "failed"
        observation.finish()
        raise
    original = response.body_iterator

    async def observed():
        try:
            while True:
                with observation.activate():
                    try:
                        chunk = await original.__anext__()
                    except StopAsyncIteration:
                        break
                    try:
                        observation.feed(chunk)
                    except Exception:
                        pass  # An observation must not interrupt the real stream.
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            observation.outcome = "cancelled"
            raise
        except BaseException:
            observation.outcome = "failed"
            raise
        finally:
            try:
                with observation.activate():
                    close = getattr(original, "aclose", None)
                    if close is not None:
                        await close()
            finally:
                observation.finish()

    response.body_iterator = observed()
    return response


def begin_chat_round(index: int) -> None:
    observation = _current_chat.get()
    if observation is not None:
        observation.begin_round(index)


def record_queue_delay(row: dict[str, Any]) -> None:
    if row.get("job_type") != "agent_chat_turn":
        return
    try:
        created = row.get("created_at")
        started = row.get("started_at")
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        if isinstance(started, str):
            started = datetime.fromisoformat(started)
        if isinstance(created, datetime) and isinstance(started, datetime):
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            emit("chat_queue", duration_ms=max(0, (started - created).total_seconds() * 1000))
    except Exception:
        pass
