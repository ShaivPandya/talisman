"""Process-local wakeups backed by one dedicated Postgres LISTEN connection.

Notifications are hints: event cursors and periodic snapshots remain authoritative.
The listener never holds a connection from the request/worker pool.
"""

from __future__ import annotations

import atexit
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from api.job_queue import ACTIVE_STATUSES, postgres_jobs_enabled
from api.postgres import require_database_url

CHANNEL = "talisman_job_events"
RESYNC_SECONDS = 1.0
POLL_FALLBACK_SECONDS = 0.35
_RECENT_JOBS = 512
logger = logging.getLogger(__name__)


@dataclass
class _Signal:
    condition: threading.Condition
    users: int = 0
    latest_seq: int = 0
    cursor: int = 0
    row: dict[str, Any] | None = None
    checked_at: float = 0.0
    generation: int = -1


class _EventHub:
    def __init__(self, dsn: str | None):
        self.dsn = dsn
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.signals: OrderedDict[str, _Signal] = OrderedDict()
        self.generation = 0
        self.ready = dsn is None
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        if dsn is not None:
            self.thread = threading.Thread(target=self._listen, name="job-event-listener", daemon=True)
            self.thread.start()

    def publish(self, job_id: str, seq: int) -> None:
        with self.condition:
            signal = self.signals.get(job_id)
            if signal is not None and seq > signal.latest_seq:
                signal.latest_seq = seq
                signal.condition.notify_all()

    def _set_ready(self, ready: bool) -> None:
        with self.condition:
            self.ready = ready
            self.generation += 1
            for signal in self.signals.values():
                signal.condition.notify_all()
            self.condition.notify_all()

    def _listen(self) -> None:
        import psycopg

        assert self.dsn is not None
        while not self.stop.is_set():
            try:
                with psycopg.connect(
                    self.dsn, autocommit=True, connect_timeout=3, application_name="talisman-job-events"
                ) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    # LISTEN must commit before trusting a snapshot. On reconnect,
                    # invalidate all cached snapshots and wake existing requests.
                    self._set_ready(True)
                    while not self.stop.is_set():
                        for notice in conn.notifies(timeout=1.0):
                            try:
                                job_id, seq = json.loads(notice.payload)
                            except (ValueError, TypeError):
                                continue
                            if isinstance(job_id, str) and type(seq) is int:
                                self.publish(job_id, seq)
            except Exception as exc:
                # Exception messages can contain credentials/connection strings.
                logger.warning("Job event listener unavailable (%s); using polling", type(exc).__name__)
            finally:
                self._set_ready(False)
            self.stop.wait(1.0)

    def close(self) -> None:
        self.stop.set()
        self._set_ready(False)
        if self.thread is not None:
            self.thread.join(timeout=4.0)


class JobEventWatch:
    def __init__(self, hub: _EventHub, signal: _Signal):
        self.hub = hub
        self.signal = signal

    @property
    def generation(self) -> int:
        with self.hub.condition:
            return self.hub.generation

    def cached_job(self, after_seq: int) -> dict[str, Any] | None:
        """Avoid an empty initial query when a client immediately polls again."""
        with self.hub.condition:
            signal = self.signal
            if (
                self.hub.ready
                and signal.generation == self.hub.generation
                and signal.cursor == after_seq
                and signal.latest_seq <= after_seq
                and time.monotonic() - signal.checked_at < RESYNC_SECONDS
                and signal.row is not None
            ):
                return dict(signal.row)
            return None

    def record(
        self, row: dict[str, Any], cursor: int, generation: int, *, complete_page: bool = True, has_events: bool = False
    ) -> None:
        with self.hub.condition:
            signal = self.signal
            # Only keep small active snapshots; terminal results can be large.
            signal.row = dict(row) if complete_page and row.get("status") in ACTIVE_STATUSES else None
            signal.cursor = cursor
            signal.checked_at = time.monotonic()
            signal.generation = generation if self.hub.ready else -1
            # Only event-derived cursors advance the watermark. A caller may
            # supply an after_seq beyond the end of the durable log.
            if has_events and cursor > signal.latest_seq:
                signal.latest_seq = cursor
                signal.condition.notify_all()

    def wait(self, after_seq: int, timeout: float) -> None:
        with self.hub.condition:
            if not self.hub.ready:
                self.signal.condition.wait(timeout=min(timeout, POLL_FALLBACK_SECONDS))
                return
            remaining = max(0.0, RESYNC_SECONDS - (time.monotonic() - self.signal.checked_at))
            self.signal.condition.wait_for(
                lambda: self.signal.latest_seq > after_seq or self.signal.generation != self.hub.generation,
                timeout=min(timeout, remaining),
            )


_hubs: dict[str | None, _EventHub] = {}
_hubs_lock = threading.Lock()


@contextmanager
def watch_job_events(job_id: str) -> Iterator[JobEventWatch]:
    dsn = require_database_url() if postgres_jobs_enabled() else None
    with _hubs_lock:
        hub = _hubs.get(dsn)
        if hub is None:
            hub = _EventHub(dsn)
            _hubs[dsn] = hub
    with hub.condition:
        signal = hub.signals.setdefault(job_id, _Signal(threading.Condition(hub.lock)))
        signal.users += 1
    try:
        yield JobEventWatch(hub, signal)
    finally:
        with hub.condition:
            signal.users -= 1
            hub.signals.move_to_end(job_id)
            # Bound recent inactive cursors without evicting live subscribers.
            for key in list(hub.signals):
                if len(hub.signals) <= _RECENT_JOBS:
                    break
                if hub.signals[key].users == 0:
                    del hub.signals[key]


def publish_local_job_event(job_id: str, seq: int) -> None:
    with _hubs_lock:
        hub = _hubs.get(None)
    if hub is not None:
        hub.publish(job_id, seq)


def clear_local_job_event_watches() -> None:
    with _hubs_lock:
        hub = _hubs.get(None)
    if hub is not None:
        with hub.condition:
            for signal in hub.signals.values():
                signal.latest_seq = 0
                signal.row = None
                signal.condition.notify_all()
            hub.generation += 1
            hub.condition.notify_all()


def close_job_event_listeners() -> None:
    with _hubs_lock:
        hubs = list(_hubs.values())
        _hubs.clear()
    for hub in hubs:
        hub.close()


atexit.register(close_job_event_listeners)
