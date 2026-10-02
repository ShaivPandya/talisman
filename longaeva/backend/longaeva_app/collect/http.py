"""Polite HTTP client for the LON-13 collector (DR-09).

Declared User-Agent, per-host minimum intervals, exponential backoff with
``Retry-After``, and no bypass of 403 / JavaScript challenges.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from longaeva_app.collect.visa_ir import JS_CHALLENGE_MARKERS

Clock = Callable[[], float]
Sleeper = Callable[[float], None]

# Per-host minimum intervals (seconds). sec.gov stays well under the SEC
# fair-access ceiling of 10 req/s; Census and Visa CDN follow gate decisions.
DEFAULT_HOST_INTERVALS: dict[str, float] = {
    "www.sec.gov": 0.5,
    "sec.gov": 0.5,
    "data.sec.gov": 0.5,
    "www.census.gov": 1.0,
    "www2.census.gov": 1.0,
    "census.gov": 1.0,
    "s1.q4cdn.com": 10.0,
}

DEFAULT_INTERVAL = 1.0
MAX_RETRIES = 4
BASE_BACKOFF = 1.0
REQUEST_TIMEOUT = 60.0


class SourceUnavailable(Exception):
    """Raised when a source cannot be fetched without bypassing access controls."""

    def __init__(self, url: str, reason: str, *, http_status: int | None = None) -> None:
        self.url = url
        self.reason = reason
        self.http_status = http_status
        super().__init__(f"{reason}: {url}" + (f" (HTTP {http_status})" if http_status else ""))


class FetchError(Exception):
    """Raised when a fetch fails after retries (not an access-control block)."""

    def __init__(self, url: str, message: str, *, http_status: int | None = None) -> None:
        self.url = url
        self.http_status = http_status
        super().__init__(f"{message}: {url}" + (f" (HTTP {http_status})" if http_status else ""))


@dataclass(frozen=True)
class FetchResult:
    """Successful HTTP response body and selected headers."""

    url: str
    content: bytes
    status_code: int
    headers: Mapping[str, str]
    final_url: str

    @property
    def etag(self) -> str | None:
        return self.headers.get("etag") or self.headers.get("ETag")

    @property
    def last_modified(self) -> str | None:
        return self.headers.get("last-modified") or self.headers.get("Last-Modified")

    @property
    def content_type(self) -> str | None:
        return self.headers.get("content-type") or self.headers.get("Content-Type")


@dataclass
class PoliteClient:
    """httpx client with per-host spacing, backoff, and access-control detection."""

    user_agent: str
    host_intervals: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_HOST_INTERVALS))
    default_interval: float = DEFAULT_INTERVAL
    max_retries: int = MAX_RETRIES
    timeout: float = REQUEST_TIMEOUT
    transport: httpx.BaseTransport | None = None
    clock: Clock = time.monotonic
    sleep: Sleeper = time.sleep
    _last_request_at: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _client: httpx.Client | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.user_agent or not self.user_agent.strip():
            raise ValueError("SEC_USER_AGENT is required for live fetches. Set it in longaeva/.env or the environment.")

    def __enter__(self) -> PoliteClient:
        self._ensure_client()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            kwargs: dict[str, Any] = {
                "headers": {"User-Agent": self.user_agent.strip()},
                "timeout": self.timeout,
                "follow_redirects": True,
            }
            if self.transport is not None:
                kwargs["transport"] = self.transport
            self._client = httpx.Client(**kwargs)
        return self._client

    def interval_for(self, url: str) -> float:
        host = (urlparse(url).hostname or "").lower()
        if host in self.host_intervals:
            return float(self.host_intervals[host])
        # Match parent domains (e.g. edgar.sec.gov → sec.gov).
        for known, interval in self.host_intervals.items():
            if host == known or host.endswith("." + known):
                return float(interval)
        return self.default_interval

    def _wait_for_host(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        interval = self.interval_for(url)
        last = self._last_request_at.get(host)
        if last is not None:
            elapsed = self.clock() - last
            remaining = interval - elapsed
            if remaining > 0:
                self.sleep(remaining)

    def _mark_request(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        self._last_request_at[host] = self.clock()

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> FetchResult:
        """GET ``url`` with polite spacing and retries.

        Raises ``SourceUnavailable`` on 403 or a JS-challenge body (one attempt).
        Raises ``FetchError`` after exhausting retries on 429/5xx/transport errors.
        """
        client = self._ensure_client()
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._wait_for_host(url)
            try:
                response = client.get(url, headers=dict(headers or {}))
            except httpx.HTTPError as exc:
                self._mark_request(url)
                last_error = exc
                if attempt >= self.max_retries:
                    break
                self.sleep(BASE_BACKOFF * (2**attempt))
                continue

            self._mark_request(url)
            status = response.status_code
            header_map = {k.lower(): v for k, v in response.headers.items()}
            # Preserve original casing for common lookup helpers.
            header_map.update({k: v for k, v in response.headers.items()})

            if status == 403:
                raise SourceUnavailable(url, "http_403", http_status=403)

            body = response.content
            if _looks_like_js_challenge(body, status):
                raise SourceUnavailable(url, "js_challenge", http_status=status)

            if status == 429 or status >= 500:
                last_error = FetchError(url, f"transient HTTP {status}", http_status=status)
                if attempt >= self.max_retries:
                    break
                delay = _retry_after_seconds(response) or (BASE_BACKOFF * (2**attempt))
                self.sleep(delay)
                continue

            if status >= 400:
                raise FetchError(url, f"HTTP {status}", http_status=status)

            return FetchResult(
                url=url,
                content=body,
                status_code=status,
                headers=dict(response.headers),
                final_url=str(response.url),
            )

        message = str(last_error) if last_error is not None else "unknown fetch failure"
        err_status: int | None = getattr(last_error, "http_status", None)
        raise FetchError(url, f"exhausted retries: {message}", http_status=err_status)


def _looks_like_js_challenge(body: bytes, status: int) -> bool:
    if status not in {200, 401, 403, 503}:
        # Only inspect bodies that commonly carry challenge pages.
        if status < 400:
            text_head = body[:4096].decode("utf-8", errors="ignore")
            return any(marker in text_head for marker in JS_CHALLENGE_MARKERS)
        return False
    text_head = body[:4096].decode("utf-8", errors="ignore")
    return any(marker in text_head for marker in JS_CHALLENGE_MARKERS)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None
