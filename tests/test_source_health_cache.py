from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from api import source_health_cache as cache


@pytest.fixture(autouse=True)
def reset_cache():
    cache.invalidate_source_health()
    yield
    cache.invalidate_source_health()


def test_expiry_is_shared_by_inputs_and_derived_health(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: now[0])
    assert cache.cached_source_health_value("risk", lambda: "old") == "old"
    now[0] += 59
    assert cache.cached_source_health_value("health", lambda: "old health") == "old health"
    now[0] += 1
    assert cache.cached_source_health_value("health", lambda: "new health") == "new health"
    assert cache.cached_source_health_value("risk", lambda: "new") == "new"


def test_cached_values_are_isolated_from_caller_mutation():
    initial = cache.cached_source_health_value("health", lambda: {"domains": [{"status": "ok"}]})
    initial["domains"][0]["status"] = "failed"
    cached = cache.cached_source_health_value("health", lambda: pytest.fail("cache miss"))
    assert cached["domains"][0]["status"] == "ok"
    cached["domains"].clear()
    assert cache.cached_source_health_value("health", lambda: None)["domains"]


def test_concurrent_requests_share_one_fill():
    started, release = Event(), Event()
    calls = []

    def load():
        calls.append(1)
        started.set()
        assert release.wait(5)
        return {"value": 1}

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(cache.cached_source_health_value, "health", load) for _ in range(4)]
        assert started.wait(5)
        release.set()
        assert [f.result(timeout=5) for f in futures] == [{"value": 1}] * 4
    assert calls == [1]


def test_invalidation_during_fill_does_not_restore_old_values():
    started, release = Event(), Event()

    def load_old():
        started.set()
        assert release.wait(5)
        return "old"

    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(cache.cached_source_health_value, "health", load_old)
        assert started.wait(5)
        cache.invalidate_source_health()
        assert cache.cached_source_health_value("health", lambda: "new") == "new"
        release.set()
        assert old.result(timeout=5) == "old"
    assert cache.cached_source_health_value("health", lambda: pytest.fail("cache miss")) == "new"


def test_failed_fill_releases_waiters_and_can_retry():
    def fail():
        raise ValueError("unavailable")

    with pytest.raises(ValueError, match="unavailable"):
        cache.cached_source_health_value("health", fail)
    assert cache.cached_source_health_value("health", lambda: "recovered") == "recovered"


def test_missing_inputs_are_cached_and_expire(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: now[0])
    assert cache.cached_source_health_value("risk", lambda: None) is None
    assert cache.cached_source_health_value("risk", lambda: pytest.fail("unexpected retry")) is None
    now[0] += 60
    assert cache.cached_source_health_value("risk", lambda: "available") == "available"


def test_expired_fill_is_not_published(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: now[0])

    def load():
        now[0] += 61
        return "old"

    assert cache.cached_source_health_value("health", load) == "old"
    assert cache.cached_source_health_value("health", lambda: "new") == "new"


def test_unavailable_snapshot_inputs_do_not_retry_on_every_warm_request(monkeypatch):
    from api.source_health import get_source_health_portfolio_risk, get_source_health_regime

    calls = []

    def unavailable(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr("api.position_risk.get_latest_portfolio_risk", unavailable)
    monkeypatch.setattr("api.signal_snapshot.get_signal_aggregator_snapshot_or_module_response", unavailable)
    for _ in range(2):
        assert get_source_health_portfolio_risk() is None
        assert get_source_health_regime() is None
    assert len(calls) == 2
