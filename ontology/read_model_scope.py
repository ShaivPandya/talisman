"""Defer ontology read-model refreshes to one per HTTP request.

An approval-gated action refreshes the read models after the proposal and
again after the approval. Inside a request scope, ``refresh()`` only marks the
scope pending; the scope refreshes once, before the response starts or before
anything in the request reads a read model, so the request always sees its
own writes.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextvars import ContextVar, Token
from typing import Any

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


class DeferredRefresh:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._refresh: Callable[[], None] | None = None

    def request(self, refresh: Callable[[], None]) -> None:
        with self._lock:
            self._refresh = refresh

    @property
    def pending(self) -> bool:
        return self._refresh is not None

    def flush(self) -> None:
        # Hold the lock while refreshing so a concurrent reader in the same request waits for fresh data.
        with self._lock:
            refresh, self._refresh = self._refresh, None
            if refresh is not None:
                refresh()


_current: ContextVar[DeferredRefresh | None] = ContextVar("ontology_read_model_refresh", default=None)


def current_deferred_refresh() -> DeferredRefresh | None:
    return _current.get()


def begin_deferred_refresh() -> tuple[DeferredRefresh, Token[DeferredRefresh | None]]:
    deferred = DeferredRefresh()
    return deferred, _current.set(deferred)


def end_deferred_refresh(token: Token[DeferredRefresh | None]) -> None:
    _current.reset(token)


def flush_deferred_refresh() -> None:
    """Apply this request's pending refresh before reading a read model."""
    deferred = _current.get()
    if deferred is not None and deferred.pending:
        deferred.flush()


def _uses_postgres_state() -> bool:
    from api.postgres import use_postgres_state

    try:
        return use_postgres_state()
    except RuntimeError:
        return False


class DeferredReadModelRefreshMiddleware:
    """Run each request's ontology read-model refreshes once, before the response starts."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not _uses_postgres_state():
            # Outside Postgres, command services skip the refresh themselves; keep that behaviour.
            await self.app(scope, receive, send)
            return

        deferred, token = begin_deferred_refresh()

        async def send_after_refresh(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start" and deferred.pending:
                await run_in_threadpool(deferred.flush)
            await send(message)

        try:
            await self.app(scope, receive, send_after_refresh)
        finally:
            try:
                # Writes made while streaming, in background tasks or before an error still need applying.
                if deferred.pending:
                    await run_in_threadpool(deferred.flush)
            except Exception:
                logger.exception("ontology read model refresh failed after the response")
            finally:
                end_deferred_refresh(token)
