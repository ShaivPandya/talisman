"""Isolation guard tests (LON-12).

Negative fixtures live under ``tmp_path`` so deliberate bad strings never enter the
real package export set. Bad literals in this file are split across concatenations
so a scan of the package itself stays clean.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from longaeva_app.isolation_guard import (
    EXPORTIGNORE_NAME,
    Finding,
    check_manifest,
    format_findings,
    iter_export_files,
    list_export_paths,
    load_exportignore,
    resolve_root,
    scan,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Split so this test file itself does not contain the forbidden substrings.
USERS_PREFIX = "/" + "Users" + "/"
TALISMAN_API = "ap" + "i"
FAKE_HOME = USERS_PREFIX + "exampledev" + "/project"


def _real_package_root() -> Path:
    """Package root visible to the guard (LONGAEVA_GUARD_ROOT inside Compose)."""
    return resolve_root()


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
"""


def _write_package(root: Path, *, exportignore: str | None = None) -> None:
    """Create a minimal package tree the guard can scan."""
    (root / EXPORTIGNORE_NAME).write_text(
        exportignore if exportignore is not None else _minimal_exportignore(),
        encoding="utf-8",
    )
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


def test_resolve_root_requires_exportignore(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_root(tmp_path)


def test_real_package_root_resolves() -> None:
    root = _real_package_root()
    assert (root / EXPORTIGNORE_NAME).is_file()


def test_manifest_covers_required_paths() -> None:
    root = _real_package_root()
    spec = load_exportignore(root)
    findings = check_manifest(root, spec)
    assert findings == [], format_findings(findings)


def test_real_package_scans_clean() -> None:
    root = _real_package_root()
    assert (root / EXPORTIGNORE_NAME).is_file(), "package root must be visible to the guard"
    findings = scan(root, strict=False)
    assert findings == [], format_findings(findings)


def test_export_file_set_excludes_env_and_venv() -> None:
    root = _real_package_root()
    rels = set(list_export_paths(root))
    assert ".env.example" in rels
    assert EXPORTIGNORE_NAME in rels
    assert ".env" not in rels
    assert not any(r.startswith(".venv/") or "/.venv/" in r for r in rels)
    assert not any("__pycache__" in r for r in rels)


def test_negative_python_import_talisman_api(tmp_path: Path) -> None:
    _write_package(tmp_path)
    bad = tmp_path / "backend" / "longaeva_app" / "bad_import.py"
    # Deliberate acceptance case: from api import x
    bad.write_text(f"from {TALISMAN_API} import x\n", encoding="utf-8")
    findings = scan(tmp_path)
    rules = {(f.rule, f.path) for f in findings}
    assert ("python-import", "backend/longaeva_app/bad_import.py") in rules


def test_negative_absolute_users_path(tmp_path: Path) -> None:
    _write_package(tmp_path)
    doc = tmp_path / "docs" / "leak.md"
    doc.write_text(f"path is {FAKE_HOME}/file\n", encoding="utf-8")
    findings = scan(tmp_path)
    abs_findings = [f for f in findings if f.rule == "absolute-path"]
    assert abs_findings, format_findings(findings)
    assert any("unix-home" in f.detail for f in abs_findings)


def test_negative_symlink(tmp_path: Path) -> None:
    _write_package(tmp_path)
    target = tmp_path / "README.md"
    link = tmp_path / "docs" / "readme.link"
    link.symlink_to(target)
    findings = scan(tmp_path)
    assert any(f.rule == "symlink" and f.path == "docs/readme.link" for f in findings)


def test_negative_env_file_in_export_set(tmp_path: Path) -> None:
    # Manifest that fails to exclude .env — the file then enters the export set.
    _write_package(
        tmp_path,
        exportignore="""\
.git/
.venv/
__pycache__/
node_modules/
var/
""",
    )
    (tmp_path / ".env").write_text("SEC_USER_AGENT=Example Contact me@example.com\n", encoding="utf-8")
    findings = scan(tmp_path, strict=False)
    assert any(f.rule == "env-file" and f.path == ".env" for f in findings)
    assert any(f.rule == "manifest" for f in findings)


def test_strict_reports_excluded_env_present(tmp_path: Path) -> None:
    _write_package(tmp_path)
    (tmp_path / ".env").write_text("SEC_USER_AGENT=Example Contact me@example.com\n", encoding="utf-8")
    # Non-strict: .env is excluded from the walk, so env-file does not fire.
    cleanish = [f for f in scan(tmp_path, strict=False) if f.rule in {"env-file", "excluded-present"}]
    assert cleanish == []
    strict_findings = scan(tmp_path, strict=True)
    assert any(f.rule == "excluded-present" and f.path.startswith(".env") for f in strict_findings)


def test_placeholder_url_credentials_allowed(tmp_path: Path) -> None:
    _write_package(tmp_path)
    cfg = tmp_path / "backend" / "longaeva_app" / "cfg.py"
    cfg.write_text(
        'URL = "postgresql://longaeva:longaeva@127.0.0.1:5432/longaeva"\n'
        'OTHER = "driver://user:pass@localhost/dbname"\n',
        encoding="utf-8",
    )
    findings = [f for f in scan(tmp_path) if f.rule == "secret"]
    assert findings == [], format_findings(findings)


def test_secret_sk_key_flagged(tmp_path: Path) -> None:
    _write_package(tmp_path)
    leak = tmp_path / "docs" / "keys.md"
    # Synthetic OpenAI-shaped key (not real).
    fake = "sk-" + ("x" * 48)
    leak.write_text(f"key={fake}\n", encoding="utf-8")
    findings = [f for f in scan(tmp_path) if f.rule == "secret"]
    assert findings, format_findings(scan(tmp_path))
    assert all("redacted" in f.detail for f in findings)


def test_local_secret_leak_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_package(tmp_path)
    secret_value = "UniqueGuardProbeSecret99"
    monkeypatch.setenv("LONGAEVA_TEST_API_KEY", secret_value)
    doc = tmp_path / "docs" / "oops.md"
    doc.write_text(f"do not paste {secret_value} into docs\n", encoding="utf-8")
    findings = [f for f in scan(tmp_path) if f.rule == "local-secret"]
    assert findings, format_findings(scan(tmp_path))
    assert all(secret_value not in f.detail for f in findings)
    assert any("LONGAEVA_TEST_API_KEY" in f.detail for f in findings)


def test_path_escape_outside_root(tmp_path: Path) -> None:
    _write_package(tmp_path)
    doc = tmp_path / "docs" / "escape.md"
    # From docs/, three parent segments leave the package root. Built without a
    # contiguous "../" literal so this test file itself stays clean under scan.
    up = ".." + "/"
    escape = up + up + up + "outside.txt"
    doc.write_text(f"see [x]({escape})\n", encoding="utf-8")
    findings = [f for f in scan(tmp_path) if f.rule == "path-escape"]
    assert findings, format_findings(scan(tmp_path))


def test_js_undeclared_dependency(tmp_path: Path) -> None:
    _write_package(tmp_path)
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "main.ts").write_text('import x from "left-pad";\n', encoding="utf-8")
    findings = [f for f in scan(tmp_path) if f.rule == "js-import"]
    assert findings, format_findings(scan(tmp_path))


def test_cli_export_check_clean_and_dirty(tmp_path: Path) -> None:
    _write_package(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
    clean = subprocess.run(
        [sys.executable, "-m", "longaeva_app.cli", "export-check", "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND_ROOT),
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "0 findings" in clean.stdout

    bad = tmp_path / "backend" / "longaeva_app" / "bad.py"
    bad.write_text(f"from {TALISMAN_API} import x\n", encoding="utf-8")
    dirty = subprocess.run(
        [sys.executable, "-m", "longaeva_app.cli", "export-check", "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND_ROOT),
    )
    assert dirty.returncode == 1
    assert "python-import" in dirty.stdout


def test_cli_list_and_strict(tmp_path: Path) -> None:
    _write_package(tmp_path)
    (tmp_path / ".env").write_text("SEC_USER_AGENT=Example Contact me@example.com\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
    listed = subprocess.run(
        [sys.executable, "-m", "longaeva_app.cli", "export-check", "--root", str(tmp_path), "--list"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND_ROOT),
    )
    assert listed.returncode == 0
    assert ".env.example" in listed.stdout
    assert ".env\n" not in listed.stdout and not listed.stdout.strip().endswith(".env")

    strict = subprocess.run(
        [sys.executable, "-m", "longaeva_app.cli", "export-check", "--root", str(tmp_path), "--strict"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND_ROOT),
    )
    assert strict.returncode == 1
    assert "excluded-present" in strict.stdout


def test_format_findings_redaction_shape() -> None:
    finding = Finding(rule="secret", path="docs/x.md", line=3, detail="openai-sk abcd…wxyz (redacted, len=51)")
    text = format_findings([finding])
    assert "docs/x.md:3 [secret]" in text
    assert "1 finding(s)" in text


def test_iter_export_files_skips_excluded_dir(tmp_path: Path) -> None:
    _write_package(tmp_path)
    cache = tmp_path / "backend" / "longaeva_app" / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"\0")
    rels = {path.resolve().relative_to(tmp_path.resolve()).as_posix() for path in iter_export_files(tmp_path)}
    assert not any("__pycache__" in r for r in rels)
