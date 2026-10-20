#!/usr/bin/env python3
"""Provision TL-179 log metrics/dashboard. --dry-run renders without cloud calls."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def render_dashboard(*, sentry_org: str, sentry_project: str, api_service: str) -> dict:
    for value in (sentry_org, sentry_project, api_service):
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
            raise ValueError("Sentry organization/project and API service must be identifiers, not URLs.")
    source = (HERE / "performance-dashboard.json").read_text()
    for key, value in (
        ("__SENTRY_ORG__", sentry_org),
        ("__SENTRY_PROJECT_ID__", sentry_project),
        ("__API_SERVICE__", api_service),
    ):
        source = source.replace(key, value)
    return json.loads(source)


def provision(*, project: str, dashboard: dict, output: Path, dry_run: bool = False) -> None:
    output.mkdir(parents=True, exist_ok=True)
    metrics = json.loads((HERE / "performance-metrics.json").read_text())

    def gcloud(*args: str):
        result = subprocess.run(
            ["gcloud", *args, f"--project={project}", "--quiet", "--format=json"],
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout) if result.stdout.strip() else None

    # List once: authentication/permission failures abort instead of masquerading
    # as missing resources. No delete/recreate, and no Cloud SQL flag mutations.
    existing_metrics = (
        set() if dry_run else {item["name"].rsplit("/", 1)[-1] for item in (gcloud("logging", "metrics", "list") or [])}
    )
    for metric in metrics:
        name = metric["name"]
        path = output / f"{name}.json"
        path.write_text(json.dumps(metric, indent=2) + "\n")
        if not dry_run:
            gcloud(
                "logging",
                "metrics",
                "update" if name in existing_metrics else "create",
                name,
                f"--config-from-file={path}",
            )

    existing = [] if dry_run else gcloud("monitoring", "dashboards", "list") or []
    matches = [item for item in existing if item.get("displayName") == dashboard["displayName"]]
    if len(matches) > 1:
        raise RuntimeError("Multiple TL-179 dashboards exist; resolve duplicates before provisioning.")
    if matches:
        current = gcloud("monitoring", "dashboards", "describe", matches[0]["name"])
        dashboard = {**dashboard, "name": current["name"], "etag": current["etag"]}
    dashboard_path = output / "dashboard.json"
    dashboard_path.write_text(json.dumps(dashboard, indent=2) + "\n")
    if not dry_run:
        args = (
            ["monitoring", "dashboards", "update", matches[0]["name"]]
            if matches
            else ["monitoring", "dashboards", "create"]
        )
        result = gcloud(*args, f"--config-from-file={dashboard_path}")
        print(f"Dashboard: {result['name']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.getenv("PROJECT_ID"), required=not os.getenv("PROJECT_ID"))
    parser.add_argument("--sentry-org", default=os.getenv("SENTRY_ORG"), required=not os.getenv("SENTRY_ORG"))
    parser.add_argument(
        "--sentry-project", default=os.getenv("SENTRY_PROJECT_ID"), required=not os.getenv("SENTRY_PROJECT_ID")
    )
    parser.add_argument("--api-service", default=os.getenv("API_SERVICE", "talisman-api"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    dashboard = render_dashboard(
        sentry_org=args.sentry_org, sentry_project=args.sentry_project, api_service=args.api_service
    )
    with tempfile.TemporaryDirectory(prefix="talisman-performance-") as temporary:
        output = args.output or Path(temporary)
        provision(project=args.project, dashboard=dashboard, output=output, dry_run=args.dry_run)
        if args.dry_run:
            print("Dry run: no cloud resources changed. Use --output to retain rendered definitions.")


if __name__ == "__main__":
    main()
