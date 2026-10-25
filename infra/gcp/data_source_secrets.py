"""Stage optional data-source credentials in Secret Manager without exposing values."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from dotenv import dotenv_values

CREDENTIALS = (
    "FIRMS_MAP_KEY",
    "CENSUS_API_KEY",
    "NOAA_CDO_TOKEN",
    "COPERNICUS_CLIENT_ID",
    "COPERNICUS_CLIENT_SECRET",
    "AISHUB_USERNAME",
    "OPENSKY_CLIENT_ID",
    "OPENSKY_CLIENT_SECRET",
)
PAIRS = (
    ("COPERNICUS_CLIENT_ID", "COPERNICUS_CLIENT_SECRET"),
    ("OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET"),
)
BEGIN = "# BEGIN managed data-source secret bindings"
END = "# END managed data-source secret bindings"


def gcloud(project: str, *args: str, payload: str | None = None) -> str:
    result = subprocess.run(
        ["gcloud", *args, f"--project={project}", "--quiet"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if result.returncode:
        # Provider/CLI errors can echo request bodies. Never relay raw output.
        raise RuntimeError(f"gcloud {' '.join(args[:3])} failed (exit {result.returncode}).")
    return result.stdout.strip()


def supplied_credentials(env_file: Path) -> dict[str, str]:
    # Disable interpolation so literal '$' characters in credentials survive.
    file_values = dotenv_values(env_file, interpolate=False) if env_file.is_file() else {}
    values = {}
    for name in CREDENTIALS:
        value = (os.environ.get(name) or file_values.get(name) or "").strip()
        if value and not value.lower().startswith(("your_", "replace_", "<", "demo_key")):
            values[name] = value
    return values


def save_bindings(config_file: Path, names: list[str]) -> None:
    """Persist references only; preserve local deploy settings and manual bindings."""
    original = config_file.read_text()
    pattern = re.compile(rf"\n?{re.escape(BEGIN)}\n.*?{re.escape(END)}\n?", re.DOTALL)
    original = pattern.sub("\n", original).rstrip()
    block = [BEGIN, "ALTERNATIVE_DATA_SECRETS+=("]
    block.extend(f'  "{name}={name}:latest"' for name in names)
    block.extend([")", END, ""])
    config_file.write_text(original + "\n\n" + "\n".join(block))


def sync(project: str, service_accounts: list[str], env_file: Path, config_file: Path, *, apply: bool) -> list[str]:
    supplied = supplied_credentials(env_file)
    # A failed listing must stop the run, rather than looking like missing secrets.
    existing = set(gcloud(project, "secrets", "list", "--format=value(name)").splitlines())
    available = set()
    for name in CREDENTIALS:
        if name in existing:
            state = gcloud(
                project,
                "secrets",
                "versions",
                "list",
                name,
                "--sort-by=~createTime",
                "--limit=1",
                "--format=value(state)",
            )
            if state == "ENABLED":
                available.add(name)

    for pair in PAIRS:
        if not set(pair) <= available | supplied.keys():
            for name in pair:
                supplied.pop(name, None)

    for name in CREDENTIALS:
        if name in available:
            print(f"{name}: existing enabled secret preserved")
        elif name in supplied:
            print(f"{name}: {'uploading' if apply else 'would upload'}")
            if apply:
                if name in existing:
                    gcloud(project, "secrets", "versions", "add", name, "--data-file=-", payload=supplied[name])
                else:
                    gcloud(
                        project,
                        "secrets",
                        "create",
                        name,
                        "--replication-policy=automatic",
                        "--data-file=-",
                        payload=supplied[name],
                    )
            available.add(name)
        else:
            print(f"{name}: missing (or incomplete OAuth pair); skipped")

    # Do not bind an incomplete OAuth pair, even if one secret already exists.
    for pair in PAIRS:
        if not set(pair) <= available:
            available.difference_update(pair)
    names = [name for name in CREDENTIALS if name in available]
    if apply and names:
        for name in names:
            for account in dict.fromkeys(service_accounts):
                gcloud(
                    project,
                    "secrets",
                    "add-iam-policy-binding",
                    name,
                    "--role=roles/secretmanager.secretAccessor",
                    f"--member=serviceAccount:{account}",
                    "--condition=None",
                )
        save_bindings(config_file, names)
        print("Secret access granted and references saved in local deploy config.")
        print("Cloud Run still needs a configuration update to load these credentials.")
    print("Bindings: " + json.dumps([f"{name}={name}:latest" for name in names]))
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--service-account", action="append", required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--config-file", type=Path, required=True)
    parser.add_argument(
        "--apply", action="store_true", help="Upload keys, grant access, and save bindings; default is read-only."
    )
    args = parser.parse_args()
    if not args.config_file.is_file():
        parser.error("The existing local GCP config file is required.")
    try:
        sync(args.project, args.service_account, args.env_file, args.config_file, apply=args.apply)
    except (RuntimeError, subprocess.TimeoutExpired):
        parser.exit(
            1, "Secret setup failed; partial successful steps are safe to retry. Check GCP access and connectivity.\n"
        )


if __name__ == "__main__":
    main()
