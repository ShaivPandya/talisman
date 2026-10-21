"""Tests for authentication flow — login, logout, session validation, CSRF."""

import pytest


@pytest.fixture(autouse=True)
def _reset_login_attempt_state():
    from api.routers import auth as auth_router

    auth_router._reset_login_attempt_state()
    yield
    auth_router._reset_login_attempt_state()


def test_login_success(client):
    resp = client.post("/api/auth/login", json={"password": "testpass"})
    assert resp.status_code == 200
    assert resp.json()["detail"] == "ok"
    assert resp.json()["username"] == "admin"
    assert resp.json()["csrfToken"]
    assert "__session" in resp.cookies


def test_login_wrong_password(client):
    resp = client.post("/api/auth/login", json={"password": "wrongpassword"})
    assert resp.status_code == 401


def test_login_missing_password(client):
    resp = client.post("/api/auth/login", json={})
    assert resp.status_code == 422


def test_logout(auth_client):
    resp = auth_client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"detail": "ok"}


def test_me_unauthenticated(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_authenticated(auth_client):
    resp = auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "admin"
    assert "admin" in body["roles"]
    assert body["csrfToken"]


def test_health_no_auth_required(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_public_health_is_diagnostic_safe(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    text = resp.text.lower()
    for forbidden in ("fred", "sqlite", "traceback", "/users/", "error:"):
        assert forbidden not in text


def test_admin_health_requires_auth(client, monkeypatch):
    from fastapi.responses import JSONResponse

    import api.main as main

    monkeypatch.setattr(main, "_detailed_health_response", lambda: JSONResponse({"status": "ok", "checks": {}}))

    unauthenticated = client.get("/api/admin/health")
    assert unauthenticated.status_code == 401

    login = client.post("/api/auth/login", json={"password": "testpass"})
    assert login.status_code == 200
    client._csrf_token = login.json()["csrfToken"]  # type: ignore[attr-defined]
    authenticated = client.get("/api/admin/health")
    assert authenticated.status_code in {200, 503}
    assert "checks" in authenticated.json()


def test_openapi_moved_under_api_prefix_in_development(client):
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/openapi.json").status_code == 404


def test_production_docs_and_schema_are_disabled(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")

    for path in ("/api/openapi.json", "/api/docs", "/api/redoc"):
        resp = client.get(path)
        assert resp.status_code == 404


def test_global_request_body_limit_rejects_large_json_before_login_parse(client, monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "64")

    resp = client.post("/api/auth/login", json={"password": "x" * 100})
    assert resp.status_code == 413


def test_login_password_length_is_limited(client):
    resp = client.post("/api/auth/login", json={"password": "x" * 513})
    assert resp.status_code == 422


def test_repeated_bad_logins_lock_out_client(client, monkeypatch):
    from api.routers import auth as auth_router

    now = [1_000.0]
    monkeypatch.setenv("AUTH_LOGIN_FAILURE_LIMIT", "2")
    monkeypatch.setenv("AUTH_LOGIN_FAILURE_WINDOW_SECONDS", "300")
    monkeypatch.setenv("AUTH_LOGIN_LOCKOUT_SECONDS", "60")
    monkeypatch.setattr(auth_router.time, "time", lambda: now[0])

    first = client.post("/api/auth/login", json={"password": "wrong"})
    second = client.post("/api/auth/login", json={"password": "wrong"})
    correct_while_locked = client.post("/api/auth/login", json={"password": "testpass"})

    assert first.status_code == 401
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"
    assert correct_while_locked.status_code == 429

    now[0] += 61
    allowed_after_lockout = client.post("/api/auth/login", json={"password": "testpass"})
    assert allowed_after_lockout.status_code == 200


def test_successful_login_clears_failed_login_counter(client, monkeypatch):
    monkeypatch.setenv("AUTH_LOGIN_FAILURE_LIMIT", "2")
    monkeypatch.setenv("AUTH_LOGIN_FAILURE_WINDOW_SECONDS", "300")
    monkeypatch.setenv("AUTH_LOGIN_LOCKOUT_SECONDS", "60")

    failed = client.post("/api/auth/login", json={"password": "wrong"})
    success = client.post("/api/auth/login", json={"password": "testpass"})
    failed_after_success = client.post("/api/auth/login", json={"password": "wrong"})

    assert failed.status_code == 401
    assert success.status_code == 200
    assert failed_after_success.status_code == 401


def test_password_mode_does_not_require_proxy_secret_for_login(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.setenv("API_PROXY_SECRET", "proxy-secret")
    monkeypatch.delenv("REQUIRE_API_PROXY_SECRET", raising=False)

    resp = client.post("/api/auth/login", json={"password": "testpass"})
    assert resp.status_code == 200


def test_explicit_proxy_secret_requirement_blocks_missing_header(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.setenv("API_PROXY_SECRET", "proxy-secret")
    monkeypatch.setenv("REQUIRE_API_PROXY_SECRET", "true")

    missing = client.post("/api/auth/login", json={"password": "testpass"})
    assert missing.status_code == 403

    allowed = client.post(
        "/api/auth/login",
        json={"password": "testpass"},
        headers={"X-Api-Proxy-Secret": "proxy-secret"},
    )
    assert allowed.status_code == 200


def test_cloudflare_mode_requires_backend_proxy_secret(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cloudflare")
    monkeypatch.delenv("API_PROXY_SECRET", raising=False)

    protected = client.get("/api/agent/workflows")
    assert protected.status_code == 403
    assert protected.json() == {"detail": "API proxy secret is required for this auth mode."}

    health = client.get("/api/health")
    assert health.status_code == 200


def test_cloudflare_mode_enforces_proxy_secret_and_identity(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cloudflare")
    monkeypatch.setenv("API_PROXY_SECRET", "proxy-secret")

    missing = client.get("/api/agent/workflows")
    assert missing.status_code == 403

    missing_identity = client.get(
        "/api/agent/workflows",
        headers={"X-Api-Proxy-Secret": "proxy-secret"},
    )
    assert missing_identity.status_code == 401

    allowed = client.get(
        "/api/agent/workflows",
        headers={
            "X-Api-Proxy-Secret": "proxy-secret",
            "Cf-Access-Authenticated-User-Email": "operator@example.com",
        },
    )
    assert allowed.status_code == 200


def test_csrf_required_for_mutating_session_requests(client):
    login = client.post("/api/auth/login", json={"password": "testpass"})
    assert login.status_code == 200
    session_cookie = login.cookies.get("__session")
    assert session_cookie

    blocked = client.post(
        "/api/auth/logout",
        cookies={"__session": session_cookie},
    )
    assert blocked.status_code == 403

    allowed = client.post(
        "/api/auth/logout",
        cookies={"__session": session_cookie},
        headers={"X-CSRF-Token": login.json()["csrfToken"]},
    )
    assert allowed.status_code == 200


def test_me_rotates_csrf_in_one_auth_statement(auth_client):
    from api import auth_store

    statements = []
    with auth_store._get_conn() as conn:
        conn.set_trace_callback(lambda sql: statements.append(sql) if "auth_sessions" in sql else None)
    try:
        previous_csrf = auth_client._csrf_token
        response = auth_client.get("/api/auth/me")
        assert response.status_code == 200
        assert len(statements) == 1
        new_csrf = response.json()["csrfToken"]
        assert new_csrf != previous_csrf
        assert auth_client.post("/api/auth/logout", headers={"X-CSRF-Token": previous_csrf}).status_code == 403
        assert auth_client.post("/api/auth/logout", headers={"X-CSRF-Token": new_csrf}).status_code == 200
    finally:
        conn.set_trace_callback(None)


def test_read_and_mutation_auth_budgets_and_request_reuse(auth_client):
    from typing import Annotated

    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from api import auth_store
    from api.main import _csrf_middleware
    from api.routers.auth import require_actor, require_auth
    from ontology.policy import Actor

    app = FastAPI()
    app.middleware("http")(_csrf_middleware)

    @app.api_route("/api/auth-budget", methods=["GET", "POST"])
    def endpoint(username: Annotated[str, Depends(require_auth)], actor: Annotated[Actor, Depends(require_actor)]):
        return {"username": username, "roles": list(actor.roles)}

    test_client = TestClient(app, cookies=auth_client.cookies)
    statements = []
    with auth_store._get_conn() as conn:
        conn.set_trace_callback(lambda sql: statements.append(sql) if "FROM auth_sessions" in sql else None)
    try:
        assert test_client.get("/api/auth-budget").status_code == 200
        assert len(statements) == 1
        statements.clear()
        assert test_client.get("/api/auth-budget").status_code == 200
        assert statements == []
        response = test_client.post("/api/auth-budget", headers={"X-CSRF-Token": auth_client._csrf_token})
        assert response.status_code == 200
        assert len(statements) == 1
    finally:
        conn.set_trace_callback(None)


@pytest.mark.parametrize("path", ["/api/admin/health", "/api/approvals", "/api/provenance/trace", "/api/policy-gate"])
def test_sensitive_reads_bypass_cached_session(auth_client, path):
    from fastapi import HTTPException
    from starlette.requests import Request

    from api import auth_store
    from api.routers.auth import _resolve_session_user

    session_token = auth_client.cookies.get("__session")
    assert auth_store.lookup_session(session_token) is not None
    # Simulate revocation by another instance, without local cache invalidation.
    with auth_store._get_conn() as conn:
        conn.execute("UPDATE auth_sessions SET revoked_at = ?", (auth_store._now(),))
        conn.commit()
    request = Request({"type": "http", "method": "GET", "path": path, "headers": []})
    with pytest.raises(HTTPException) as exc:
        _resolve_session_user(request, session_token)
    assert exc.value.status_code == 401


def test_csrf_validation_and_denial_audit_leave_event_loop_responsive(monkeypatch):
    import asyncio
    import threading

    from starlette.requests import Request

    import api.main as main

    entered = threading.Event()
    release = threading.Event()
    worker_threads = []

    def verify(request):
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(2), "CSRF validation blocked the event loop"
        return False

    def audit(*args, **kwargs):
        worker_threads.append(threading.get_ident())

    monkeypatch.setattr(main, "verify_request_csrf", verify)
    monkeypatch.setattr(main, "emit_audit_event", audit)
    monkeypatch.setattr(main, "is_machine_authenticated_request", lambda request: False)

    async def run():
        loop_thread = threading.get_ident()
        request = Request({"type": "http", "method": "POST", "path": "/api/portfolio", "headers": []})

        async def next_handler(request):
            raise AssertionError("invalid CSRF must not reach the route")

        task = asyncio.create_task(main._csrf_middleware(request, next_handler))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 1), 1.5)
            release.set()
            response = await task
            assert response.status_code == 403
            assert len(worker_threads) == 2 and loop_thread not in worker_threads
        finally:
            release.set()
            await task

    asyncio.run(run())


def test_smoke_password_login_succeeds_when_hash_configured(client, monkeypatch):
    import bcrypt

    smoke_pw = "smoke-test-password"
    smoke_hash = bcrypt.hashpw(smoke_pw.encode(), bcrypt.gensalt(12)).decode()
    monkeypatch.setenv("AUTH_SMOKE_PASSWORD_HASH", smoke_hash)
    from api.auth_store import reset_auth_store_for_tests

    reset_auth_store_for_tests()

    resp = client.post("/api/auth/login", json={"password": smoke_pw, "username": "smoke"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "smoke"
    assert "__session" in resp.cookies


def test_smoke_password_creates_smoke_subject(client, monkeypatch):
    import bcrypt

    smoke_pw = "smoke-test-password"
    smoke_hash = bcrypt.hashpw(smoke_pw.encode(), bcrypt.gensalt(12)).decode()
    monkeypatch.setenv("AUTH_SMOKE_PASSWORD_HASH", smoke_hash)
    from api.auth_store import reset_auth_store_for_tests

    reset_auth_store_for_tests()

    resp = client.post("/api/auth/login", json={"password": smoke_pw, "username": "smoke"})
    assert resp.status_code == 200
    client._csrf_token = resp.json()["csrfToken"]  # type: ignore[attr-defined]
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "smoke"


def test_admin_login_still_works_with_smoke_hash_configured(client, monkeypatch):
    import bcrypt

    smoke_pw = "different-smoke-password"
    smoke_hash = bcrypt.hashpw(smoke_pw.encode(), bcrypt.gensalt(12)).decode()
    monkeypatch.setenv("AUTH_SMOKE_PASSWORD_HASH", smoke_hash)
    from api.auth_store import reset_auth_store_for_tests

    reset_auth_store_for_tests()

    resp = client.post("/api/auth/login", json={"password": "testpass"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_admin_login_subject_is_admin(client, monkeypatch):
    monkeypatch.delenv("AUTH_SMOKE_PASSWORD_HASH", raising=False)
    from api.auth_store import reset_auth_store_for_tests

    reset_auth_store_for_tests()

    resp = client.post("/api/auth/login", json={"password": "testpass"})
    assert resp.status_code == 200
    client._csrf_token = resp.json()["csrfToken"]  # type: ignore[attr-defined]
    me = client.get("/api/auth/me")
    assert me.json()["username"] == "admin"


def test_no_smoke_login_when_hash_absent(client, monkeypatch):
    monkeypatch.delenv("AUTH_SMOKE_PASSWORD_HASH", raising=False)
    from api.auth_store import reset_auth_store_for_tests

    reset_auth_store_for_tests()

    resp = client.post("/api/auth/login", json={"password": "some-random-password", "username": "smoke"})
    assert resp.status_code == 401


def test_wrong_smoke_password_rejected(client, monkeypatch):
    import bcrypt

    smoke_pw = "smoke-test-password"
    smoke_hash = bcrypt.hashpw(smoke_pw.encode(), bcrypt.gensalt(12)).decode()
    monkeypatch.setenv("AUTH_SMOKE_PASSWORD_HASH", smoke_hash)
    from api.auth_store import reset_auth_store_for_tests

    reset_auth_store_for_tests()

    resp = client.post("/api/auth/login", json={"password": "totally-wrong", "username": "smoke"})
    assert resp.status_code == 401
