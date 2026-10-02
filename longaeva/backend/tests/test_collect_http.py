"""PoliteClient rate limiting and access-control handling (LON-13)."""

from __future__ import annotations

import httpx
import pytest

from longaeva_app.collect.http import FetchError, PoliteClient, SourceUnavailable


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_per_host_spacing_with_fake_clock() -> None:
    clock = FakeClock()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=b"ok")

    transport = httpx.MockTransport(handler)
    client = PoliteClient(
        user_agent="LongaevaTest/0.1 (test@example.com)",
        transport=transport,
        clock=clock,
        sleep=clock.sleep,
        host_intervals={"www.sec.gov": 0.5},
    )
    with client:
        client.get("https://www.sec.gov/a")
        client.get("https://www.sec.gov/b")
    assert calls["n"] == 2
    assert clock.sleeps and clock.sleeps[0] == pytest.approx(0.5)


def test_user_agent_header_sent() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, content=b"ok")

    client = PoliteClient(
        user_agent="LongaevaTest/0.1 (contact@example.com)",
        transport=httpx.MockTransport(handler),
    )
    with client:
        client.get("https://www.sec.gov/x")
    assert seen == ["LongaevaTest/0.1 (contact@example.com)"]


def test_403_unavailable_after_one_request() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403, content=b"forbidden")

    client = PoliteClient(
        user_agent="LongaevaTest/0.1 (test@example.com)",
        transport=httpx.MockTransport(handler),
    )
    with client:
        with pytest.raises(SourceUnavailable) as exc:
            client.get("https://investor.visa.com/news/")
    assert exc.value.reason == "http_403"
    assert calls["n"] == 1


def test_js_challenge_unavailable() -> None:
    body = b"<html><title>Just a moment...</title><div class='cf-browser-verification'></div></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    client = PoliteClient(
        user_agent="LongaevaTest/0.1 (test@example.com)",
        transport=httpx.MockTransport(handler),
    )
    with client:
        with pytest.raises(SourceUnavailable) as exc:
            client.get("https://example.com/challenge")
    assert exc.value.reason == "js_challenge"


def test_backoff_then_success() -> None:
    clock = FakeClock()
    states = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        states["n"] += 1
        if states["n"] < 3:
            return httpx.Response(503, content=b"busy", headers={"Retry-After": "2"})
        return httpx.Response(200, content=b"ok")

    client = PoliteClient(
        user_agent="LongaevaTest/0.1 (test@example.com)",
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=clock.sleep,
        host_intervals={"example.com": 0.0},
        default_interval=0.0,
    )
    with client:
        result = client.get("https://example.com/retry")
    assert result.content == b"ok"
    assert states["n"] == 3
    assert 2.0 in clock.sleeps


def test_requires_user_agent() -> None:
    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        PoliteClient(user_agent="")


def test_exhausted_retries_raises_fetch_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"err")

    clock = FakeClock()
    client = PoliteClient(
        user_agent="LongaevaTest/0.1 (test@example.com)",
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=clock.sleep,
        max_retries=1,
        default_interval=0.0,
        host_intervals={"example.com": 0.0},
    )
    with client:
        with pytest.raises(FetchError):
            client.get("https://example.com/fail")
