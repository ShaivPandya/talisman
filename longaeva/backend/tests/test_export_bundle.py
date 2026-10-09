"""Tests for the submission ZIP builder.

Negative fixtures live under ``tmp_path`` so deliberate bad strings never enter the
real package export set. Forbidden literals in this file are split across concatenations
so a scan of the package itself stays clean.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from longaeva_app.export_bundle import (
    ZIP_PREFIX,
    ExportBundleError,
    build_export_zip,
    check_export_zip,
    load_forbid_file,
)
from longaeva_app.isolation_guard import EXPORTIGNORE_NAME, resolve_root

BACKEND_ROOT = Path(__file__).resolve().parents[1]

PROBE = "UniqueExport" + "ProbeName99"
USERS_PREFIX = "/" + "Users" + "/"
FAKE_HOME = USERS_PREFIX + "exampledev"
TALISMAN_API = "ap" + "i"


def _minimal_exportignore() -> str:
    return """\
.env
.env.*
!.env.example
.git/
.venv/
venv/
__pycache__/
node_modules/
var/
*.pyc
*.zip
"""


def _write_package(root: Path) -> None:
    """Create a minimal package tree the guard can scan."""
    root.mkdir(parents=True, exist_ok=True)
    (root / EXPORTIGNORE_NAME).write_text(_minimal_exportignore(), encoding="utf-8")
    (root / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (root / ".env.example").write_text("SEC_USER_AGENT=\n", encoding="utf-8")
    backend = root / "backend"
    app = backend / "longaeva_app"
    tests = backend / "tests"
    app.mkdir(parents=True)
    tests.mkdir(parents=True)
    (app / "__init__.py").write_text('"""app"""\n', encoding="utf-8")
    (backend / "requirements.lock").write_text(
        "#\n# fixture lock\n#\nfastapi==0.115.0\n",
        encoding="utf-8",
    )
    (root / "data" / "fixtures").mkdir(parents=True)
    (root / "data" / "fixtures" / "origins.csv").write_text("origin\n", encoding="utf-8")
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "limitations.md").write_text("# Limitations\n", encoding="utf-8")


def _zip_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def _member_mode(path: Path, arcname: str) -> int:
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(arcname)
    return (info.external_attr >> 16) & 0o777


def test_load_forbid_file_skips_comments(tmp_path: Path) -> None:
    path = tmp_path / "forbid.txt"
    path.write_text("# comment\n\nAlpha\nBeta\n", encoding="utf-8")
    assert load_forbid_file(path) == ("Alpha", "Beta")


def test_build_includes_example_env_excludes_env(tmp_path: Path) -> None:
    _write_package(tmp_path)
    (tmp_path / ".env").write_text("SEC_USER_AGENT=Example Contact me@example.com\n", encoding="utf-8")
    script = tmp_path / "backend" / "scripts" / "check.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    script.chmod(0o755)
    out = tmp_path / "out" / "bundle.zip"
    summary = build_export_zip(tmp_path, out)
    assert out.is_file()
    assert summary.file_count >= 6
    names = _zip_names(out)
    assert f"{ZIP_PREFIX}/.env.example" in names
    assert f"{ZIP_PREFIX}/README.md" in names
    assert f"{ZIP_PREFIX}/.env" not in names
    assert not any(".git/" in name for name in names)
    assert not any("node_modules/" in name for name in names)
    assert _member_mode(out, f"{ZIP_PREFIX}/backend/scripts/check.sh") == 0o755
    assert _member_mode(out, f"{ZIP_PREFIX}/README.md") == 0o644


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    dist = tmp_path / "dist"
    _write_package(pkg)
    a = dist / "a.zip"
    b = dist / "b.zip"
    first = build_export_zip(pkg, a)
    second = build_export_zip(pkg, b)
    assert a.read_bytes() == b.read_bytes()
    assert first.sha256 == second.sha256
    assert first.file_count == second.file_count


def test_guard_finding_aborts_and_leaves_no_zip(tmp_path: Path) -> None:
    _write_package(tmp_path)
    bad = tmp_path / "backend" / "longaeva_app" / "bad_import.py"
    bad.write_text(f"from {TALISMAN_API} import x\n", encoding="utf-8")
    out = tmp_path / "bundle.zip"
    with pytest.raises(ExportBundleError) as excinfo:
        build_export_zip(tmp_path, out)
    assert not out.exists()
    assert any(f.rule == "python-import" for f in excinfo.value.findings)
    assert not list(tmp_path.glob("*.partial"))


def test_self_check_rejects_git_member(tmp_path: Path) -> None:
    crafted = tmp_path / "bad.zip"
    with zipfile.ZipFile(crafted, "w") as archive:
        archive.writestr(f"{ZIP_PREFIX}/README.md", "# ok\n")
        archive.writestr(f"{ZIP_PREFIX}/.git/config", "secret\n")
    findings = check_export_zip(crafted)
    assert any(f.rule == "excluded-entry" and ".git" in f.detail for f in findings)


def test_self_check_rejects_absolute_home_bytes(tmp_path: Path) -> None:
    crafted = tmp_path / "bad.zip"
    with zipfile.ZipFile(crafted, "w") as archive:
        archive.writestr(f"{ZIP_PREFIX}/docs/leak.md", f"path {FAKE_HOME}/file\n")
    findings = check_export_zip(crafted)
    assert any(f.rule == "absolute-path" for f in findings)
    assert all(FAKE_HOME not in f.detail for f in findings)


def test_personal_string_flagged_without_echo(tmp_path: Path) -> None:
    _write_package(tmp_path)
    doc = tmp_path / "docs" / "oops.md"
    doc.write_text(f"signed by {PROBE}\n", encoding="utf-8")
    out = tmp_path / "bundle.zip"
    with pytest.raises(ExportBundleError) as excinfo:
        build_export_zip(tmp_path, out, forbid=(PROBE,))
    assert not out.exists()
    personal = [f for f in excinfo.value.findings if f.rule == "personal-string"]
    assert personal
    assert all(PROBE not in f.detail for f in personal)
    assert all("redacted" in f.detail for f in personal)


def test_cli_export_zip_clean_and_dirty(tmp_path: Path) -> None:
    _write_package(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
    out = tmp_path / "ok.zip"
    clean = subprocess.run(
        [
            sys.executable,
            "-m",
            "longaeva_app.cli",
            "export-zip",
            "--root",
            str(tmp_path),
            "--output",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND_ROOT),
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert out.is_file()
    assert "sha256" in clean.stdout

    bad = tmp_path / "backend" / "longaeva_app" / "bad.py"
    bad.write_text(f"from {TALISMAN_API} import x\n", encoding="utf-8")
    dirty_out = tmp_path / "dirty.zip"
    dirty = subprocess.run(
        [
            sys.executable,
            "-m",
            "longaeva_app.cli",
            "export-zip",
            "--root",
            str(tmp_path),
            "--output",
            str(dirty_out),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND_ROOT),
    )
    assert dirty.returncode == 1
    assert "python-import" in dirty.stdout
    assert not dirty_out.exists()


def test_export_scripts_bash_n() -> None:
    root = resolve_root()
    export_sh = root / "scripts" / "export_submission.sh"
    verify_sh = root / "scripts" / "verify_export.sh"
    assert export_sh.is_file(), "scripts/export_submission.sh must exist"
    assert verify_sh.is_file(), "scripts/verify_export.sh must exist"
    for path in (export_sh, verify_sh):
        result = subprocess.run(
            ["/bin/bash", "-n", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{path.name}: {result.stderr}"


def test_real_package_exportignore_covers_zip_glob() -> None:
    text = (resolve_root() / EXPORTIGNORE_NAME).read_text(encoding="utf-8")
    assert "*.zip" in text
