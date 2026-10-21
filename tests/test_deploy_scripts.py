import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARGS_RE = re.compile(r"--args=([^\\\s]+)")


def test_firebase_hosting_spa_rewrite_does_not_capture_missing_assets() -> None:
    config = json.loads((ROOT / "firebase.json").read_text())
    hosting = config["hosting"]
    rewrites = hosting["rewrites"]

    assert rewrites[0]["source"] == "/api/**"

    index_rewrites = [rewrite for rewrite in rewrites if rewrite.get("destination") == "/index.html"]
    assert len(index_rewrites) == 1

    spa_rewrite = index_rewrites[0]
    assert rewrites[1] == spa_rewrite
    assert spa_rewrite.get("source") != "**"
    assert "regex" in spa_rewrite

    no_cache_route_headers = [
        header_rule
        for header_rule in hosting["headers"]
        if header_rule.get("regex")
        and any(
            header["key"].lower() == "cache-control" and "no-cache" in header["value"]
            for header in header_rule["headers"]
        )
    ]
    assert len(no_cache_route_headers) == 1
    assert spa_rewrite["regex"] == no_cache_route_headers[0]["regex"]

    spa_pattern = re.compile(spa_rewrite["regex"])
    for path in ["/", "/index.html", "/sizer", "/sizer/results", "/analyzer", "/alternative-data"]:
        assert spa_pattern.fullmatch(path)

    for path in [
        "/api/health",
        "/assets/DefinitelyMissing-test.js",
        "/assets/index-old.js",
        "/favicon.ico",
    ]:
        assert not spa_pattern.fullmatch(path)


def test_deploy_scripts_do_not_repeat_gcloud_args_values() -> None:
    for script_path in sorted((ROOT / "infra/gcp").glob("*.sh")):
        for line_number, line in enumerate(script_path.read_text().splitlines(), start=1):
            match = ARGS_RE.search(line)
            if not match:
                continue

            args = [arg for arg in match.group(1).strip("'\"").split(",") if arg]
            duplicates = sorted({arg for arg in args if args.count(arg) > 1})

            assert not duplicates, f"{script_path}:{line_number} repeats --args values: {duplicates}"


def test_sizer_worker_deploy_removed() -> None:
    assert not (ROOT / "infra/gcp/deploy-sizer-worker.sh").exists()

    config_example = (ROOT / "infra/gcp/config.example.sh").read_text()
    backend = (ROOT / "infra/gcp/deploy-backend.sh").read_text()

    assert "SIZER_WORKER_" not in config_example
    assert "deploy-sizer-worker.sh" not in backend
    assert "sizer worker pool deploy" not in backend


def test_ontology_worker_deploy_uses_env_for_duplicate_ontology_values() -> None:
    script = (ROOT / "infra/gcp/deploy-ontology-worker.sh").read_text()

    assert "--args=-m,api.job_worker_loop,run \\" in script
    assert "--job-type,ontology,--queue,ontology" not in script
    assert '"ASYNC_DISPATCH_BACKEND_ONTOLOGY=warm_worker"' in script
    assert '"ASYNC_QUEUE_ONTOLOGY=ontology"' in script
    assert '"JOB_WORKER_JOB_TYPE=ontology"' in script
    assert '"JOB_WORKER_QUEUE=ontology"' in script


def test_analyzer_worker_deploy_uses_env_for_duplicate_analyzer_values() -> None:
    script = (ROOT / "infra/gcp/deploy-analyzer-worker.sh").read_text()

    assert "--args=-m,api.job_worker_loop,run \\" in script
    assert "--job-type,analyzer,--queue,analyzer" not in script
    assert '"ASYNC_DISPATCH_BACKEND_ANALYZER=warm_worker"' in script
    assert '"ASYNC_QUEUE_ANALYZER=analyzer"' in script
    assert '"JOB_WORKER_JOB_TYPE=analyzer"' in script
    assert '"JOB_WORKER_QUEUE=analyzer"' in script
    assert '"ASYNC_ANALYZER_COMPLETED_TTL_SECONDS=300"' in script
    assert '--cpu="${ANALYZER_WORKER_CPU:-1}"' in script
    assert '--memory="${ANALYZER_WORKER_MEMORY:-1Gi}"' in script


def test_api_deploy_routes_interactive_analysis_to_warm_workers() -> None:
    script = (ROOT / "infra/gcp/deploy-api.sh").read_text()

    assert '"ASYNC_DISPATCH_BACKEND_ANALYZER=warm_worker"' in script
    assert '"ASYNC_DISPATCH_BACKEND_SIZER=inline"' in script
    assert '"ASYNC_DISPATCH_BACKEND_ONTOLOGY=warm_worker"' in script
    assert '"AGENT_CHAT_DISPATCH_BACKEND=warm_worker"' in script
    assert '"ASYNC_QUEUE_ANALYZER=analyzer"' in script
    assert '"ASYNC_ANALYZER_COMPLETED_TTL_SECONDS=300"' in script


def test_watch_trigger_monitor_scheduler_is_disabled_by_default() -> None:
    script = (ROOT / "infra/gcp/setup-scheduler.sh").read_text()

    assert "SCHEDULE_WATCH_TRIGGER_MONITOR:-0" in script
    assert "delete_scheduler_job_if_present watch-trigger-monitor" in script
    assert 'upsert_api_job watch-trigger-monitor "${WATCH_TRIGGER_MONITOR_SCHEDULE:-30 14-22 * * 1-5}"' in script


def test_catalyst_kill_monitor_scheduler_is_disabled_by_default() -> None:
    script = (ROOT / "infra/gcp/setup-scheduler.sh").read_text()

    assert "SCHEDULE_CATALYST_KILL_MONITOR:-0" in script
    assert "delete_scheduler_job_if_present catalyst-kill-monitor" in script
    assert 'upsert_api_job catalyst-kill-monitor "${CATALYST_KILL_MONITOR_SCHEDULE:-0 15-21 * * 1-5}"' in script


def test_workspace_source_refresh_scheduler_is_enabled_by_default() -> None:
    script = (ROOT / "infra/gcp/setup-scheduler.sh").read_text()

    assert "delete_scheduler_job_if_present workspace-source-refresh" not in script
    assert (
        'upsert_api_job workspace-source-refresh "${WORKSPACE_SOURCE_REFRESH_SCHEDULE:-30 16 * * 1-5}" '
        '/api/admin/jobs/enqueue-workspace-source-refresh "${WORKSPACE_SOURCE_REFRESH_TIME_ZONE:-America/New_York}"'
    ) in script


def test_snapshot_refresh_schedulers_follow_after_close_freshness_cutoff() -> None:
    script = (ROOT / "infra/gcp/setup-scheduler.sh").read_text()

    assert (
        'upsert_api_job market-snapshot-refresh "${MARKET_SNAPSHOT_SCHEDULE:-20 16 * * 1-5}" '
        '/api/admin/jobs/enqueue-market-snapshot-refresh "${MARKET_SNAPSHOT_TIME_ZONE:-America/New_York}"'
    ) in script
    assert (
        'upsert_api_job macro-snapshot-refresh "${MACRO_SNAPSHOT_SCHEDULE:-25 16 * * 1-5}" '
        '/api/admin/jobs/enqueue-macro-snapshot-refresh "${MACRO_SNAPSHOT_TIME_ZONE:-America/New_York}"'
    ) in script


def test_common_gcp_env_requires_postgres_for_api_and_ontology_worker() -> None:
    lib = (ROOT / "infra/gcp/lib.sh").read_text()

    assert "STATE_DB_BACKEND=postgres" in lib
    assert "ASYNC_JOB_STALE_GRACE_SECONDS=${ASYNC_JOB_STALE_GRACE_SECONDS:-300}" in lib
    assert "ASYNC_TIMEOUT_SIZER_SECONDS=${ASYNC_TIMEOUT_SIZER_SECONDS:-180}" in lib

    for script_name in ("deploy-api.sh", "deploy-ontology-worker.sh"):
        script = (ROOT / "infra/gcp" / script_name).read_text()
        assert "mapfile -t COMMON_ENV < <(common_env_vars)" in script
        assert '"${COMMON_ENV[@]}"' in script


def test_backend_deploy_includes_analyzer_worker_paths() -> None:
    script = (ROOT / "infra/gcp/deploy-backend.sh").read_text()

    assert '"analyzer worker pool deploy"' in script
    assert "/infra/gcp/deploy-analyzer-worker.sh" in script
    assert 'log "Deploying analyzer worker pool"' in script


def test_generic_async_job_defaults_to_smaller_fallback_resources() -> None:
    script = (ROOT / "infra/gcp/deploy-async-job.sh").read_text()

    assert '--cpu="${ASYNC_JOB_CPU:-1}"' in script
    assert '--memory="${ASYNC_JOB_MEMORY:-1Gi}"' in script
    assert '"ASYNC_ANALYZER_COMPLETED_TTL_SECONDS=300"' in script


# ---------------------------------------------------------------------------
# SHA-33: release manifest + release env vars
# ---------------------------------------------------------------------------


def test_backend_deploy_invokes_manifest_generation() -> None:
    """deploy-backend.sh must call the release manifest generator."""
    script = (ROOT / "infra/gcp/deploy-backend.sh").read_text()

    assert "release_manifest" in script or "release-manifest" in script
    assert "PYTHON_BIN" in script
    assert "infra.gcp.release_manifest" in script
    assert "--image-uri" in script
    assert "--output" in script


def test_backend_deploy_preserves_dirty_tree_guard() -> None:
    """The dirty-tree deploy guard must remain intact after manifest integration."""
    script = (ROOT / "infra/gcp/deploy-backend.sh").read_text()

    assert "ALLOW_DIRTY" in script
    assert "Working tree is dirty" in script
    assert 'git -C "${_repo_root}" diff --quiet' in script


def test_backend_deploy_manifest_rollback_refs() -> None:
    """deploy-backend.sh should attempt to pass prior manifest for rollback refs."""
    script = (ROOT / "infra/gcp/deploy-backend.sh").read_text()

    assert "--prior-manifest" in script
    assert "release-manifest.json" in script


def test_api_deploy_includes_release_env_vars() -> None:
    """deploy-api.sh must set TALISMAN_RELEASE_* env vars for the health endpoints."""
    script = (ROOT / "infra/gcp/deploy-api.sh").read_text()

    assert "TALISMAN_RELEASE_GIT_SHA=" in script
    assert "TALISMAN_RELEASE_GIT_SHA_SHORT=" in script
    assert "TALISMAN_RELEASE_IMAGE_TAG=" in script
    assert "TALISMAN_RELEASE_ENVIRONMENT=" in script


def test_api_deploy_does_not_expose_secrets_as_release_vars() -> None:
    """Release env vars must not include any secret references."""
    script = (ROOT / "infra/gcp/deploy-api.sh").read_text()

    # Find lines with TALISMAN_RELEASE and check none reference secrets
    for line in script.splitlines():
        if "TALISMAN_RELEASE" in line:
            assert "SECRET" not in line.upper(), f"Release var references a secret: {line.strip()}"
            assert "PASSWORD" not in line.upper(), f"Release var references a password: {line.strip()}"
            assert "API_KEY" not in line.upper(), f"Release var references an API key: {line.strip()}"


# ---------------------------------------------------------------------------
# SHA-34: deploy smoke runner
# ---------------------------------------------------------------------------


def test_backend_deploy_does_not_gate_on_smoke() -> None:
    """deploy-backend.sh must not fail the rollout on post-deploy smoke."""
    script = (ROOT / "infra/gcp/deploy-backend.sh").read_text()

    assert "run-backend-smoke.sh" not in script
    assert "RUN_DEPLOY_SMOKE" not in script


def test_smoke_runner_does_not_pass_secrets_as_cli_args() -> None:
    """run-backend-smoke.sh must not pass secrets as positional/flag CLI args."""
    smoke_script = (ROOT / "infra/gcp/run-backend-smoke.sh").read_text()

    for line in smoke_script.splitlines():
        stripped = line.strip()
        # Skip comments and blank lines
        if not stripped or stripped.startswith("#"):
            continue
        # Check we never pass secret values as CLI arguments directly
        if "--smoke-password" in stripped or "--proxy-secret" in stripped:
            raise AssertionError(f"Secret passed as CLI arg: {stripped}")


def test_api_deploy_includes_migration_head_env_var() -> None:
    """deploy-api.sh must set TALISMAN_RELEASE_MIGRATION_HEAD."""
    script = (ROOT / "infra/gcp/deploy-api.sh").read_text()

    assert "TALISMAN_RELEASE_MIGRATION_HEAD" in script


def test_config_example_includes_smoke_hash_secret() -> None:
    """config.example.sh must bind AUTH_SMOKE_PASSWORD_HASH for the API."""
    config = (ROOT / "infra/gcp/config.example.sh").read_text()

    assert "AUTH_SMOKE_PASSWORD_HASH" in config


def _render_pool_deploy(tmp_path, script_name, *, overrides=None, example_config=False):
    """Run real deployment scripts against a capturing gcloud, never the cloud."""
    root = tmp_path / Path(script_name).stem
    scripts = root / "infra/gcp"
    scripts.mkdir(parents=True)
    for filename in ("lib.sh", script_name):
        shutil.copyfile(ROOT / "infra/gcp" / filename, scripts / filename)
    if example_config:
        shutil.copyfile(ROOT / "infra/gcp/config.example.sh", scripts / "config.sh")
    else:
        (scripts / "config.sh").write_text(
            """PROJECT_ID=pool-test
REGION=us-central1
ARTIFACT_REPO=pool-test
IMAGE_NAME=api
API_SERVICE=api
API_SA=api@example.invalid
WORKER_SA=worker@example.invalid
MIGRATOR_SA=migrator@example.invalid
CLOUDSQL_INSTANCE=pool-test:us-central1:test
GCS_STATE_BUCKET=pool-test
TOP50_REFRESH_JOB=top50
CORS_ORIGINS=https://example.invalid
ANALYZER_WORKER_INSTANCES=0
ONTOLOGY_WORKER_INSTANCES=0
API_SECRETS=(DATABASE_URL=fake:latest)
WORKER_SECRETS=(DATABASE_URL=fake:latest)
"""
        )
    binary = root / "bin"
    binary.mkdir()
    gcloud = binary / "gcloud"
    gcloud.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "if sys.argv[1] != 'config':\n"
        "    Path(os.environ['DEPLOY_ARGUMENTS']).write_text(json.dumps(sys.argv[1:]))\n"
    )
    gcloud.chmod(0o755)
    captured = root / "arguments.json"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("POSTGRES_POOL_", "API_MAX_"))}
    env.update(
        PATH=f"{binary}{os.pathsep}{os.environ['PATH']}",
        DEPLOY_ARGUMENTS=str(captured),
        IMAGE_TAG="pool-test",
        SKIP_IMAGE_CHECK="1",
    )
    env.update(overrides or {})
    subprocess.run(
        [shutil.which("bash") or "/bin/bash", str(scripts / script_name)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    args = json.loads(captured.read_text())
    flags = dict(arg.split("=", 1) for arg in args if arg.startswith("--") and "=" in arg)
    pairs = [pair.split("=", 1) for pair in flags["--set-env-vars"].removeprefix("^|^").split("|")]
    pool_keys = [key for key, _ in pairs if key.startswith("POSTGRES_POOL_")]
    assert len(pool_keys) == len(set(pool_keys)), "duplicate pool settings in rendered deployment"
    return flags, dict(pairs)


@pytest.mark.parametrize(
    "script_name,minimum,maximum",
    [
        ("deploy-api.sh", 2, 2),
        ("deploy-agent-worker.sh", 2, 2),
        ("deploy-analyzer-worker.sh", 2, 2),
        ("deploy-ontology-worker.sh", 2, 2),
        ("deploy-async-job.sh", 2, 2),
        ("deploy-top50-refresh-job.sh", 0, 1),
    ],
)
def test_rendered_production_pool_settings(tmp_path, script_name, minimum, maximum):
    _, env = _render_pool_deploy(tmp_path, script_name)
    assert int(env["POSTGRES_POOL_MIN_SIZE"]) == minimum
    assert int(env["POSTGRES_POOL_MAX_SIZE"]) == maximum
    assert float(env["POSTGRES_POOL_TIMEOUT_SECONDS"]) == 5
    assert minimum <= maximum


def test_pool_overrides_and_api_service_cap_are_rendered_consistently(tmp_path):
    flags, env = _render_pool_deploy(
        tmp_path,
        "deploy-api.sh",
        overrides={
            "POSTGRES_POOL_MIN_SIZE": "0",
            "POSTGRES_POOL_MAX_SIZE": "1",
            "POSTGRES_POOL_TIMEOUT_SECONDS": "1.25",
            "API_MAX_INSTANCES": "1",
        },
    )
    assert flags["--max"] == flags["--max-instances"] == "1"
    assert env["POSTGRES_POOL_MIN_SIZE"] == "0"
    assert env["POSTGRES_POOL_MAX_SIZE"] == "1"
    assert env["POSTGRES_POOL_TIMEOUT_SECONDS"] == "1.25"


def test_example_config_keeps_the_approved_api_pool_budget(tmp_path):
    flags, env = _render_pool_deploy(tmp_path, "deploy-api.sh", example_config=True)
    assert flags["--max"] == flags["--max-instances"] == "2"
    assert env["POSTGRES_POOL_MIN_SIZE"] == env["POSTGRES_POOL_MAX_SIZE"] == "2"
    assert env["POSTGRES_POOL_TIMEOUT_SECONDS"] == "5"


def test_rendered_stack_fits_live_connection_budget_including_rollout(tmp_path):
    api_flags, api = _render_pool_deploy(tmp_path, "deploy-api.sh", example_config=True)
    agent_flags, agent = _render_pool_deploy(tmp_path, "deploy-agent-worker.sh", example_config=True)
    analyzer_flags, analyzer = _render_pool_deploy(tmp_path, "deploy-analyzer-worker.sh", example_config=True)
    ontology_flags, ontology = _render_pool_deploy(tmp_path, "deploy-ontology-worker.sh", example_config=True)
    _, async_job = _render_pool_deploy(tmp_path, "deploy-async-job.sh", example_config=True)
    _, top50 = _render_pool_deploy(tmp_path, "deploy-top50-refresh-job.sh", example_config=True)
    assert api_flags["--max"] == api_flags["--max-instances"] == "2"
    api_connections = int(api_flags["--max"]) * int(api["POSTGRES_POOL_MAX_SIZE"])
    agent_connections = int(agent_flags["--instances"]) * int(agent["POSTGRES_POOL_MAX_SIZE"])
    analysis_connections = sum(
        int(flags["--instances"]) * int(env["POSTGRES_POOL_MAX_SIZE"])
        for flags, env in ((analyzer_flags, analyzer), (ontology_flags, ontology))
    )
    # Two async executions, one migration connection, and two admin slots are
    # explicit operational allowances, not scheduler-enforced execution limits.
    steady = (
        api_connections
        + agent_connections
        + analysis_connections
        + 2 * int(async_job["POSTGRES_POOL_MAX_SIZE"])
        + int(top50["POSTGRES_POOL_MAX_SIZE"])
        + 1
        + 2
    )
    assert int(analyzer_flags["--instances"]) == int(ontology_flags["--instances"]) == 1
    assert steady == 18
    # Rollouts drain generic async executions. Worker pools update before the
    # API fleet, so their extra replicas do not overlap the extra API fleet.
    drained_async_connections = 2 * int(async_job["POSTGRES_POOL_MAX_SIZE"])
    worker_rollout = agent_connections + analysis_connections
    assert worker_rollout == 6
    assert steady - drained_async_connections + worker_rollout + 3 == 23 < 25
    assert steady - drained_async_connections + api_connections + 3 == 21 < 25


@pytest.mark.parametrize("parallel", ["0", "1"])
def test_backend_applies_schema_before_starting_new_workers(tmp_path, parallel):
    scripts = tmp_path / "infra/gcp"
    scripts.mkdir(parents=True)
    for filename in ("lib.sh", "deploy-backend.sh"):
        shutil.copyfile(ROOT / "infra/gcp" / filename, scripts / filename)
    (scripts / "config.sh").write_text(
        """PROJECT_ID=claim-test
REGION=us-central1
ARTIFACT_REPO=claim-test
IMAGE_NAME=api
MIGRATION_JOB=migrate
API_SECRETS=()
WORKER_SECRETS=()
"""
    )
    for name in (
        "deploy-migration-job.sh",
        "deploy-top50-refresh-job.sh",
        "deploy-async-job.sh",
        "deploy-agent-worker.sh",
        "deploy-analyzer-worker.sh",
        "deploy-ontology-worker.sh",
        "deploy-api.sh",
    ):
        script = scripts / name
        script.write_text(f'#!/bin/sh\nprintf "%s\\n" "{name}" >> "$DEPLOY_EVENTS"\n')
        script.chmod(0o755)
    binary = tmp_path / "bin"
    binary.mkdir()
    commands = {
        "git": f'#!/bin/sh\nprintf "%s\\n" "{tmp_path}"\n',
        "python": "#!/bin/sh\nexit 0\n",
        "gcloud": (
            '#!/bin/sh\nif [ "$1 $2 $3" = "run jobs execute" ]; then\n'
            '  printf "%s\\n" "migration-complete" >> "$DEPLOY_EVENTS"\nfi\n'
        ),
    }
    for name, content in commands.items():
        command = binary / name
        command.write_text(content)
        command.chmod(0o755)
    events_path = tmp_path / "events.log"
    env = {
        **os.environ,
        "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}",
        "PYTHON": str(binary / "python"),
        "DEPLOY_EVENTS": str(events_path),
        "IMAGE_TAG": "claim-test",
        "SKIP_BUILD": "1",
        "SKIP_IMAGE_CHECK": "1",
        "ALLOW_DIRTY": "1",
        "RUN_DB_MIGRATIONS": "1",
        "PARALLEL_JOB_DEPLOYS": parallel,
        "FULL_SYNC": "0",
        "SYNC_IAM": "0",
        "SYNC_SCHEDULER": "0",
        "SYNC_MONITORING": "0",
    }
    subprocess.run(
        [shutil.which("bash") or "/bin/bash", str(scripts / "deploy-backend.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    events = events_path.read_text().splitlines()
    assert events[0:2] == ["deploy-migration-job.sh", "migration-complete"]
    assert events[-1] == "deploy-api.sh"
    assert "deploy-analyzer-worker.sh" in events[2:-1]
    assert "deploy-ontology-worker.sh" in events[2:-1]
