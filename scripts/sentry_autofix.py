"""Qualify Sentry PRs using GitHub metadata; never execute the proposed code.

Only the copy of this controller on main is used by the privileged workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPOSITORY = "ShaivPandya/talisman"
REPOSITORY_ID = 1133863807
SENTRY_BOT_ID = 39604003
REQUIRED_JOBS = {
    "lint",
    "test",
    "typecheck",
    "eval-gates",
    "frontend",
    "security-pip-audit",
    "security-npm-audit",
    "security-secret-scan",
    "security-python-sast",
    "security-trivy",
}
SHARED_COMPONENTS = {
    "BoundedTooltip",
    "ChartTile",
    "DataTable",
    "Dialog",
    "FormControls",
    "LoadingSpinner",
    "MarkdownRenderer",
    "MetricCard",
    "Notice",
    "PageHeader",
    "RefreshButton",
    "StatusBadge",
    "SurfaceCard",
    "TimeSeriesChart",
}
APPLICATION_FILES = {
    "api/serializers.py",
    "frontend/src/hooks/useMediaQuery.ts",
    "frontend/src/lib/colors.ts",
    "frontend/src/lib/utils.ts",
    "frontend/src/lib/accentPresets.ts",
    "frontend/src/lib/chunkRecovery.ts",
} | {f"frontend/src/components/shared/{name}.tsx" for name in SHARED_COMPONENTS}
SENTRY_LINK = re.compile(r"https://twinleaf\.sentry\.io/(?:issues|organizations/twinleaf/issues)/\d+")


class NotQualified(Exception):
    """The PR stays open for manual review."""


def require(condition: object, reason: str) -> None:
    if not condition:
        raise NotQualified(reason)


def test_file(name: str) -> bool:
    return bool(re.fullmatch(r"tests/test_[a-z0-9_]+\.py|frontend/tests/smoke/[a-z0-9-]+\.spec\.ts", name))


def qualify_files(files: list[dict]) -> None:
    require(1 < len(files) <= 5, "Requires an application fix and test, within five files.")
    require(sum(f["additions"] + f["deletions"] for f in files) <= 200, "Over 200 changed lines.")
    require(any(f["filename"] in APPLICATION_FILES for f in files), "No approved application file changed.")
    regression = False
    for file in files:
        name = file["filename"]
        require(file["status"] in {"added", "modified"}, "Deleted, renamed, or copied files need review.")
        require(name in APPLICATION_FILES or test_file(name), f"Outside the automatic-fix allowlist: {name}")
        require(bool(file.get("patch")), f"Missing text diff: {name}")
        if test_file(name):
            require(file["deletions"] == 0, "Existing test coverage must not be removed or rewritten.")
            added = "\n".join(line[1:] for line in file["patch"].splitlines() if line.startswith("+"))
            require(not re.search(r"\b(skip|xfail|fixme|only)\b", added), "Test skips or focused tests need review.")
            regression |= bool(re.search(r"\bassert\b|\bexpect\(", added))
    require(regression, "An added regression assertion is required.")


def qualify_metadata(pr: dict, run: dict, jobs: list[dict], base_sha: str) -> None:
    require(pr["state"] == "open" and not pr["draft"], "PR is closed or draft.")
    require(pr["user"]["id"] == SENTRY_BOT_ID and pr["user"]["type"] == "Bot", "PR was not created by Sentry.")
    require(pr["head"]["repo"]["id"] == REPOSITORY_ID, "Fork PRs require review.")
    require(
        pr["base"]["repo"]["id"] == REPOSITORY_ID and pr["base"]["ref"] == "main", "Wrong target repository or branch."
    )
    require(SENTRY_LINK.search(pr.get("body") or ""), "PR must link a Twinleaf Sentry issue.")
    require(pr["base"]["sha"] == base_sha, "Base branch changed; fresh CI is required.")
    require(
        pr.get("mergeable") is True and pr.get("mergeable_state") == "clean",
        "GitHub has not confirmed a clean, permitted merge.",
    )
    require(run["event"] == "pull_request" and run["conclusion"] == "success", "Requires successful pull-request CI.")
    require(run["path"] == ".github/workflows/ci.yml", "Unexpected CI workflow.")
    require(run["head_sha"] == pr["head"]["sha"], "CI does not cover the current PR head.")
    require(run["head_repository"]["id"] == REPOSITORY_ID, "CI ran in a different repository.")
    actual = {job["name"]: job for job in jobs}
    require(REQUIRED_JOBS <= actual.keys(), "One or more required CI jobs are missing.")
    require(all(job["conclusion"] == "success" for job in jobs), "A CI job failed, was cancelled, or was skipped.")


class GitHub:
    def request(self, path: str, data: dict | None = None, method: str | None = None):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{REPOSITORY}/{path}",
            data=json.dumps(data).encode() if data is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.load(response)

    def pages(self, path: str, key: str | None = None) -> list:
        result = []
        for page in range(1, 32):
            separator = "&" if "?" in path else "?"
            response = self.request(f"{path}{separator}per_page=100&page={page}")
            items = response[key] if key else response
            result.extend(items)
            if len(items) < 100:
                return result
        raise NotQualified("Too many results to safely qualify automatically.")


def candidate(api: GitHub, run_id: int) -> dict:
    run = api.request(f"actions/runs/{run_id}")
    require(run["event"] == "pull_request", "This CI run was not triggered by a pull request.")
    prs = api.pages(f"commits/{run['head_sha']}/pulls")
    prs = [pr for pr in prs if pr["state"] == "open" and pr["base"]["ref"] == "main"]
    require(len(prs) == 1, "Expected one open PR for the tested commit.")
    pr = api.request(f"pulls/{prs[0]['number']}")
    base_sha = api.request("git/ref/heads/main")["object"]["sha"]
    jobs = api.pages(f"actions/runs/{run_id}/jobs?filter=latest", "jobs")
    qualify_metadata(pr, run, jobs, base_sha)
    latest = api.request(f"actions/workflows/ci.yml/runs?head_sha={pr['head']['sha']}&event=pull_request&per_page=1")
    require(latest["workflow_runs"][0]["id"] == run_id, "A newer CI run exists.")
    comparison = api.request(f"compare/{base_sha}...{pr['head']['sha']}")
    require(
        comparison["behind_by"] == 0 and comparison["status"] == "ahead", "Update the PR branch from main and rerun CI."
    )
    files = api.pages(f"pulls/{pr['number']}/files")
    require(len(files) == pr["changed_files"], "Incomplete PR file list.")
    qualify_files(files)
    tree = api.request(f"git/trees/{pr['head']['sha']}?recursive=1")
    require(not tree.get("truncated"), "Cannot verify all file modes.")
    modes = {item["path"]: item["mode"] for item in tree["tree"]}
    require(all(modes.get(file["filename"]) == "100644" for file in files), "Symlinks or executable files need review.")
    reviews = api.pages(f"pulls/{pr['number']}/reviews")
    latest_reviews = {}
    for review in reviews:
        if review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest_reviews[review["user"]["id"]] = review["state"]
    require("CHANGES_REQUESTED" not in latest_reviews.values(), "A reviewer has requested changes.")
    deployments = api.request("deployments?environment=sentry-autofix&per_page=1")
    if deployments:
        statuses = api.request(f"deployments/{deployments[0]['id']}/statuses?per_page=1")
        require(
            statuses and statuses[0]["state"] in {"success", "inactive"},
            "Previous automatic deployment needs attention.",
        )
    return {"pr": pr["number"], "head": pr["head"]["sha"], "base": base_sha, "run_id": run_id}


def output(**values) -> None:
    if path := os.environ.get("GITHUB_OUTPUT"):
        with Path(path).open("a") as file:
            for key, value in values.items():
                file.write(f"{key}={value}\n")


def merge(api: GitHub, expected: dict) -> None:
    require(os.environ.get("SENTRY_AUTOFIX_ENABLED") == "true", "Automatic shipping is disabled.")
    current = candidate(api, expected["run_id"])
    require(current == expected, "PR or base changed after preflight.")
    deployment = api.request(
        "deployments",
        {
            "ref": current["head"],
            "environment": "sentry-autofix",
            "auto_merge": False,
            "required_contexts": [],
            "production_environment": True,
            "description": f"Sentry fix PR #{current['pr']}",
            "payload": current,
        },
    )
    output(deployment_id=deployment["id"])
    result = api.request(
        f"pulls/{current['pr']}/merge",
        {
            "sha": current["head"],
            "merge_method": "squash",
            "commit_title": f"Fix Sentry issue (#{current['pr']})",
        },
        method="PUT",
    )
    require(result.get("merged"), "GitHub rejected the merge.")
    output(merged_sha=result["sha"])
    print(f"Merged PR #{current['pr']} at {result['sha']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--candidate", type=Path, default=Path("candidate.json"))
    parser.add_argument("--merge", action="store_true")
    args = parser.parse_args()
    api = GitHub()
    try:
        if args.merge:
            merge(api, json.loads(args.candidate.read_text()))
        else:
            require(args.run_id, "No CI run supplied.")
            data = candidate(api, args.run_id)
            args.candidate.write_text(json.dumps(data))
            output(qualified="true", base_sha=data["base"])
            print(f"PR #{data['pr']} meets the automatic-fix policy.")
    except NotQualified as error:
        print(f"Manual review required: {error}")
        output(qualified="false")
        return 1 if args.merge else 0
    except urllib.error.HTTPError as error:
        print(f"GitHub API returned HTTP {error.code}; no qualification granted.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
