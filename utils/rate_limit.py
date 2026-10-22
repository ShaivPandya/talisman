"""
Process-wide token buckets that pace calls to external data providers.

Each provider gets one shared bucket. Up to ``burst`` calls start immediately; after
that, calls are admitted at the refill rate. The refill rate is
``(calls - burst) / per_seconds``, so any window of ``per_seconds`` admits at most
``calls`` requests even when the bucket starts full.

Buckets are per process: separate workers or instances each get their own allowance.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


class TokenBucket:
    """Thread-safe token bucket. Waiting callers reserve their slot, so they are admitted in order."""

    def __init__(self, rate: float, burst: int) -> None:
        if rate <= 0 or burst < 1:
            raise ValueError("TokenBucket needs a positive rate and a burst of at least 1.")
        self.rate = rate
        self.burst = float(burst)
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Take one token, sleeping until it is available. Returns the seconds waited."""
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self.burst, self._tokens + (now - self._updated) * self.rate)
            self._updated = now
            self._tokens -= 1
            wait = -self._tokens / self.rate if self._tokens < 0 else 0.0
        if wait:
            time.sleep(wait)
        return wait


@dataclass(frozen=True, slots=True)
class RateLimit:
    calls: int
    per_seconds: float
    burst: int

    def bucket(self) -> TokenBucket:
        return TokenBucket((self.calls - self.burst) / self.per_seconds, self.burst)


PROVIDER_LIMITS: dict[str, RateLimit] = {
    # FRED allows 120 requests per minute per API key.
    "fred": RateLimit(calls=120, per_seconds=60, burst=20),
}

_buckets: dict[str, TokenBucket] = {}
_buckets_lock = threading.Lock()


def provider_limiter(provider: str) -> TokenBucket:
    """Return the shared bucket for a provider named in PROVIDER_LIMITS."""
    with _buckets_lock:
        bucket = _buckets.get(provider)
        if bucket is None:
            bucket = _buckets[provider] = PROVIDER_LIMITS[provider].bucket()
        return bucket
