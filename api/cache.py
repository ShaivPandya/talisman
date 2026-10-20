"""
TTL caching for FastAPI route handlers.

TTL cache behaviour:
- short_cache: 300s  — live market data (prices, breadth, signals)
- long_cache:  3600s — slow/external scrapes (central banks, industry)
- daily_cache: 86400s — low-frequency macro/reference data (country dashboard)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cachetools import TLRUCache

from api.performance import count, measure

logger = logging.getLogger("uvicorn.error")

SHORT_CACHE_TTL = 300
LONG_CACHE_TTL = 3600
DAILY_CACHE_TTL = 24 * 60 * 60
_READ_WAIT_TIMEOUT_S = 120


@dataclass(slots=True)
class _CacheEntry:
    value: Any
    expires_at: float
    created_at: datetime


@dataclass(slots=True)
class _KeyState:
    io_lock: threading.Lock = field(default_factory=threading.Lock)
    generation: int = 0
    users: int = 0


class ApiCache(TLRUCache[str, _CacheEntry]):
    """Bounded cache whose entries retain their original expiry after promotion."""

    def __init__(self, maxsize: int, ttl: float, timer: Callable[[], float] = time.monotonic):
        super().__init__(maxsize, ttu=lambda _key, entry, _now: entry.expires_at, timer=timer)
        self._ttl = ttl
        self._key_states: dict[str, _KeyState] = {}

    @property
    def ttl(self) -> float:
        return self._ttl


short_cache = ApiCache(maxsize=128, ttl=SHORT_CACHE_TTL)
long_cache = ApiCache(maxsize=128, ttl=LONG_CACHE_TTL)
daily_cache = ApiCache(maxsize=128, ttl=DAILY_CACHE_TTL)
_lock = threading.Lock()
_singleflight_lock = threading.Lock()
_invalidation_lock = threading.Lock()
_writes_drained = threading.Condition(_lock)
_cache_epoch = 0
_clearing = False
_active_writes = 0
_MISSING = object()


@dataclass(frozen=True, slots=True)
class _CacheToken:
    epoch: int
    generation: int


@dataclass(slots=True)
class _SingleFlightState:
    event: threading.Event
    value: object = _MISSING
    error: Exception | None = None
    backend: str = "memory"
    refresh_requested: bool = False
    complete: bool = False


_singleflight_by_key: dict[tuple[int, str, str, _CacheToken], _SingleFlightState] = {}


@contextmanager
def _key_operation(cache: ApiCache, key: str) -> Iterator[tuple[_KeyState, _CacheToken]]:
    with _lock:
        state = cache._key_states.get(key)
        if state is None:
            state = cache._key_states[key] = _KeyState()
        state.users += 1
        token = _CacheToken(_cache_epoch, state.generation)
    try:
        yield state, token
    finally:
        with _lock:
            state.users -= 1
            if not state.users:
                del cache._key_states[key]


def _token_current(state: _KeyState, token: _CacheToken) -> bool:
    """Called with _lock held; stale work may finish but cannot repopulate caches."""
    return token.epoch == _cache_epoch and token.generation == state.generation


@contextmanager
def _flight(
    cache: ApiCache, key: str, phase: str, token: _CacheToken, *, force_refresh: bool = False
) -> Iterator[tuple[_SingleFlightState, bool]]:
    flight_key = (id(cache), key, phase, token)
    with _singleflight_lock:
        state = _singleflight_by_key.get(flight_key)
        owner = False
        if state is None or state.complete:
            state = _SingleFlightState(event=threading.Event())
            _singleflight_by_key[flight_key] = state
            owner = True
        if force_refresh:
            state.refresh_requested = True
    try:
        yield state, owner
    except Exception as exc:
        if owner:
            state.error = exc
        raise
    finally:
        if owner:
            with _singleflight_lock:
                state.complete = True
                if _singleflight_by_key.get(flight_key) is state:
                    del _singleflight_by_key[flight_key]
                state.event.set()


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DISK_CACHE_ENABLED = os.getenv("API_DISK_CACHE_DISABLE", "").strip().lower() not in ("1", "true", "yes")
_GCS_CACHE_PREFIX = (os.getenv("API_GCS_CACHE_PREFIX") or "live/cache/api_cache").strip("/")


def _candidate_disk_cache_roots() -> list[Path]:
    env_path = (os.getenv("API_DISK_CACHE_DIR") or "").strip()
    roots: list[Path] = []
    if env_path:
        roots.append(Path(env_path).expanduser())
    roots.append(_REPO_ROOT / "data_cache" / "api_cache")
    roots.append(Path(os.getenv("TMPDIR") or "/tmp") / "talisman" / "data_cache" / "api_cache")
    deduped: list[Path] = []
    for root in roots:
        if root not in deduped:
            deduped.append(root)
    return deduped


def _initialize_disk_cache_root(candidates: list[Path]) -> tuple[Path, bool]:
    for root in candidates:
        try:
            (root / "short").mkdir(parents=True, exist_ok=True)
            (root / "long").mkdir(parents=True, exist_ok=True)
            (root / "daily").mkdir(parents=True, exist_ok=True)
            return root, True
        except Exception:
            logger.warning(
                "api cache init: failed to create disk cache dirs at %s; trying next fallback",
                str(root),
                exc_info=True,
            )
    return candidates[0], False


_DISK_CACHE_ROOTS = _candidate_disk_cache_roots()
_DISK_CACHE_ROOT = _DISK_CACHE_ROOTS[0]
if _DISK_CACHE_ENABLED:
    _DISK_CACHE_ROOT, _DISK_CACHE_ENABLED = _initialize_disk_cache_root(_DISK_CACHE_ROOTS)

logger.info(
    "api cache init: disk_cache=%s root=%s short_ttl=%ss long_ttl=%ss daily_ttl=%ss",
    "enabled" if _DISK_CACHE_ENABLED else "disabled",
    str(_DISK_CACHE_ROOT),
    getattr(short_cache, "ttl", "n/a"),
    getattr(long_cache, "ttl", "n/a"),
    getattr(daily_cache, "ttl", "n/a"),
)


def _disk_cache_name(cache: ApiCache) -> str:
    if cache is short_cache:
        return "short"
    if cache is daily_cache:
        return "daily"
    return "long"


def _disk_cache_path(cache: ApiCache, key: str) -> Path:
    name = _disk_cache_name(cache)
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return _DISK_CACHE_ROOT / name / f"{h}.json"


def _gcs_cache_enabled() -> bool:
    if _DISK_CACHE_ENABLED:
        return False
    try:
        from api.state_storage import use_gcs_state

        return bool(use_gcs_state())
    except Exception:
        return False


def _gcs_cache_key(cache: ApiCache, key: str) -> str:
    name = _disk_cache_name(cache)
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"{_GCS_CACHE_PREFIX}/{name}/{h}.json"


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except Exception:
        return None
    return parsed


def _timestamp_age_seconds(value: datetime) -> float:
    now = datetime.now(value.tzinfo) if value.tzinfo is not None else datetime.now()
    return (now - value).total_seconds()


def _stored_entry(cache: ApiCache, value: Any, created_at: datetime | None) -> _CacheEntry | None:
    if value is None or created_at is None:
        return None
    remaining = cache.ttl - _timestamp_age_seconds(created_at)
    if remaining <= 0:
        return None
    return _CacheEntry(value, cache.timer() + remaining, created_at)


def _disk_get(cache: ApiCache, key: str) -> _CacheEntry | None:
    if not _DISK_CACHE_ENABLED:
        return None
    path = _disk_cache_path(cache, key)
    try:
        count("storage_disk_reads")
        with measure("storage_ms"):
            payload = json.loads(path.read_text(encoding="utf-8"))
        created_at = _parse_timestamp(payload.get("created_at"))
        if created_at is None:
            created_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return _stored_entry(cache, payload.get("value"), created_at)
    except Exception:
        logger.debug("api cache disk read failed (key=%s path=%s)", key, str(path), exc_info=True)
        return None


def _disk_set(cache: ApiCache, key: str, entry: _CacheEntry) -> None:
    if not _DISK_CACHE_ENABLED:
        return
    path = _disk_cache_path(cache, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"key": key, "created_at": entry.created_at.isoformat(), "value": entry.value}), encoding="utf-8"
        )
        tmp.replace(path)
    except Exception:
        # Disk cache is best-effort; ignore failures.
        logger.debug("api cache disk write failed (key=%s path=%s)", key, str(path), exc_info=True)
        return


def _gcs_get(cache: ApiCache, key: str) -> _CacheEntry | None:
    if not _gcs_cache_enabled():
        return None
    gcs_key = _gcs_cache_key(cache, key)
    try:
        from api.state_storage import object_updated, read_text

        payload = json.loads(read_text(_DISK_CACHE_ROOT / ".state-cache-placeholder", gcs_key, encoding="utf-8"))
        created_at = _parse_timestamp(payload.get("created_at"))
        if created_at is None:
            created_at = object_updated(_DISK_CACHE_ROOT / ".state-cache-placeholder", gcs_key)
        return _stored_entry(cache, payload.get("value"), created_at)
    except Exception:
        logger.debug("api cache state read failed (key=%s gcs_key=%s)", key, gcs_key, exc_info=True)
        return None


def _gcs_set(cache: ApiCache, key: str, entry: _CacheEntry) -> None:
    if not _gcs_cache_enabled():
        return
    gcs_key = _gcs_cache_key(cache, key)
    try:
        from api.state_storage import write_text

        write_text(
            _DISK_CACHE_ROOT / ".state-cache-placeholder",
            gcs_key,
            json.dumps({"key": key, "created_at": entry.created_at.isoformat(), "value": entry.value}, allow_nan=False),
            encoding="utf-8",
            content_type="application/json; charset=utf-8",
        )
    except Exception:
        logger.debug("api cache state write failed (key=%s gcs_key=%s)", key, gcs_key, exc_info=True)


def _gcs_delete(cache: ApiCache, key: str) -> None:
    if not _gcs_cache_enabled():
        return
    gcs_key = _gcs_cache_key(cache, key)
    try:
        from api.state_storage import delete_file

        delete_file(_DISK_CACHE_ROOT / ".state-cache-placeholder", gcs_key)
    except Exception:
        logger.debug("api cache state delete failed (key=%s gcs_key=%s)", key, gcs_key, exc_info=True)


def _gcs_invalidate_all() -> None:
    if not _gcs_cache_enabled():
        return
    try:
        from api.state_storage import delete_file, list_keys

        for key in list_keys(f"{_GCS_CACHE_PREFIX}/"):
            delete_file(_DISK_CACHE_ROOT / ".state-cache-placeholder", key)
    except Exception:
        logger.debug("api cache state invalidate_all failed", exc_info=True)


def _stamp_age(v, cache: ApiCache) -> None:
    """Compute data_age_seconds and stale flag from _meta.fetched_at."""
    if not isinstance(v, dict):
        return
    meta = v.get("_meta")
    if not meta or "fetched_at" not in meta:
        return
    try:
        age = _timestamp_age_seconds(datetime.fromisoformat(meta["fetched_at"]))
        meta["data_age_seconds"] = round(age)
        ttl = meta.get("cache_ttl") or getattr(cache, "ttl", 600)
        meta["stale"] = age > 2 * ttl
    except Exception:
        pass


def _memory_entry(cache: ApiCache, key: str) -> _CacheEntry | None:
    with _lock:
        return cache.get(key)


def _cache_result(cache: ApiCache, entry: _CacheEntry | None, backend: str):
    if entry is None or entry.value is None:
        count("cache_miss")
        return None
    count("cache_hit")
    count(f"cache_{backend}_hit")
    _stamp_age(entry.value, cache)
    return entry.value


def _read_cached(
    cache: ApiCache,
    key: str,
    key_state: _KeyState,
    token: _CacheToken,
    wait_timeout_s: float,
) -> tuple[Any, bool]:
    """Return the value and whether waiting for a shared storage read timed out."""
    with _flight(cache, key, "read", token) as (state, owner):
        if owner:
            with key_state.io_lock:
                with _lock:
                    if not _token_current(key_state, token) or _clearing:
                        state.value = None
                        return _cache_result(cache, None, "memory"), False
                    entry = cache.get(key)
                if entry is None:
                    entry = _disk_get(cache, key)
                    state.backend = "disk"
                    if entry is None:
                        entry = _gcs_get(cache, key)
                        state.backend = "gcs"
                    with _lock:
                        if not _token_current(key_state, token) or _clearing:
                            entry = None
                        elif (published := cache.get(key)) is not None:
                            entry = published
                            state.backend = "memory"
                        elif entry is not None and entry.expires_at > cache.timer():
                            # maxsize bounds growth; preserve the original expiry
                            # so promotion never gives a stored value a fresh TTL.
                            cache[key] = entry
                        else:
                            entry = None
                state.value = entry
        else:
            count("cache_wait")
            with measure("cache_wait_ms"):
                waited = state.event.wait(timeout=wait_timeout_s)
            if not waited:
                return _cache_result(cache, _memory_entry(cache, key), "memory"), True
            if state.error is not None:
                raise state.error

        entry = state.value if isinstance(state.value, _CacheEntry) else None
        with _lock:
            if not _token_current(key_state, token) or (entry is not None and entry.expires_at <= cache.timer()):
                entry = None
        return _cache_result(cache, entry, state.backend), False


def get_cached(cache: ApiCache, key: str):
    with measure("cache_ms"):
        entry = _memory_entry(cache, key)
        if entry is not None:
            return _cache_result(cache, entry, "memory")
        with _key_operation(cache, key) as (key_state, token):
            value, _timed_out = _read_cached(cache, key, key_state, token, _READ_WAIT_TIMEOUT_S)
            return value


def _publish(
    cache: ApiCache, key: str, value, key_state: _KeyState, token: _CacheToken, *, wait_for_io: bool = True
) -> None:
    global _active_writes
    created_at = datetime.now(UTC)
    if isinstance(value, dict):
        raw_meta = value.get("_meta")
        existing_meta: dict = raw_meta if isinstance(raw_meta, dict) else {}
        value["_meta"] = {
            **existing_meta,
            "fetched_at": datetime.now().isoformat(),
            "cache_ttl": cache.ttl,
        }
    entry = _CacheEntry(value, cache.timer() + cache.ttl, created_at)
    with _lock:
        if not _token_current(key_state, token):
            return
        cache[key] = entry
        if _clearing:
            return
    # A timeout fallback may publish to memory without waiting for the slow
    # read it timed out on. Persistence remains best-effort in that case.
    if not key_state.io_lock.acquire(blocking=wait_for_io):
        return
    try:
        with _lock:
            if not _token_current(key_state, token) or _clearing or cache.get(key) is not entry:
                return
            _active_writes += 1
        try:
            _disk_set(cache, key, entry)
            _gcs_set(cache, key, entry)
        finally:
            with _writes_drained:
                _active_writes -= 1
                _writes_drained.notify_all()
    finally:
        key_state.io_lock.release()


def set_cached(cache: ApiCache, key: str, value) -> None:
    with _key_operation(cache, key) as (key_state, token):
        _publish(cache, key, value, key_state, token)


def _get_or_set_cached_with_status(
    cache: ApiCache,
    key: str,
    loader: Callable[[], Any],
    *,
    force_refresh: bool = False,
    wait_timeout_s: float = 120,
) -> tuple[Any, str]:
    if force_refresh:
        count("cache_refresh")
    if not force_refresh:
        with measure("cache_ms"):
            entry = _memory_entry(cache, key)
            if entry is not None and entry.value is not None:
                return _cache_result(cache, entry, "memory"), "hit"

    with (
        _key_operation(cache, key) as (key_state, token),
        _flight(cache, key, "load", token, force_refresh=force_refresh) as (state, owner),
    ):
        if owner:
            read_timed_out = False
            if not force_refresh:
                with measure("cache_ms"):
                    cached, read_timed_out = _read_cached(cache, key, key_state, token, wait_timeout_s)
                if cached is not None:
                    with _singleflight_lock:
                        if not state.refresh_requested:
                            state.value = cached
                            state.complete = True
                            return cached, "hit"
            value = loader()
            _publish(cache, key, value, key_state, token, wait_for_io=not read_timed_out)
            state.value = value
            return value, "refresh" if force_refresh else "miss_fetch"

        count("cache_wait")
        with measure("cache_wait_ms"):
            waited = state.event.wait(timeout=wait_timeout_s)
        if waited:
            if state.error is not None:
                raise state.error
            if state.value is not _MISSING:
                _stamp_age(state.value, cache)
                return state.value, "refresh" if force_refresh else "miss_wait"

        # Recheck only memory: a timed-out waiter must not start another
        # storage read or wait for the same read flight again.
        entry = _memory_entry(cache, key)
        if entry is not None and entry.value is not None:
            return _cache_result(cache, entry, "memory"), "refresh" if force_refresh else "miss_wait"

        logger.warning(
            "api cache singleflight wait timeout; running fallback loader key=%s force_refresh=%s",
            key,
            force_refresh,
        )
        value = loader()
        _publish(cache, key, value, key_state, token, wait_for_io=False)
        return value, "refresh" if force_refresh else "miss_refetch"


def get_or_set_cached(
    cache: ApiCache,
    key: str,
    loader: Callable[[], Any],
    *,
    force_refresh: bool = False,
    wait_timeout_s: float = 120,
):
    value, _status = _get_or_set_cached_with_status(
        cache,
        key,
        loader,
        force_refresh=force_refresh,
        wait_timeout_s=wait_timeout_s,
    )
    return value


def stamp_fresh(result: dict) -> dict:
    """Add _meta to uncached endpoint responses (always fresh)."""
    result["_meta"] = {
        "fetched_at": datetime.now().isoformat(),
        "cache_ttl": None,
        "data_age_seconds": 0,
        "stale": False,
    }
    return result


def delete_cached(cache: ApiCache, key: str) -> None:
    """Invalidate older work and delete a key from every tier (best-effort)."""
    with _key_operation(cache, key) as (key_state, _token), key_state.io_lock:
        with _lock:
            key_state.generation += 1
            cache.pop(key, None)
        if _DISK_CACHE_ENABLED:
            try:
                _disk_cache_path(cache, key).unlink(missing_ok=True)
            except Exception:
                pass
        _gcs_delete(cache, key)
    logger.info("api cache delete (key=%s)", key)


def invalidate_all() -> None:
    """Clear all tiers without letting older work restore invalidated entries."""
    global _cache_epoch, _clearing
    with _invalidation_lock:
        with _lock:
            _cache_epoch += 1
            _clearing = True
            short_cache.clear()
            long_cache.clear()
            daily_cache.clear()
        logger.info("api cache invalidate_all: memory cleared")
        try:
            # New requests bypass persistence while old uploads drain. Never
            # hold the memory lock while waiting for I/O or purging storage.
            with _writes_drained:
                _writes_drained.wait_for(lambda: _active_writes == 0)
            _invalidate_persistent_cache()
        finally:
            with _lock:
                _clearing = False
    _invalidate_downstream_caches()


def _invalidate_persistent_cache() -> None:
    try:
        if _DISK_CACHE_ROOT.exists():
            for sub in ("short", "long", "daily"):
                d = _DISK_CACHE_ROOT / sub
                if d.exists():
                    for p in d.glob("*.json"):
                        try:
                            p.unlink()
                        except Exception:
                            pass
    except Exception:
        logger.debug("api cache invalidate_all: disk cleanup failed", exc_info=True)

    _gcs_invalidate_all()


def _invalidate_downstream_caches() -> None:
    # Downstream module disk caches that survive between server restarts.
    try:
        from equities.market_technicals.market_breadth import invalidate_disk_cache as _invalidate_breadth

        _invalidate_breadth()
    except Exception:
        logger.debug("api cache invalidate_all: breadth disk cleanup failed", exc_info=True)

    try:
        from api.signal_aggregator import invalidate_sp500_price_cache

        invalidate_sp500_price_cache()
    except Exception:
        logger.debug("api cache invalidate_all: signal aggregator price cache cleanup failed", exc_info=True)

    try:
        from api.job_queue import clear_memory_jobs

        clear_memory_jobs()
    except Exception:
        logger.debug("api cache invalidate_all: async job cleanup failed", exc_info=True)

    try:
        from api.job_events import clear_memory_events

        clear_memory_events()
    except Exception:
        logger.debug("api cache invalidate_all: async job event cleanup failed", exc_info=True)
