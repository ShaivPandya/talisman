"""Tests for the no-Docker startup script. They do not download PostgreSQL."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from longaeva_app.isolation_guard import resolve_root

SCRIPT = resolve_root() / "scripts" / "up_local.py"


def load_up_local() -> Any:
    spec = importlib.util.spec_from_file_location("up_local_under_test", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load scripts/up_local.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def up_local() -> Any:
    return load_up_local()


def test_platform_key_supported(up_local: Any) -> None:
    assert up_local.platform_key("Darwin", "arm64") == "darwin-arm64v8"
    assert up_local.platform_key("Darwin", "x86_64") == "darwin-amd64"
    assert up_local.platform_key("Linux", "x86_64") == "linux-amd64"
    assert up_local.platform_key("Linux", "aarch64") == "linux-arm64v8"
    assert up_local.platform_key("Windows", "AMD64") == "windows-amd64"


def test_platform_key_unsupported(up_local: Any) -> None:
    with pytest.raises(up_local.SetupError, match="make up"):
        up_local.platform_key("Windows", "ARM64")
    with pytest.raises(up_local.SetupError, match="make up"):
        up_local.platform_key("Linux", "x86_64", musl=True)
    with pytest.raises(up_local.SetupError, match="make up"):
        up_local.platform_key("FreeBSD", "amd64")


def test_python_version_error(up_local: Any) -> None:
    assert up_local.python_version_error((3, 12, 0)) is None
    assert up_local.python_version_error((3, 13, 1)) is None
    message = up_local.python_version_error((3, 11, 9))
    assert isinstance(message, str)
    assert "Python 3.12" in message
    assert "3.11.9" in message


def test_node_version(up_local: Any) -> None:
    assert up_local.parse_node_version("v20.19.0\n") == (20, 19, 0)
    assert up_local.parse_node_version("v20.19") == (20, 19, 0)
    assert up_local.parse_node_version("v25.8.0") == (25, 8, 0)
    assert up_local.node_version_error((20, 19, 0)) is None
    assert up_local.node_version_error((25, 8, 0)) is None
    old = up_local.node_version_error((20, 18, 9))
    assert isinstance(old, str)
    assert "20.19.0" in old
    with pytest.raises(up_local.SetupError):
        up_local.parse_node_version("not-node")


def test_database_port_override(up_local: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(up_local, "bring_up", lambda: None)
    assert up_local.main(["--db-port", "55439"]) == 0
    assert up_local.DB_PORT == 55439
    assert up_local.DATABASE_URL.endswith(":55439/longaeva")
    assert up_local.ADMIN_DATABASE_URL.endswith(":55439/postgres")
    assert up_local.main([]) == 0
    assert up_local.DB_PORT == 55432


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_invalid_database_port(up_local: Any, port: str) -> None:
    with pytest.raises(SystemExit):
        up_local.parse_args(["--db-port", port])


def test_verify_sha256_rejects_mismatch(up_local: Any, tmp_path: Path) -> None:
    path = tmp_path / "payload.bin"
    payload = b"postgres"
    path.write_bytes(payload)
    up_local.verify_sha256(path, hashlib.sha256(payload).hexdigest())
    assert path.is_file()
    with pytest.raises(up_local.SetupError, match="checksum"):
        up_local.verify_sha256(path, "0" * 64)
    assert not path.exists()


def test_manifest_pins_postgres_16(up_local: Any) -> None:
    manifest = up_local.load_manifest(up_local.MANIFEST_PATH)
    assert manifest["version"] == "16.10.0"
    platforms = manifest["platforms"]
    expected = {
        up_local.platform_key("Darwin", "arm64"),
        up_local.platform_key("Darwin", "x86_64"),
        up_local.platform_key("Linux", "x86_64"),
        up_local.platform_key("Linux", "aarch64"),
        up_local.platform_key("Windows", "AMD64"),
    }
    assert set(platforms) == expected
    for entry in platforms.values():
        digest = entry["sha256"]
        assert isinstance(digest, str)
        assert len(digest) == 64
        assert digest == digest.lower()
        int(digest, 16)
        url = entry["url"]
        assert isinstance(url, str)
        assert url.startswith("https://repo1.maven.org/maven2/")
        assert "16.10.0" in url
