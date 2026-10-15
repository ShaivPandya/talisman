"""Tests for the deploy smoke CLI (infra/gcp/deploy_smoke.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from infra.gcp.deploy_smoke import (
    CheckResult,
    check_admin_deploy_smoke,
    check_approvals_summary,
    check_health,
    check_login,
    check_me,
    check_viewer_denied,
    check_workspace,
    main,
    print_results,
    run_smoke,
)


class FakeResponse:
    """Minimal httpx.Response stand-in."""

    def __init__(self, status_code: int = 200, body: dict | None = None, cookies: dict | None = None):
        self.status_code = status_code
        self._body = body or {}
        self._cookies = cookies or {}
        self.cookies = self._cookies

    def json(self) -> dict:
        return self._body


# ---------------------------------------------------------------------------
# check_health
# ---------------------------------------------------------------------------


def test_check_health_ok():
    client = MagicMock()
    client.get.return_value = FakeResponse(200, {"status": "ok", "release": {"image_tag": "abc123"}})
    result = check_health(client, "abc123")
    assert result.passed


def test_check_health_tag_mismatch():
    client = MagicMock()
    client.get.return_value = FakeResponse(200, {"status": "ok", "release": {"image_tag": "old"}})
    result = check_health(client, "abc123")
    assert not result.passed
    assert "mismatch" in result.detail


def test_check_health_no_expected_tag():
    client = MagicMock()
    client.get.return_value = FakeResponse(200, {"status": "ok"})
    result = check_health(client, None)
    assert result.passed


def test_check_health_bad_status():
    client = MagicMock()
    client.get.return_value = FakeResponse(503, {"status": "unhealthy"})
    result = check_health(client, None)
    assert not result.passed


# ---------------------------------------------------------------------------
# check_login
# ---------------------------------------------------------------------------


def test_check_login_ok():
    client = MagicMock()
    client.post.return_value = FakeResponse(
        200,
        {"detail": "ok", "csrfToken": "csrf-tok"},
        cookies={"__session": "tok"},
    )
    result, cookies, headers = check_login(client, "smoke-pw")
    assert result.passed
    assert cookies.get("__session") == "tok"
    assert headers.get("X-CSRF-Token") == "csrf-tok"


def test_check_login_401():
    client = MagicMock()
    client.post.return_value = FakeResponse(401, {"detail": "Incorrect password"}, cookies={})
    result, cookies, headers = check_login(client, "bad-pw")
    assert not result.passed
    assert not cookies
    assert not headers


def test_login_sends_production_request_schema(monkeypatch):
    monkeypatch.setenv("AUTH_DEFAULT_USERNAME", "smoke")

    def handle(request: httpx.Request) -> httpx.Response:
        if (
            request.headers.get("X-Request-Schema-Name") != "post:/api/auth/login"
            or request.headers.get("X-Request-Schema-Version") != "1"
        ):
            return httpx.Response(400, json={"detail": "Missing request schema headers"})
        return httpx.Response(200, json={"csrfToken": "csrf-tok"}, headers={"set-cookie": "__session=tok; Path=/"})

    with httpx.Client(base_url="https://test", transport=httpx.MockTransport(handle)) as client:
        result, cookies, _ = check_login(client, "smoke-pw")
    assert result.passed
    assert cookies == {"__session": "tok"}


# ---------------------------------------------------------------------------
# check_me
# ---------------------------------------------------------------------------


def test_check_me_ok():
    client = MagicMock()
    client.get.return_value = FakeResponse(200, {"username": "smoke"})
    result = check_me(client, {"__session": "tok"})
    assert result.passed


def test_check_me_401():
    client = MagicMock()
    client.get.return_value = FakeResponse(401)
    result = check_me(client, {})
    assert not result.passed


@pytest.mark.parametrize("roles", [[], ["admin"], ["viewer", "owner"], ["viewer", "admin"]])
def test_viewer_profile_rejects_missing_or_elevated_roles(roles):
    client = MagicMock()
    client.get.return_value = FakeResponse(200, {"username": "smoke", "roles": roles})
    assert not check_me(client, {"__session": "tok"}, "viewer").passed


@pytest.mark.parametrize("status", [200, 401, 500])
def test_viewer_denial_requires_authenticated_403(status):
    client = MagicMock()
    client.get.return_value = FakeResponse(status)
    assert not check_viewer_denied(client, {}, "/api/admin/deploy-smoke", "admin_viewer_denied").passed


# ---------------------------------------------------------------------------
# check_workspace
# ---------------------------------------------------------------------------


def test_check_workspace_ok():
    client = MagicMock()
    body = {"regime": None, "portfolio": None, "pending_approvals": {}, "recommendations": {}}
    client.get.return_value = FakeResponse(200, body)
    result = check_workspace(client, {"__session": "tok"})
    assert result.passed


def test_check_workspace_missing_keys():
    client = MagicMock()
    client.get.return_value = FakeResponse(200, {"regime": None})
    result = check_workspace(client, {"__session": "tok"})
    assert not result.passed
    assert "missing keys" in result.detail


# ---------------------------------------------------------------------------
# check_approvals_summary
# ---------------------------------------------------------------------------


def test_check_approvals_summary_ok():
    client = MagicMock()
    client.get.return_value = FakeResponse(200, {"count": 0, "items": []})
    result = check_approvals_summary(client, {"__session": "tok"})
    assert result.passed


def test_check_approvals_summary_missing_keys():
    client = MagicMock()
    client.get.return_value = FakeResponse(200, {"total": 0})
    result = check_approvals_summary(client, {"__session": "tok"})
    assert not result.passed


# ---------------------------------------------------------------------------
# check_admin_deploy_smoke
# ---------------------------------------------------------------------------


def test_check_admin_deploy_smoke_ok():
    client = MagicMock()
    client.get.return_value = FakeResponse(200, {"checks": {}})
    result = check_admin_deploy_smoke(client, {"__session": "tok"})
    assert result.passed


def test_check_admin_deploy_smoke_503():
    client = MagicMock()
    client.get.return_value = FakeResponse(503, {"checks": {}, "failed_checks": ["postgres", "migration_head"]})
    result = check_admin_deploy_smoke(client, {"__session": "tok"})
    assert not result.passed
    assert "postgres" in result.detail


# ---------------------------------------------------------------------------
# run_smoke integration
# ---------------------------------------------------------------------------


def test_run_smoke_requires_password():
    with pytest.raises(ValueError, match="AUTH_SMOKE_PASSWORD"):
        run_smoke("http://test", "post-deploy", smoke_password="")


def test_run_smoke_all_pass():
    """All checks should pass with a fully healthy mock."""
    with patch("infra.gcp.deploy_smoke._client") as mock_client_fn:
        client = MagicMock()
        mock_client_fn.return_value = client

        healthy_body = {"status": "ok", "release": {"image_tag": "abc"}}
        client.get.side_effect = lambda path, **kw: {
            "/api/health": FakeResponse(200, healthy_body),
            "/api/auth/me": FakeResponse(200, {"username": "smoke"}),
            "/api/workspace": FakeResponse(
                200,
                {"regime": None, "portfolio": None, "pending_approvals": {}},
            ),
            "/api/approvals/summary?limit=1": FakeResponse(200, {"count": 0, "items": []}),
            "/api/admin/deploy-smoke": FakeResponse(200, {"checks": {}}),
        }.get(path, FakeResponse(404))

        client.post.return_value = FakeResponse(200, {"detail": "ok"}, cookies={"__session": "tok"})

        results = run_smoke(
            "http://test",
            "post-deploy",
            expected_image_tag="abc",
            smoke_password="smoke-pw",
        )

        assert all(r.passed for r in results), [r for r in results if not r.passed]


def test_run_smoke_viewer_verifies_privilege_boundaries():
    responses = {
        "/api/health": FakeResponse(200, {"status": "ok", "release": {"image_tag": "abc"}}),
        "/api/auth/me": FakeResponse(200, {"username": "smoke", "roles": ["smoke", "viewer"]}),
        "/api/workspace": FakeResponse(200, {"regime": None, "portfolio": None, "pending_approvals": {}}),
        "/api/approvals/summary?limit=1": FakeResponse(403),
        "/api/admin/deploy-smoke": FakeResponse(403),
    }
    with patch("infra.gcp.deploy_smoke._client") as mock_client_fn:
        client = mock_client_fn.return_value
        client.get.side_effect = lambda path, **kw: responses[path]
        client.post.return_value = FakeResponse(200, cookies={"__session": "tok"})
        results = run_smoke("http://test", "post-deploy", "abc", smoke_password="smoke-pw", auth_profile="viewer")
    assert len(results) == 6
    assert all(result.passed and result.required for result in results)
    assert {result.name for result in results} >= {"approvals_viewer_denied", "admin_viewer_denied"}


def test_default_admin_profile_rejects_privileged_denials():
    with patch("infra.gcp.deploy_smoke._client") as mock_client_fn:
        client = mock_client_fn.return_value
        client.post.return_value = FakeResponse(200, cookies={"__session": "tok"})
        client.get.return_value = FakeResponse(403)
        results = run_smoke("http://test", "post-deploy", smoke_password="smoke-pw")
    assert not next(result for result in results if result.name == "admin_deploy_smoke").passed
    assert not next(result for result in results if result.name == "approvals_summary").passed


# ---------------------------------------------------------------------------
# print_results
# ---------------------------------------------------------------------------


def test_print_results_all_pass(capsys):
    results = [CheckResult("health", True, "ok")]
    assert print_results(results, "post-deploy") is True
    captured = capsys.readouterr()
    assert "PASSED" in captured.out


def test_print_results_failure(capsys):
    results = [CheckResult("health", False, "bad")]
    assert print_results(results, "post-deploy") is False
    captured = capsys.readouterr()
    assert "FAILED" in captured.out


def test_print_results_redacts_secrets(capsys):
    results = [CheckResult("login", False, "password=leaked")]
    print_results(results, "post-deploy")
    captured = capsys.readouterr()
    assert "leaked" not in captured.out
    assert "REDACTED" in captured.out


# ---------------------------------------------------------------------------
# CLI main
# ---------------------------------------------------------------------------


def test_cli_missing_password(monkeypatch):
    monkeypatch.delenv("AUTH_SMOKE_PASSWORD", raising=False)
    monkeypatch.delenv("API_PROXY_SECRET", raising=False)
    code = main(["--service-url", "http://test", "--mode", "post-deploy"])
    assert code == 1


def test_cli_passes_explicit_viewer_profile(monkeypatch):
    monkeypatch.setenv("AUTH_SMOKE_PASSWORD", "smoke-pw")
    with patch("infra.gcp.deploy_smoke.run_smoke", return_value=[]) as runner:
        assert main(["--service-url", "http://test", "--auth-profile", "viewer"]) == 0
    assert runner.call_args.kwargs["auth_profile"] == "viewer"
