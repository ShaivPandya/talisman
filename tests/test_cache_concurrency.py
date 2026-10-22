"""Deterministic read-through expiry and invalidation interleavings."""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from api import cache as cache_mod
from api import state_storage
from api.cache import ApiCache, delete_cached, get_cached, get_or_set_cached, invalidate_all, set_cached


class Clock:
    def __init__(self):
        self.wall = datetime(2026, 10, 19, 12, tzinfo=UTC)
        self.monotonic = 1000.0

    def __call__(self):
        return self.monotonic

    def advance(self, seconds):
        self.monotonic += seconds
        self.wall += timedelta(seconds=seconds)


class Store:
    def __init__(self, clock):
        self.clock = clock
        self.data = {}
        self.updated = {}
        self.reads = []
        self.writes = []

    def read(self, _path, key, **_kwargs):
        self.reads.append(key)
        return self.data[key]

    def write(self, _path, key, content, **_kwargs):
        self.writes.append(key)
        self.data[key] = content
        self.updated[key] = self.clock.wall
        return f"gs://test/{key}"

    def delete(self, _path, key):
        existed = key in self.data
        self.data.pop(key, None)
        self.updated.pop(key, None)
        return existed


@pytest.fixture
def isolated_cache(monkeypatch, tmp_path):
    clock = Clock()
    store = Store(clock)
    cache = ApiCache(maxsize=16, ttl=60, timer=clock)

    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock.wall.astimezone(tz)
            return value if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr(cache_mod, "datetime", ClockDateTime)
    monkeypatch.setattr(cache_mod, "long_cache", cache)
    monkeypatch.setattr(cache_mod, "_DISK_CACHE_ENABLED", False)
    monkeypatch.setattr(cache_mod, "_DISK_CACHE_ROOT", tmp_path)
    monkeypatch.setattr(cache_mod, "_GCS_CACHE_PREFIX", "test/cache")
    monkeypatch.setattr(cache_mod, "_invalidate_downstream_caches", lambda: None)
    monkeypatch.setattr(state_storage, "use_gcs_state", lambda: True)
    monkeypatch.setattr(state_storage, "read_text", store.read)
    monkeypatch.setattr(state_storage, "write_text", store.write)
    monkeypatch.setattr(state_storage, "delete_file", store.delete)
    monkeypatch.setattr(state_storage, "object_updated", lambda _path, key: store.updated.get(key))
    monkeypatch.setattr(
        state_storage, "list_keys", lambda prefix: sorted(k for k in store.data if k.startswith(prefix))
    )
    yield cache, store, clock
    assert cache._key_states == {}
    assert cache_mod._singleflight_by_key == {}
    assert cache_mod._active_writes == 0
    assert not cache_mod._clearing


@contextmanager
def blocked_call(monkeypatch, name, *, after=False):
    """Block one key at a real storage boundary; always release failed tests."""
    original = getattr(cache_mod, name)
    started = threading.Event()
    release = threading.Event()

    def blocked(cache, key, *args, **kwargs):
        if key != "blocked":
            return original(cache, key, *args, **kwargs)
        result = original(cache, key, *args, **kwargs) if after else None
        started.set()
        assert release.wait(5), f"{name} was never released"
        return result if after else original(cache, key, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(cache_mod, name, blocked)
        try:
            yield started, release
        finally:
            release.set()


def observe_waiters(monkeypatch):
    original = cache_mod._flight
    condition = threading.Condition()
    joined = 0

    @contextmanager
    def observed(*args, **kwargs):
        nonlocal joined
        with original(*args, **kwargs) as (state, owner):
            if not owner:
                with condition:
                    joined += 1
                    condition.notify_all()
            yield state, owner

    monkeypatch.setattr(cache_mod, "_flight", observed)

    def wait_for(count):
        with condition:
            assert condition.wait_for(lambda: joined >= count, timeout=5)

    return wait_for


@pytest.mark.parametrize("backend", ["disk", "gcs"])
@pytest.mark.parametrize("operation", ["read", "write", "delete"])
def test_blocked_storage_does_not_block_other_keys(isolated_cache, monkeypatch, backend, operation):
    cache, _store, _clock = isolated_cache
    monkeypatch.setattr(cache_mod, "_DISK_CACHE_ENABLED", backend == "disk")
    for key in ("blocked", "warm", "cold"):
        set_cached(cache, key, {"value": key})
    cache.clear()
    assert get_cached(cache, "warm")["value"] == "warm"
    name = {"read": f"_{backend}_get", "write": f"_{backend}_set", "delete": "_gcs_delete"}[operation]

    def operation_for_key():
        if operation == "read":
            return get_cached(cache, "blocked")
        if operation == "write":
            return set_cached(cache, "blocked", {"value": "new"})
        return delete_cached(cache, "blocked")

    with ThreadPoolExecutor(max_workers=3) as pool, blocked_call(monkeypatch, name) as (started, release):
        blocked = pool.submit(operation_for_key)
        assert started.wait(5)
        assert pool.submit(get_cached, cache, "warm").result(timeout=1)["value"] == "warm"
        assert pool.submit(get_cached, cache, "cold").result(timeout=1)["value"] == "cold"
        assert not blocked.done()
        release.set()
        blocked.result(timeout=5)


@pytest.mark.parametrize("kind", ["direct", "load", "mixed"])
@pytest.mark.parametrize("stored_hit", [False, True])
def test_concurrent_lookups_share_one_storage_read(isolated_cache, monkeypatch, kind, stored_hit):
    cache, store, _clock = isolated_cache
    if stored_hit:
        set_cached(cache, "blocked", {"value": "stored"})
        cache.clear()
    calls = []
    wait_for = observe_waiters(monkeypatch)

    def lookup(index):
        if kind == "direct" or (kind == "mixed" and index % 2 == 0):
            return get_cached(cache, "blocked")

        def loader():
            calls.append(index)
            return {"value": "loaded"}

        return get_or_set_cached(cache, "blocked", loader)

    with ThreadPoolExecutor(max_workers=6) as pool, blocked_call(monkeypatch, "_gcs_get") as (started, release):
        futures = [pool.submit(lookup, 0)]
        assert started.wait(5)
        futures.extend(pool.submit(lookup, index) for index in range(1, 6))
        wait_for(5)
        release.set()
        results = [future.result(timeout=5) for future in futures]

    assert len(store.reads) == 1
    assert len(calls) == (0 if stored_hit or kind == "direct" else 1)
    for index, result in enumerate(results):
        expected = "stored" if stored_hit else "loaded"
        if not stored_hit and (kind == "direct" or (kind == "mixed" and index % 2 == 0)):
            assert result is None
        else:
            assert result["value"] == expected


@pytest.mark.parametrize("backend", ["disk", "gcs"])
@pytest.mark.parametrize("legacy", [False, True])
def test_promoted_entries_keep_original_expiry_and_metadata(isolated_cache, monkeypatch, backend, legacy):
    cache, store, clock = isolated_cache
    monkeypatch.setattr(cache_mod, "_DISK_CACHE_ENABLED", backend == "disk")
    set_cached(cache, "promoted", {"value": 42})
    original_meta = dict(get_cached(cache, "promoted")["_meta"])
    if backend == "disk":
        path = cache_mod._disk_cache_path(cache, "promoted")
        payload = json.loads(path.read_text())
        assert payload["created_at"]
        if legacy:
            payload.pop("created_at")
            path.write_text(json.dumps(payload))
        os.utime(path, (clock.wall.timestamp(), clock.wall.timestamp()))
        original_disk = path.read_bytes()
    elif legacy:
        key = cache_mod._gcs_cache_key(cache, "promoted")
        payload = json.loads(store.data[key])
        payload.pop("created_at")
        store.data[key] = json.dumps(payload)
    writes = list(store.writes)
    cache.clear()
    clock.advance(45)
    promoted = get_cached(cache, "promoted")
    assert promoted["value"] == 42
    assert promoted["_meta"]["fetched_at"] == original_meta["fetched_at"]
    assert promoted["_meta"]["cache_ttl"] == 60
    assert promoted["_meta"]["data_age_seconds"] == 45
    assert cache.get("promoted").expires_at == 1060
    clock.advance(14)
    assert get_cached(cache, "promoted")["value"] == 42
    assert store.writes == writes
    if backend == "gcs":
        assert len(store.reads) == 1
    else:
        assert path.read_bytes() == original_disk
    clock.advance(1)
    assert get_cached(cache, "promoted") is None


@pytest.mark.parametrize("timestamp", [None, "invalid", "aware", "naive"])
def test_unusable_or_expired_storage_timestamp_is_a_miss(isolated_cache, timestamp):
    cache, store, _clock = isolated_cache
    key = cache_mod._gcs_cache_key(cache, "expired")
    if timestamp in ("aware", "naive"):
        now = cache_mod.datetime.now(UTC if timestamp == "aware" else None)
        timestamp = (now - timedelta(seconds=60)).isoformat()
    store.data[key] = json.dumps({"value": "old", "created_at": timestamp})
    assert get_cached(cache, "expired") is None
    assert cache.get("expired") is None


def test_entry_expiring_during_read_is_not_promoted(isolated_cache, monkeypatch):
    cache, _store, clock = isolated_cache
    set_cached(cache, "blocked", "old")
    cache.clear()
    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        blocked_call(monkeypatch, "_gcs_get", after=True) as (
            started,
            release,
        ),
    ):
        lookup = pool.submit(get_cached, cache, "blocked")
        assert started.wait(5)
        clock.advance(60)
        release.set()
        assert lookup.result(timeout=5) is None
    assert cache.get("blocked") is None


@pytest.mark.parametrize("action", ["delete", "clear"])
def test_invalidation_prevents_older_loader_from_repopulating(isolated_cache, action):
    cache, store, _clock = isolated_cache
    started = threading.Event()
    release = threading.Event()

    def old_loader():
        started.set()
        assert release.wait(5)
        return {"value": "old"}

    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(get_or_set_cached, cache, "same", old_loader)
        try:
            assert started.wait(5)
            delete_cached(cache, "same") if action == "delete" else invalidate_all()
            assert get_or_set_cached(cache, "same", lambda: {"value": "new"})["value"] == "new"
        finally:
            release.set()
        assert old.result(timeout=5)["value"] == "old"
    assert get_cached(cache, "same")["value"] == "new"
    assert json.loads(store.data[cache_mod._gcs_cache_key(cache, "same")])["value"]["value"] == "new"


def test_clear_discards_inflight_read_without_waiting_for_it(isolated_cache, monkeypatch):
    cache, store, _clock = isolated_cache
    set_cached(cache, "blocked", "old")
    cache.clear()
    with (
        ThreadPoolExecutor(max_workers=2) as pool,
        blocked_call(monkeypatch, "_gcs_get", after=True) as (
            started,
            release,
        ),
    ):
        old = pool.submit(get_cached, cache, "blocked")
        assert started.wait(5)
        pool.submit(invalidate_all).result(timeout=1)
        assert not store.data
        release.set()
        assert old.result(timeout=5) is None
    assert get_cached(cache, "blocked") is None


def test_delete_waits_for_inflight_upload_then_removes_it(isolated_cache, monkeypatch):
    cache, store, _clock = isolated_cache
    with ThreadPoolExecutor(max_workers=2) as pool, blocked_call(monkeypatch, "_gcs_set") as (started, release):
        writer = pool.submit(set_cached, cache, "blocked", "old")
        assert started.wait(5)
        deleted = pool.submit(delete_cached, cache, "blocked")
        release.set()
        writer.result(timeout=5)
        deleted.result(timeout=5)
    assert get_cached(cache, "blocked") is None
    assert not store.data


def test_clear_drains_old_uploads_while_new_requests_continue(isolated_cache, monkeypatch):
    cache, store, _clock = isolated_cache
    clearing = threading.Event()
    original_wait = cache_mod._writes_drained.wait_for

    def observe_clear(predicate, timeout=None):
        clearing.set()
        return original_wait(predicate, timeout)

    monkeypatch.setattr(cache_mod._writes_drained, "wait_for", observe_clear)
    with ThreadPoolExecutor(max_workers=3) as pool, blocked_call(monkeypatch, "_gcs_set") as (started, release):
        writer = pool.submit(set_cached, cache, "blocked", "old")
        assert started.wait(5)
        cleared = pool.submit(invalidate_all)
        assert clearing.wait(5)
        assert not cleared.done()
        reads_before = list(store.reads)
        fresh = pool.submit(get_or_set_cached, cache, "new", lambda: "fresh")
        assert fresh.result(timeout=1) == "fresh"
        assert get_cached(cache, "new") == "fresh"
        assert store.reads == reads_before
        release.set()
        writer.result(timeout=5)
        cleared.result(timeout=5)
    assert get_cached(cache, "blocked") is None
    assert get_cached(cache, "new") == "fresh"
    assert not store.data


def test_direct_waiter_times_out_without_another_storage_read(isolated_cache, monkeypatch):
    cache, store, _clock = isolated_cache
    monkeypatch.setattr(cache_mod, "_READ_WAIT_TIMEOUT_S", 0)
    with ThreadPoolExecutor(max_workers=1) as pool, blocked_call(monkeypatch, "_gcs_get") as (started, release):
        owner = pool.submit(get_cached, cache, "blocked")
        assert started.wait(5)
        assert get_cached(cache, "blocked") is None
        release.set()
        assert owner.result(timeout=5) is None
    assert len(store.reads) == 1


def test_loader_joining_direct_read_can_finish_after_read_timeout(isolated_cache, monkeypatch):
    cache, store, _clock = isolated_cache
    set_cached(cache, "blocked", "old")
    cache.clear()
    with (
        ThreadPoolExecutor(max_workers=2) as pool,
        blocked_call(monkeypatch, "_gcs_get", after=True) as (
            started,
            release,
        ),
    ):
        reader = pool.submit(get_cached, cache, "blocked")
        assert started.wait(5)
        loaded = pool.submit(get_or_set_cached, cache, "blocked", lambda: "fresh", wait_timeout_s=0)
        assert loaded.result(timeout=1) == "fresh"
        release.set()
        assert reader.result(timeout=5) == "fresh"
    assert len(store.reads) == 1
    assert get_cached(cache, "blocked") == "fresh"


@pytest.mark.parametrize("expire_read", [False, True])
def test_timeout_fallback_does_not_wait_for_storage_or_promote_old_value(isolated_cache, monkeypatch, expire_read):
    cache, store, clock = isolated_cache
    set_cached(cache, "blocked", {"value": "old"})
    cache.clear()
    owner_loads = []

    def owner_loader():
        owner_loads.append(True)
        return {"value": "unexpected"}

    with (
        ThreadPoolExecutor(max_workers=2) as pool,
        blocked_call(monkeypatch, "_gcs_get", after=True) as (
            started,
            release,
        ),
    ):
        owner = pool.submit(get_or_set_cached, cache, "blocked", owner_loader)
        assert started.wait(5)
        if expire_read:
            clock.advance(60)
        waiter = pool.submit(
            cache_mod._get_or_set_cached_with_status,
            cache,
            "blocked",
            lambda: {"value": "fresh"},
            wait_timeout_s=0,
        )
        value, status = waiter.result(timeout=1)
        assert value["value"] == "fresh"
        assert status == "miss_refetch"
        release.set()
        assert owner.result(timeout=5)["value"] == "fresh"
    assert owner_loads == []
    assert len(store.reads) == 1
    assert get_cached(cache, "blocked")["value"] == "fresh"


def test_clear_rejects_upload_queued_behind_a_read(isolated_cache, monkeypatch):
    cache, store, _clock = isolated_cache
    set_cached(cache, "blocked", "old")
    cache.clear()
    published = threading.Event()
    original_set = ApiCache.__setitem__

    def observe_set(self, key, entry):
        original_set(self, key, entry)
        if self is cache and entry.value == "queued":
            published.set()

    monkeypatch.setattr(ApiCache, "__setitem__", observe_set)
    with (
        ThreadPoolExecutor(max_workers=3) as pool,
        blocked_call(monkeypatch, "_gcs_get", after=True) as (
            started,
            release,
        ),
    ):
        reader = pool.submit(get_cached, cache, "blocked")
        assert started.wait(5)
        writer = pool.submit(set_cached, cache, "blocked", "queued")
        assert published.wait(5)
        pool.submit(invalidate_all).result(timeout=1)
        release.set()
        assert reader.result(timeout=5) is None
        writer.result(timeout=5)
    assert get_cached(cache, "blocked") is None
    assert not store.data
    assert len(store.writes) == 1


def test_requests_continue_while_clear_purges_storage(isolated_cache, monkeypatch):
    cache, store, _clock = isolated_cache
    started = threading.Event()
    release = threading.Event()
    original = cache_mod._gcs_invalidate_all

    def purge():
        started.set()
        assert release.wait(5)
        original()

    monkeypatch.setattr(cache_mod, "_gcs_invalidate_all", purge)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cleared = pool.submit(invalidate_all)
        try:
            assert started.wait(5)
            fresh = pool.submit(get_or_set_cached, cache, "new", lambda: "fresh")
            assert fresh.result(timeout=1) == "fresh"
            assert not store.reads
            assert not store.writes
        finally:
            release.set()
        cleared.result(timeout=5)
    assert get_cached(cache, "new") == "fresh"


def test_force_refresh_joining_storage_read_still_runs_loader(isolated_cache, monkeypatch):
    cache, _store, _clock = isolated_cache
    set_cached(cache, "blocked", "old")
    cache.clear()
    wait_for = observe_waiters(monkeypatch)
    calls = []

    def loader():
        calls.append(True)
        return "fresh"

    with ThreadPoolExecutor(max_workers=2) as pool, blocked_call(monkeypatch, "_gcs_get") as (started, release):
        owner = pool.submit(get_or_set_cached, cache, "blocked", loader)
        assert started.wait(5)
        refresh = pool.submit(get_or_set_cached, cache, "blocked", loader, force_refresh=True)
        wait_for(1)
        release.set()
        assert owner.result(timeout=5) == "fresh"
        assert refresh.result(timeout=5) == "fresh"
    assert len(calls) == 1


def test_eviction_and_completed_keys_keep_memory_and_coordination_bounded(isolated_cache):
    cache, _store, _clock = isolated_cache
    for index in range(64):
        set_cached(cache, f"key-{index}", index)
    assert len(cache) == cache.maxsize == 16
    assert cache._key_states == {}
