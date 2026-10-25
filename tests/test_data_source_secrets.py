from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from infra.gcp import data_source_secrets as secrets


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for name in secrets.CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env.data-sources"
    config = tmp_path / "config.sh"
    config.write_text('PROJECT_ID=test\nALTERNATIVE_DATA_SECRETS=("CUSTOM=CUSTOM:7")\n')
    calls = []

    def fake_gcloud(project, *args, payload=None):
        calls.append((args, payload))
        if args[:2] == ("secrets", "list"):
            return "CENSUS_API_KEY\nNOAA_CDO_TOKEN"
        if args[:3] == ("secrets", "versions", "list"):
            return "ENABLED" if args[3] == "CENSUS_API_KEY" else "DISABLED"
        return ""

    monkeypatch.setattr(secrets, "gcloud", fake_gcloud)
    return env_file, config, calls


def test_sync_uploads_only_supplied_credentials_and_preserves_existing(setup, capsys):
    env_file, config, calls = setup
    env_file.write_text(
        "FIRMS_MAP_KEY=private-firms\nCENSUS_API_KEY=do-not-rotate\nNOAA_CDO_TOKEN=private-noaa\n"
        "COPERNICUS_CLIENT_ID=incomplete\nOPENSKY_CLIENT_ID=client\nOPENSKY_CLIENT_SECRET=private-sky\n"
        "AISHUB_USERNAME=your_username_here\nUNRELATED_SECRET=do-not-import\n"
    )
    names = secrets.sync("test", ["api@test", "worker@test"], env_file, config, apply=True)
    assert names == ["FIRMS_MAP_KEY", "CENSUS_API_KEY", "NOAA_CDO_TOKEN", "OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET"]
    uploads = [(args, payload) for args, payload in calls if payload is not None]
    assert [payload for _, payload in uploads] == ["private-firms", "private-noaa", "client", "private-sky"]
    assert any(args[:4] == ("secrets", "versions", "add", "NOAA_CDO_TOKEN") for args, _ in uploads)
    grants = [args for args, _ in calls if args[:2] == ("secrets", "add-iam-policy-binding")]
    assert len(grants) == len(names) * 2
    for name in names:
        assert {arg for args in grants if args[2] == name for arg in args if arg.startswith("--member=")} == {
            "--member=serviceAccount:api@test",
            "--member=serviceAccount:worker@test",
        }
    output = capsys.readouterr().out + config.read_text()
    assert all(payload not in output for _, payload in uploads)
    assert "do-not-rotate" not in output
    assert 'ALTERNATIVE_DATA_SECRETS=("CUSTOM=CUSTOM:7")' in config.read_text()


def test_preview_does_not_mutate_cloud_or_config(setup):
    env_file, config, calls = setup
    env_file.write_text("FIRMS_MAP_KEY=private-firms\n")
    before = config.read_bytes()
    secrets.sync("test", ["api@test"], env_file, config, apply=False)
    assert config.read_bytes() == before
    assert all(args[:2] == ("secrets", "list") or args[:3] == ("secrets", "versions", "list") for args, _ in calls)


def test_repeated_setup_is_idempotent_and_can_complete_oauth_pair(setup, monkeypatch):
    env_file, config, calls = setup
    env_file.write_text("COPERNICUS_CLIENT_SECRET=private-secret\n")

    def fake_gcloud(project, *args, payload=None):
        calls.append((args, payload))
        if args[:2] == ("secrets", "list"):
            return "COPERNICUS_CLIENT_ID\nCOPERNICUS_CLIENT_SECRET"
        if args[:3] == ("secrets", "versions", "list"):
            return "ENABLED" if args[3] == "COPERNICUS_CLIENT_ID" else ""
        return ""

    monkeypatch.setattr(secrets, "gcloud", fake_gcloud)
    names = secrets.sync("test", ["api@test"], env_file, config, apply=True)
    assert names == ["COPERNICUS_CLIENT_ID", "COPERNICUS_CLIENT_SECRET"]
    first = config.read_text()
    secrets.save_bindings(config, names)
    assert config.read_text() == first
    assert first.count(secrets.BEGIN) == 1


def test_failed_inventory_stops_before_any_changes(setup, monkeypatch):
    env_file, config, _ = setup
    before = config.read_bytes()

    def failed_gcloud(*args, **kwargs):
        raise RuntimeError("permission denied")

    monkeypatch.setattr(secrets, "gcloud", failed_gcloud)
    with pytest.raises(RuntimeError):
        secrets.sync("test", ["api@test"], env_file, config, apply=True)
    assert config.read_bytes() == before


def test_credential_interpolation_is_disabled(setup):
    env_file, _, _ = setup
    env_file.write_text("COPERNICUS_CLIENT_SECRET=literal-${HOME}-value\n")
    assert secrets.supplied_credentials(env_file)["COPERNICUS_CLIENT_SECRET"] == "literal-${HOME}-value"


def test_subprocess_uses_stdin_and_redacts_errors(monkeypatch):
    def failed_run(command, **kwargs):
        assert "private-value" not in " ".join(command)
        assert kwargs["input"] == "private-value"
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(command, 1, stdout="private-value", stderr="private-value")

    monkeypatch.setattr(subprocess, "run", failed_run)
    with pytest.raises(RuntimeError) as error:
        secrets.gcloud("test", "secrets", "create", "FIRMS_MAP_KEY", "--data-file=-", payload="private-value")
    assert "private-value" not in str(error.value)
