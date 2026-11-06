"""Deployment failure restores the previous resources and stops the release."""

import subprocess

import pytest

from scripts import sentry_autofix_deploy as deploy


@pytest.fixture
def environment(monkeypatch):
    for name in ["PROJECT_ID", "REGION", "ARTIFACT_REPO", "IMAGE_NAME", "AUTOFIX_BUILD_SA", "AUTOFIX_BUILD_BUCKET"]:
        monkeypatch.setenv(name, "test")


def test_application_drift_blocks_before_merge(monkeypatch):
    monkeypatch.setattr(
        deploy,
        "service",
        lambda: {
            "spec": {
                "template": {"spec": {"containers": [{"env": [{"name": "TALISMAN_RELEASE_GIT_SHA", "value": "old"}]}]}}
            }
        },
    )
    monkeypatch.setattr(deploy, "run", lambda *args, **kw: "api/routers/auth.py" if "diff" in args else "")
    with pytest.raises(RuntimeError, match="baseline separately"):
        deploy.preflight("new")


def test_wrong_checkout_never_deploys(monkeypatch, environment):
    monkeypatch.setattr(deploy, "run", lambda *args, **kw: "wrong")
    with pytest.raises(RuntimeError, match="Checkout"):
        deploy.ship("sha")


@pytest.mark.parametrize("failure", ["service-update", "smoke", "frontend"])
def test_failure_restores_all_changed_resources(monkeypatch, environment, failure):
    calls = []
    firebase_calls = []
    monkeypatch.setattr(deploy, "resources", lambda: [("jobs", "worker"), ("services", "api")])

    def fake_run(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("git", "rev-parse"):
            return "sha"
        if "run-backend-smoke.sh" in " ".join(args) and failure == "smoke":
            raise subprocess.CalledProcessError(1, args)
        if "deploy-frontend.sh" in " ".join(args) and failure == "frontend":
            raise subprocess.CalledProcessError(1, args)
        return ""

    def fake_gcloud(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("run", "services", "update") and failure == "service-update":
            raise subprocess.CalledProcessError(1, args)
        return "kind: snapshot"

    def fake_firebase(path, data=None):
        firebase_calls.append((path, data))
        return {"releases": [{"version": {"name": "sites/test/versions/prior"}}]}

    monkeypatch.setattr(deploy, "run", fake_run)
    monkeypatch.setattr(deploy, "gcloud", fake_gcloud)
    monkeypatch.setattr(deploy, "firebase", fake_firebase)
    with pytest.raises(subprocess.CalledProcessError):
        deploy.ship("sha")
    restores = [args for args in calls if len(args) > 2 and args[2] == "replace"]
    assert [args[1] for args in restores] == ["services", "jobs"]
    assert all("migrations" not in " ".join(args) for args in calls)
    assert (len(firebase_calls) == 2) == (failure == "frontend")
    if failure == "frontend":
        assert "prior" in firebase_calls[-1][0]
