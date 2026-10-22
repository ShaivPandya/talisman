import asyncio
from datetime import UTC, date, datetime

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, ORJSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel

from api import main
from api.logging_config import request_id_var


@pytest.fixture
def probe_app(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.setenv("REQUIRE_API_PROXY_SECRET", "false")
    monkeypatch.setattr(main, "_WRITE_FREEZE", False)
    monkeypatch.setattr(main, "emit_audit_event", lambda *args, **kwargs: None)
    app = FastAPI(default_response_class=main.app.router.default_response_class)
    app.add_middleware(main.ApiMiddleware, schema_app=app)
    app.add_exception_handler(Exception, main._unhandled_error_handler)
    return app


def test_guards_preserve_rejection_order_and_headers(probe_app, monkeypatch):
    monkeypatch.setattr(main, "verify_request_csrf", lambda request: False)
    client = TestClient(probe_app)
    monkeypatch.setenv("AUTH_MODE", "cloudflare")
    monkeypatch.setenv("API_PROXY_SECRET", "")
    monkeypatch.setattr(main, "_WRITE_FREEZE", True)
    frozen = client.post("/api/probe")
    assert frozen.status_code == 423
    monkeypatch.setattr(main, "_WRITE_FREEZE", False)
    proxy = client.post("/api/probe")
    assert proxy.status_code == 403 and "proxy secret" in proxy.json()["detail"]
    monkeypatch.setenv("API_PROXY_SECRET", "test-proxy")
    csrf = client.post("/api/probe", headers={"X-Api-Proxy-Secret": "test-proxy"})
    assert csrf.status_code == 403 and "CSRF" in csrf.json()["detail"]
    for response in (frozen, proxy, csrf):
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["x-request-id"]


def test_custom_security_headers_and_production_hsts(probe_app, monkeypatch):
    @probe_app.get("/api/probe")
    def probe():
        return JSONResponse(
            {}, headers={"Content-Security-Policy": "default-src 'self'", "Referrer-Policy": "same-origin"}
        )

    monkeypatch.setenv("ENVIRONMENT", "production")
    response = TestClient(probe_app).get("/api/probe", headers={"X-Request-Id": "probe-request"})
    assert response.headers["x-request-id"] == "probe-request"
    assert response.headers["content-security-policy"] == "default-src 'self'; frame-ancestors 'none'"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_error_reply_keeps_request_id_and_security_headers(probe_app):
    @probe_app.get("/api/probe")
    def probe():
        raise RuntimeError("private implementation detail")

    response = TestClient(probe_app, raise_server_exceptions=False).get(
        "/api/probe", headers={"X-Request-Id": "error-id"}
    )
    assert response.status_code == 500
    assert response.json() == {"error": "Internal server error", "type": "InternalError"}
    assert response.headers["x-request-id"] == "error-id"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_default_json_dates_nonfinite_numbers_and_response_validation(probe_app):
    assert probe_app.router.default_response_class is ORJSONResponse

    @probe_app.get("/api/json")
    def json_payload():
        return {
            "date": date(2026, 1, 2),
            "timestamp": datetime(2026, 1, 2, tzinfo=UTC),
            "nan": float("nan"),
            "inf": float("inf"),
        }

    class PublicModel(BaseModel):
        value: int

    @probe_app.get("/api/model", response_model=PublicModel)
    def model_payload():
        return {"value": 1, "private": "must be filtered"}

    @probe_app.get("/api/direct")
    def direct_payload():
        return ORJSONResponse({"array": np.array([1.0, np.nan, np.inf]), "timestamp": datetime(2026, 1, 2)})

    client = TestClient(probe_app)
    assert client.get("/api/json").json() == {
        "date": "2026-01-02",
        "timestamp": "2026-01-02T00:00:00+00:00",
        "nan": None,
        "inf": None,
    }
    assert client.get("/api/model").json() == {"value": 1}
    assert client.get("/api/direct").json() == {"array": [1.0, None, None], "timestamp": "2026-01-02T00:00:00"}


def test_upgraded_chunked_body_still_obeys_body_limit(probe_app, monkeypatch):
    from api.request_schema import register_api_request_upgrade_adapter

    class Payload(BaseModel):
        value: str

    @probe_app.post("/api/auth/login")
    def endpoint(body: Payload):
        return body

    register_api_request_upgrade_adapter("post:/api/auth/login", 0, 1, lambda payload: {"value": payload["old"]})
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "20")

    async def run():
        async def body():
            yield b'{"old":"'
            yield b"a" * 100
            yield b'"}'

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=probe_app), base_url="http://probe") as client:
            response = await client.post(
                "/api/auth/login",
                content=body(),
                headers={
                    "Content-Type": "application/json",
                    "X-Request-Schema-Name": "post:/api/auth/login",
                    "X-Request-Schema-Version": "0",
                },
            )
        assert response.status_code == 413
        assert response.headers["x-request-id"]

    asyncio.run(run())


def test_streaming_is_unbuffered_and_request_context_is_isolated(probe_app):
    async def run():
        first = asyncio.Event()
        release = asyncio.Event()
        messages = []

        async def inner(scope, receive, send):
            assert request_id_var.get() == "stream-id"
            await send(
                {"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]}
            )
            await send({"type": "http.response.body", "body": b"data: first\n\n", "more_body": True})
            await release.wait()
            await send({"type": "http.response.body", "body": b"data: last\n\n"})

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body":
                first.set()

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/stream",
            "headers": [(b"x-request-id", b"stream-id")],
            "query_string": b"",
        }
        previous = request_id_var.get("")
        wrapper = main.ApiMiddleware(inner, schema_app=probe_app)
        task = asyncio.create_task(wrapper(scope, receive, send))
        try:
            await asyncio.wait_for(first.wait(), 2)
            assert not task.done()
            assert messages[-1]["body"] == b"data: first\n\n"
            assert request_id_var.get("") == previous
        finally:
            release.set()
            await task
        assert messages[-1]["body"] == b"data: last\n\n"
        assert request_id_var.get("") == previous

    asyncio.run(run())


def test_cors_preflight_bypasses_proxy_guard(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cloudflare")
    monkeypatch.setenv("API_PROXY_SECRET", "")
    response = client.options(
        "/api/chart", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
