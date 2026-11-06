"""The automatic merge boundary rejects stale, forged, and sensitive fixes."""

from copy import deepcopy

import pytest

from scripts import sentry_autofix as policy


def file_change(name, **overrides):
    return {
        "filename": name,
        "status": "modified",
        "additions": 3,
        "deletions": 0,
        "patch": "@@ -1,1 +1,4 @@\n+def test_regression():\n+    assert True",
        **overrides,
    }


def allowed_files():
    return [file_change("api/serializers.py"), file_change("tests/test_serializers.py")]


def metadata():
    pr = {
        "state": "open",
        "draft": False,
        "user": {"id": policy.SENTRY_BOT_ID, "type": "Bot"},
        "head": {"repo": {"id": policy.REPOSITORY_ID}, "sha": "head"},
        "base": {"repo": {"id": policy.REPOSITORY_ID}, "ref": "main", "sha": "base"},
        "body": "Fix https://twinleaf.sentry.io/issues/12345/",
        "mergeable": True,
        "mergeable_state": "clean",
    }
    run = {
        "event": "pull_request",
        "conclusion": "success",
        "path": ".github/workflows/ci.yml",
        "head_sha": "head",
        "head_repository": {"id": policy.REPOSITORY_ID},
    }
    jobs = [{"name": name, "conclusion": "success"} for name in sorted(policy.REQUIRED_JOBS)]
    return pr, run, jobs


def test_small_fix_with_additive_test_is_allowed():
    policy.qualify_files(allowed_files())
    policy.qualify_metadata(*metadata(), "base")


@pytest.mark.parametrize(
    "name",
    [
        "api/routers/auth.py",
        "api/position_risk.py",
        "portfolio/optimizer.py",
        "migrations/versions/new.py",
        "frontend/package.json",
        ".github/workflows/ci.yml",
        "scripts/sentry_autofix.py",
        "tests/conftest.py",
        "frontend/tests/smoke/fixtures.ts",
        "frontend/src/lib/api.ts",
        "frontend/src/components/auth/ProtectedRoute.tsx",
        "frontend/src/pages/Workspace.tsx",
        "infra/gcp/deploy-api.sh",
        "api/observability.py",
    ],
)
def test_sensitive_or_unknown_path_needs_review(name):
    with pytest.raises(policy.NotQualified):
        policy.qualify_files([*allowed_files(), file_change(name)])


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "renamed", "previous_filename": "api/routers/auth.py"},
        {"status": "removed"},
        {"patch": None},
        {"additions": 201},
    ],
)
def test_unsafe_diff_needs_review(overrides):
    files = allowed_files()
    files[0].update(overrides)
    with pytest.raises(policy.NotQualified):
        policy.qualify_files(files)


def test_missing_regression_or_too_many_files_needs_review():
    for files in [allowed_files()[:1], allowed_files() * 3]:
        with pytest.raises(policy.NotQualified):
            policy.qualify_files(files)


@pytest.mark.parametrize(
    "overrides",
    [
        {"deletions": 1},
        {"patch": "+@pytest.mark.skip\n+assert True"},
        {"patch": "+test.only('works', () => { expect(1).toBe(1) })"},
        {"patch": "+# no assertion"},
    ],
)
def test_reduced_or_missing_test_coverage_needs_review(overrides):
    files = allowed_files()
    files[1].update(overrides)
    with pytest.raises(policy.NotQualified):
        policy.qualify_files(files)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p, r, j: p["user"].update(id=123),
        lambda p, r, j: p["user"].update(type="User"),
        lambda p, r, j: p["head"]["repo"].update(id=123),
        lambda p, r, j: p.update(draft=True),
        lambda p, r, j: p.update(state="closed"),
        lambda p, r, j: p.update(mergeable_state="blocked"),
        lambda p, r, j: p.update(body="Fix https://evil.test/issues/123"),
        lambda p, r, j: r.update(head_sha="old"),
        lambda p, r, j: r.update(event="workflow_dispatch"),
        lambda p, r, j: r.update(path=".github/workflows/fake.yml"),
        lambda p, r, j: j.pop(),
        lambda p, r, j: j[0].update(conclusion="skipped"),
        lambda p, r, j: j[0].update(conclusion="failure"),
    ],
)
def test_untrusted_or_incomplete_ci_cannot_merge(mutate):
    pr, run, jobs = deepcopy(metadata())
    mutate(pr, run, jobs)
    with pytest.raises(policy.NotQualified):
        policy.qualify_metadata(pr, run, jobs, "base")


def test_moved_base_is_rejected():
    with pytest.raises(policy.NotQualified):
        policy.qualify_metadata(*metadata(), "new-base")


def test_kill_switch_prevents_api_mutations(monkeypatch):
    monkeypatch.setenv("SENTRY_AUTOFIX_ENABLED", "false")
    with pytest.raises(policy.NotQualified, match="disabled"):
        policy.merge(None, {})


class FakeGitHub:
    def __init__(self):
        pr, run, jobs = metadata()
        pr.update(number=7, changed_files=2)
        self.responses = {
            "actions/runs/1": run,
            "pulls/7": pr,
            "git/ref/heads/main": {"object": {"sha": "base"}},
            "actions/workflows/ci.yml/runs?head_sha=head&event=pull_request&per_page=1": {"workflow_runs": [{"id": 1}]},
            "compare/base...head": {"behind_by": 0, "status": "ahead"},
            "git/trees/head?recursive=1": {
                "tree": [{"path": f["filename"], "mode": "100644"} for f in allowed_files()]
            },
            "deployments?environment=sentry-autofix&per_page=1": [],
            "commits/head/pulls": [pr],
            "actions/runs/1/jobs?filter=latest": jobs,
            "pulls/7/files": allowed_files(),
            "pulls/7/reviews": [],
        }

    def request(self, path):
        return self.responses[path]

    def pages(self, path, key=None):
        return self.responses[path]


def test_complete_candidate_binds_base_head_and_run():
    assert policy.candidate(FakeGitHub(), 1) == {"pr": 7, "head": "head", "base": "base", "run_id": 1}


@pytest.mark.parametrize(
    "path,value",
    [
        ("actions/workflows/ci.yml/runs?head_sha=head&event=pull_request&per_page=1", {"workflow_runs": [{"id": 2}]}),
        ("compare/base...head", {"behind_by": 1, "status": "diverged"}),
        ("git/trees/head?recursive=1", {"truncated": True, "tree": []}),
        ("git/trees/head?recursive=1", {"tree": [{"path": "api/serializers.py", "mode": "120000"}]}),
        ("pulls/7/reviews", [{"user": {"id": 42}, "state": "CHANGES_REQUESTED"}]),
    ],
)
def test_stale_runs_symlinks_or_review_objections_block(path, value):
    api = FakeGitHub()
    api.responses[path] = value
    with pytest.raises(policy.NotQualified):
        policy.candidate(api, 1)


@pytest.mark.parametrize("state", ["pending", "in_progress", "failure", "error", None])
def test_prior_release_needing_attention_blocks_new_merges(state):
    api = FakeGitHub()
    api.responses["deployments?environment=sentry-autofix&per_page=1"] = [{"id": 12}]
    api.responses["deployments/12/statuses?per_page=1"] = [{"state": state}] if state else []
    with pytest.raises(policy.NotQualified, match="Previous automatic"):
        policy.candidate(api, 1)


def test_pr_changed_after_preflight_is_not_merged(monkeypatch):
    monkeypatch.setenv("SENTRY_AUTOFIX_ENABLED", "true")
    api = FakeGitHub()
    expected = {"pr": 7, "head": "previous-head", "base": "base", "run_id": 1}
    with pytest.raises(policy.NotQualified, match="changed after preflight"):
        policy.merge(api, expected)
