"""Deploy a qualified fix, preserve live configuration, and restore on failure."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def gcloud(*args: str, capture: bool = False) -> str:
    return run("gcloud", *args, f"--project={os.environ['PROJECT_ID']}", "--quiet", capture=capture)


def resources() -> list[tuple[str, str]]:
    return [
        ("services", os.environ["API_SERVICE"]),
        ("jobs", os.environ["ASYNC_JOB_RUNNER_JOB"]),
        ("jobs", os.environ["TOP50_REFRESH_JOB"]),
        ("worker-pools", os.environ["AGENT_WORKER_POOL"]),
        ("worker-pools", os.environ["ANALYZER_WORKER_POOL"]),
        ("worker-pools", os.environ["ONTOLOGY_WORKER_POOL"]),
    ]


def service() -> dict:
    return json.loads(
        gcloud(
            "run",
            "services",
            "describe",
            os.environ["API_SERVICE"],
            f"--region={os.environ['REGION']}",
            "--format=json",
            capture=True,
        )
    )


def firebase(path: str, data: dict | None = None) -> dict:
    token = gcloud("auth", "print-access-token", capture=True)
    request = urllib.request.Request(
        f"https://firebasehosting.googleapis.com/v1beta1/sites/{os.environ['PROJECT_ID']}/{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps(data).encode() if data is not None else None,
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def preflight(base: str | None) -> None:
    live = service()
    values = {item["name"]: item.get("value", "") for item in live["spec"]["template"]["spec"]["containers"][0]["env"]}
    deployed = values["TALISMAN_RELEASE_GIT_SHA"]
    if base and deployed != base:
        # Installation-only commits need no application rollout. Any application
        # drift, including sensitive code, requires a separate normal deployment.
        run("git", "merge-base", "--is-ancestor", deployed, base)
        changed = run("git", "diff", "--name-only", f"{deployed}..{base}", capture=True).splitlines()
        operational = {
            ".github/workflows/ci.yml",
            ".github/workflows/sentry-autofix.yml",
            "scripts/sentry_autofix.py",
            "scripts/sentry_autofix_deploy.py",
            "tests/test_sentry_autofix.py",
            "tests/test_sentry_autofix_deploy.py",
            "docs/sentry_autofix.md",
            ".gitignore",
            ".dockerignore",
            ".gcloudignore",
        }
        if set(changed) - operational:
            raise RuntimeError("Production is behind main in application code; deploy that baseline separately first.")
    releases = firebase("releases?pageSize=1").get("releases", [])
    if not releases or not releases[0].get("version", {}).get("name"):
        raise RuntimeError("No Firebase release available for recovery.")
    print(f"Cloud Run and Firebase are accessible. Current backend release: {deployed}")


def ship(sha: str) -> None:
    if run("git", "rev-parse", "HEAD", capture=True) != sha:
        raise RuntimeError("Checkout does not match the merged commit.")
    region = f"--region={os.environ['REGION']}"
    image = f"{os.environ['REGION']}-docker.pkg.dev/{os.environ['PROJECT_ID']}/{os.environ['ARTIFACT_REPO']}/{os.environ['IMAGE_NAME']}:{sha}"
    previous_version = firebase("releases?pageSize=1")["releases"][0]["version"]["name"]
    with tempfile.TemporaryDirectory(prefix="sentry-autofix-") as temporary:
        snapshots = []
        for kind, name in resources():
            snapshot = Path(temporary) / f"{name}.yaml"
            snapshot.write_text(gcloud("run", kind, "describe", name, region, "--format=export", capture=True))
            snapshots.append((kind, snapshot))

        # The builder has artifact-write and source-read permissions only.
        gcloud(
            "builds",
            "submit",
            ".",
            region,
            "--config=infra/gcp/cloudbuild.yaml",
            f"--substitutions=_TAG={sha}",
            "--suppress-logs",
            f"--service-account=projects/{os.environ['PROJECT_ID']}/serviceAccounts/{os.environ['AUTOFIX_BUILD_SA']}",
            f"--gcs-source-staging-dir=gs://{os.environ['AUTOFIX_BUILD_BUCKET']}/source",
        )
        changed = []
        frontend_started = False
        try:
            # Preserve runtime identities, secrets, scaling, IAM, and schema.
            for (kind, name), snapshot in zip(resources(), snapshots, strict=True):
                changed.append(snapshot)
                args = ["run", kind, "update", name, region, f"--image={image}"]
                if kind == "services":
                    args.append(
                        f"--update-env-vars=TALISMAN_RELEASE_GIT_SHA={sha},TALISMAN_RELEASE_GIT_SHA_SHORT={sha[:8]},TALISMAN_RELEASE_IMAGE_TAG={sha}"
                    )
                gcloud(*args)
            os.environ.update(EXPECTED_IMAGE_TAG=sha, AUTH_DEFAULT_USERNAME="smoke", SMOKE_AUTH_PROFILE="viewer")
            run("bash", "infra/gcp/run-backend-smoke.sh")
            frontend_started = True
            os.environ.update(VITE_SENTRY_RELEASE=sha, VITE_TALISMAN_RELEASE_GIT_SHA_SHORT=sha[:8])
            run("bash", "infra/gcp/deploy-frontend.sh")
            with urllib.request.urlopen(f"https://{os.environ['PROJECT_ID']}.web.app/", timeout=45) as response:
                if response.status != 200 or '<div id="root">' not in response.read().decode():
                    raise RuntimeError("Frontend smoke check failed.")
        except BaseException:
            print("Deployment failed; restoring previous Cloud Run configuration and Firebase release.")
            rollback_errors = []
            if frontend_started:
                try:
                    firebase(
                        f"releases?{urllib.parse.urlencode({'versionName': previous_version})}",
                        {"message": "Recover failed Sentry autofix deployment"},
                    )
                except Exception as error:
                    rollback_errors.append(type(error).__name__)
            for kind, snapshot in reversed(changed):
                try:
                    args = ["run", kind, "replace", str(snapshot)]
                    if kind != "worker-pools":
                        args.append(region)
                    gcloud(*args)
                except Exception as error:
                    rollback_errors.append(type(error).__name__)
            if rollback_errors:
                print(f"Recovery needs attention: {rollback_errors}")
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--base")
    parser.add_argument("--ship")
    args = parser.parse_args()
    if args.preflight:
        preflight(args.base)
    elif args.ship:
        ship(args.ship)
    else:
        parser.error("Choose --preflight or --ship SHA")


if __name__ == "__main__":
    main()
