from __future__ import annotations

import threading
from bisect import bisect_left

import pytest

from utils import rate_limit


class FakeClock:
    def __init__(self, *, advance_on_sleep: bool = True) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self.advance_on_sleep = advance_on_sleep

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if self.advance_on_sleep:
            self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(rate_limit, "time", fake)
    return fake


def test_burst_starts_immediately_then_calls_are_paced(clock):
    bucket = rate_limit.TokenBucket(rate=2.0, burst=3)
    waits = [bucket.acquire() for _ in range(5)]
    assert waits == [0.0, 0.0, 0.0, pytest.approx(0.5), pytest.approx(0.5)]
    assert clock.now == pytest.approx(1.0)


def test_idle_time_refills_up_to_the_burst_only(clock):
    bucket = rate_limit.TokenBucket(rate=1.0, burst=2)
    bucket.acquire()
    bucket.acquire()
    clock.now += 100
    assert [bucket.acquire() for _ in range(3)] == [0.0, 0.0, pytest.approx(1.0)]


def test_fred_limit_never_admits_more_than_120_calls_in_any_minute(clock):
    bucket = rate_limit.PROVIDER_LIMITS["fred"].bucket()
    admitted = []
    for _ in range(400):
        bucket.acquire()
        admitted.append(clock.now)
    # Windows just under a minute, so the 120th call landing exactly on the boundary cannot round in.
    busiest = max(bisect_left(admitted, start + 60 - 1e-6) - i for i, start in enumerate(admitted))
    assert busiest <= 120
    assert admitted[19] == 0.0 and admitted[20] > 0.0
    assert admitted[-1] == pytest.approx((400 - 20) * 0.6)


def test_concurrent_callers_reserve_distinct_slots(monkeypatch):
    clock = FakeClock(advance_on_sleep=False)
    monkeypatch.setattr(rate_limit, "time", clock)
    bucket = rate_limit.TokenBucket(rate=10.0, burst=4)
    start = threading.Barrier(16)
    waits: list[float] = []

    def call() -> None:
        start.wait()
        waits.append(bucket.acquire())

    threads = [threading.Thread(target=call) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(waits) == pytest.approx([0.0] * 4 + [n / 10 for n in range(1, 13)])


def test_provider_limiter_is_shared_per_provider(monkeypatch):
    monkeypatch.setattr(rate_limit, "_buckets", {})
    assert rate_limit.provider_limiter("fred") is rate_limit.provider_limiter("fred")
    with pytest.raises(KeyError):
        rate_limit.provider_limiter("unknown")


def test_bucket_rejects_unusable_limits():
    with pytest.raises(ValueError):
        rate_limit.TokenBucket(rate=0, burst=1)
    with pytest.raises(ValueError):
        rate_limit.TokenBucket(rate=1, burst=0)
