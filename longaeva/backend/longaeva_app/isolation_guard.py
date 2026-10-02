"""Static isolation guard for the Longaeva package export set (LON-12 / PR-02, PR-07).

Scans the would-be-exported file set (everything under the package root that is not
matched by ``.exportignore``) for:

* out-of-package Python / JS imports
* path escapes and absolute developer paths
* symlinks and non-regular files
* ``.env`` files that would ship
* secret-like strings and leaked local secret values

PDFs are scanned as raw bytes only (compressed streams are not inflated); that
limitation is recorded in ``docs/limitations.md``.
"""

from __future__ import annotations

import ast
import gzip
import importlib.metadata as importlib_metadata
import io
import json
import os
import re
import stat
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pathspec import GitIgnoreSpec

from longaeva_app.config import PACKAGE_ROOT

EXPORTIGNORE_NAME = ".exportignore"
GUARD_ROOT_ENV = "LONGAEVA_GUARD_ROOT"

# Known Talisman top-level import names that must never appear.
TALISMAN_TOP_LEVELS: frozenset[str] = frozenset(
    {
        "api",
        "auto_report",
        "backtest",
        "commodities",
        "conftest",
        "data_cache",
        "decision_quality",
        "equities",
        "fix_ruff",
        "fx",
        "government_bonds",
        "infra",
        "investment_overviews",
        "investment_theses",
        "llm_utils",
        "load_env",
        "macro",
        "ontology",
        "portfolio",
        "security",
        "utils",
    }
)

# Documented placeholder credentials that appear in Compose / config / tests.
URL_CREDENTIAL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "postgresql://longaeva:longaeva@",
        "postgres://u:p@",
        "postgresql://u:p@",
        "postgresql+psycopg://u:p@",
        "driver://user:pass@",
    }
)

TEXT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".md",
        ".csv",
        ".json",
        ".yaml",
        ".yml",
        ".txt",
        ".toml",
        ".html",
        ".htm",
        ".css",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".sh",
        ".ini",
        ".conf",
        ".example",
        ".ignore",
        ".gitignore",
        ".dockerignore",
        ".exportignore",
    }
)

TEXT_BASENAMES: frozenset[str] = frozenset(
    {
        "Makefile",
        "Dockerfile",
        "LICENSE",
        "LICENSE-NOTES.md",
        ".env.example",
        ".exportignore",
        ".gitignore",
        ".dockerignore",
    }
)

JS_SUFFIXES: frozenset[str] = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})

NODE_BUILTINS: frozenset[str] = frozenset(
    {
        "assert",
        "buffer",
        "child_process",
        "cluster",
        "console",
        "constants",
        "crypto",
        "dgram",
        "dns",
        "domain",
        "events",
        "fs",
        "http",
        "http2",
        "https",
        "module",
        "net",
        "os",
        "path",
        "perf_hooks",
        "process",
        "punycode",
        "querystring",
        "readline",
        "repl",
        "stream",
        "string_decoder",
        "timers",
        "tls",
        "tty",
        "url",
        "util",
        "v8",
        "vm",
        "worker_threads",
        "zlib",
        "node:assert",
        "node:buffer",
        "node:child_process",
        "node:crypto",
        "node:fs",
        "node:http",
        "node:https",
        "node:os",
        "node:path",
        "node:process",
        "node:stream",
        "node:url",
        "node:util",
        "node:zlib",
    }
)

MANIFEST_MUST_EXCLUDE: tuple[str, ...] = (
    ".env",
    "backend/.env",
    "frontend/.env.local",
    ".git/",
    ".venv/",
    "node_modules/",
    "__pycache__/",
    "var/",
)

MANIFEST_MUST_KEEP: tuple[str, ...] = (
    ".env.example",
    "README.md",
    "backend/longaeva_app/__init__.py",
    "data/fixtures/origins.csv",
    "docs/limitations.md",
)

LOCAL_SECRET_KEY_RE = re.compile(
    r"(?:^|[^A-Z0-9_])([A-Z][A-Z0-9_]*(?:USER_AGENT|API_KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Z0-9_]*)\s*=\s*(.*)$",
    re.MULTILINE,
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

ABS_PATH_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("unix-home", re.compile(r"(?:/Users|/home)/[A-Za-z0-9._-]+")),
    ("windows-home", re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+")),
    ("macos-tmpdir", re.compile(r"(?:/private)?/var/folders/[A-Za-z0-9_/+.-]+")),
)

SECRET_RES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("aws-access-key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("github-token", re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("openai-sk", re.compile(rb"sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("google-api-key", re.compile(rb"AIza[0-9A-Za-z_-]{35}")),
    ("slack-token", re.compile(rb"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("stripe-live", re.compile(rb"sk_live_[A-Za-z0-9]{20,}")),
    ("private-key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
)

URL_CRED_RE = re.compile(
    rb"([a-z][a-z0-9+.-]*://)([^/\s:@'\"\\]+)(:[^@\s'\"/\\]+)(@)",
    re.IGNORECASE,
)

GENERIC_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD))\s*[:=]\s*['\"]([A-Za-z0-9+/=_\-.]{16,})['\"]",
)

SYS_PATH_MUTATION_ATTRS: frozenset[str] = frozenset({"append", "insert", "extend"})

PATH_DOTDOT_RE = re.compile(r"(?:\.\./)+[^\s)\]\"'`>]*|\.\.(?:/|\\)")

JS_FROM_RE = re.compile(
    r"""(?:import|export)\s+(?:type\s+)?(?:[\w*{}\s,]+)\s+from\s+['"]([^'"]+)['"]""",
)
JS_REQUIRE_RE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""")
JS_DYNAMIC_IMPORT_RE = re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)""")

# Distribution name (lock / PyPI) -> known top-level import names when metadata is missing.
DIST_TOP_LEVEL_FALLBACK: dict[str, frozenset[str]] = {
    "pyyaml": frozenset({"yaml"}),
    "pydantic-settings": frozenset({"pydantic_settings"}),
    "types-pyyaml": frozenset({"yaml"}),
    "types-openpyxl": frozenset({"openpyxl"}),
    "types-psycopg2": frozenset({"psycopg2"}),
    "pillow": frozenset({"PIL"}),
    "pdfminer-six": frozenset({"pdfminer"}),
    "uvicorn": frozenset({"uvicorn"}),
    "sqlalchemy": frozenset({"sqlalchemy"}),
    "psycopg-binary": frozenset({"psycopg_binary"}),
}


@dataclass(frozen=True, slots=True)
class Finding:
    """One isolation-guard violation."""

    rule: str
    path: str
    line: int | None
    detail: str

    def format(self) -> str:
        loc = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{loc} [{self.rule}] {self.detail}"


def resolve_root(explicit: Path | None = None) -> Path:
    """Return the package root that contains ``.exportignore``.

    Preference order: ``explicit``, ``LONGAEVA_GUARD_ROOT``, then ``PACKAGE_ROOT``.
    """
    if explicit is not None:
        root = explicit.resolve()
    else:
        env = os.environ.get(GUARD_ROOT_ENV, "").strip()
        root = Path(env).resolve() if env else PACKAGE_ROOT.resolve()
    marker = root / EXPORTIGNORE_NAME
    if not marker.is_file():
        raise FileNotFoundError(
            f"Isolation guard root {root} has no {EXPORTIGNORE_NAME}; "
            f"set {GUARD_ROOT_ENV} or pass --root to the package directory."
        )
    return root


def load_exportignore(root: Path) -> GitIgnoreSpec:
    """Load ``.exportignore`` as a gitignore-style pathspec."""
    text = (root / EXPORTIGNORE_NAME).read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    return GitIgnoreSpec.from_lines(lines)


def _rel_posix(root: Path, path: Path) -> str:
    """Return ``path`` relative to ``root`` without following symlinks."""
    return Path(os.path.relpath(os.path.abspath(path), os.path.abspath(root))).as_posix()


def _is_excluded(spec: GitIgnoreSpec, rel: str, *, is_dir: bool) -> bool:
    candidate = rel + ("/" if is_dir and not rel.endswith("/") else "")
    return bool(spec.match_file(candidate))


def _is_dir_nofollow(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _is_file_nofollow(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _is_symlink(path: Path) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def iter_export_files(root: Path, *, strict: bool = False) -> list[Path]:
    """Return regular files and symlinks that would be included in the export.

    Walks without following symlinks. Directories matched by ``.exportignore`` are
    skipped entirely (unless ``strict`` is True, in which case their presence is
    still reported by :func:`scan` via the ``excluded-present`` rule, but this
    iterator still only yields included paths).
    """
    del strict  # reserved; exclusion presence is handled in scan()
    spec = load_exportignore(root)
    root = root.resolve()
    out: list[Path] = []
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                rel = _rel_posix(root, entry)
            except ValueError:
                continue
            is_dir = _is_dir_nofollow(entry)
            if _is_excluded(spec, rel, is_dir=is_dir):
                continue
            if _is_symlink(entry) or _is_file_nofollow(entry):
                out.append(entry)
            elif is_dir:
                stack.append(entry)
    out.sort(key=lambda p: _rel_posix(root, p))
    return out


def _parse_lock_distributions(lock_path: Path) -> set[str]:
    """Return normalized distribution names pinned in ``requirements.lock``."""
    if not lock_path.is_file():
        return set()
    names: set[str] = set()
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or line.startswith(" ") or "==" not in line:
            continue
        name = line.split("==", 1)[0].strip().lower().replace("_", "-")
        if name:
            names.add(name)
    return names


def _dist_to_top_levels(distributions: set[str]) -> set[str]:
    """Map pinned distributions to importable top-level names."""
    allowed: set[str] = set()
    packages_map = importlib_metadata.packages_distributions()
    for top, dists in packages_map.items():
        for dist in dists:
            if dist.lower().replace("_", "-") in distributions:
                allowed.add(top)
    for dist in distributions:
        allowed.update(DIST_TOP_LEVEL_FALLBACK.get(dist, ()))
        # Convention: most packages import as the name with dashes -> underscores.
        allowed.add(dist.replace("-", "_"))
    return allowed


def _test_helper_modules(root: Path) -> set[str]:
    """Top-level names provided by non-test modules under ``backend/tests/``."""
    tests_dir = root / "backend" / "tests"
    names: set[str] = set()
    if not tests_dir.is_dir():
        return names
    for path in tests_dir.iterdir():
        if path.name.startswith("test_") or path.name.startswith("_") or path.name == "conftest.py":
            continue
        if path.suffix == ".py" and path.is_file():
            names.add(path.stem)
        elif path.is_dir() and (path / "__init__.py").is_file():
            names.add(path.name)
    return names


def _collect_local_secrets(root: Path) -> dict[str, str]:
    """Collect secret values from ``<root>/.env`` and the process environment.

    Values shorter than 8 characters are ignored. Findings never print the value;
    only the key name is retained for attribution.
    """
    secrets: dict[str, str] = {}

    def _consider(key: str, raw: str) -> None:
        value = raw.strip().strip("'\"")
        if len(value) < 8:
            return
        secrets[value] = key
        for match in EMAIL_RE.finditer(value):
            secrets[match.group(0)] = f"{key}#email"

    env_path = root / ".env"
    if env_path.is_file():
        try:
            text = env_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        for match in LOCAL_SECRET_KEY_RE.finditer(text):
            _consider(match.group(1), match.group(2))

    key_re = re.compile(r"(?:USER_AGENT|API_KEY|TOKEN|SECRET|PASSWORD|PASSWD)", re.IGNORECASE)
    for key, value in os.environ.items():
        if key_re.search(key):
            _consider(key, value)
    return secrets


def _read_content_blobs(path: Path) -> list[tuple[str, bytes]]:
    """Return ``(label, bytes)`` blobs to scan for path/secret rules."""
    try:
        data = path.read_bytes()
    except OSError:
        return []
    suffix = path.suffix.lower()
    if suffix == ".gz":
        try:
            return [("gz", gzip.decompress(data))]
        except OSError:
            return [("raw", data)]
    if suffix in {".xlsx", ".xlsm", ".zip"}:
        blobs: list[tuple[str, bytes]] = [("raw", data)]
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for name in archive.namelist():
                    try:
                        blobs.append((name, archive.read(name)))
                    except (KeyError, OSError, RuntimeError):
                        continue
        except zipfile.BadZipFile:
            pass
        return blobs
    return [("raw", data)]


def _is_text_path(path: Path) -> bool:
    if path.name in TEXT_BASENAMES:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def _decode_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _redact(value: str, *, keep: int = 4) -> str:
    if len(value) <= keep * 2:
        return "***"
    return f"{value[:keep]}…{value[-keep:]} (redacted, len={len(value)})"


def check_manifest(root: Path, spec: GitIgnoreSpec) -> list[Finding]:
    """Verify ``.exportignore`` excludes secrets/tooling and keeps required paths."""
    findings: list[Finding] = []
    marker = EXPORTIGNORE_NAME
    for rel in MANIFEST_MUST_EXCLUDE:
        is_dir = rel.endswith("/")
        if not _is_excluded(spec, rel.rstrip("/"), is_dir=is_dir):
            findings.append(
                Finding(
                    rule="manifest",
                    path=marker,
                    line=None,
                    detail=f"must exclude {rel!r}",
                )
            )
    for rel in MANIFEST_MUST_KEEP:
        if _is_excluded(spec, rel, is_dir=False):
            findings.append(
                Finding(
                    rule="manifest",
                    path=marker,
                    line=None,
                    detail=f"must keep {rel!r}",
                )
            )
    return findings


def _scan_excluded_present(root: Path, spec: GitIgnoreSpec) -> list[Finding]:
    """Strict mode: report any path that exists but is excluded by the manifest."""
    findings: list[Finding] = []
    root = root.resolve()
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                rel = _rel_posix(root, entry)
            except ValueError:
                continue
            is_dir = _is_dir_nofollow(entry)
            if _is_excluded(spec, rel, is_dir=is_dir):
                findings.append(
                    Finding(
                        rule="excluded-present",
                        path=rel + ("/" if is_dir else ""),
                        line=None,
                        detail="path is excluded by .exportignore but present in the tree",
                    )
                )
                continue
            if is_dir and not _is_symlink(entry):
                stack.append(entry)
    return findings


def _scan_env_and_special(root: Path, files: Sequence[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        rel = _rel_posix(root, path)
        name = path.name
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            findings.append(
                Finding(
                    rule="env-file",
                    path=rel,
                    line=None,
                    detail="`.env` files must not ship; keep only `.env.example`",
                )
            )
        if _is_symlink(path):
            findings.append(
                Finding(
                    rule="symlink",
                    path=rel,
                    line=None,
                    detail=f"symlink target must not be exported (target={os.readlink(path)!r})",
                )
            )
        elif not _is_file_nofollow(path):
            findings.append(
                Finding(
                    rule="special-file",
                    path=rel,
                    line=None,
                    detail="non-regular file must not be exported",
                )
            )
    return findings


def _top_level_of(module: str) -> str:
    return module.split(".", 1)[0]


def _check_python_module_name(
    name: str,
    *,
    rel: str,
    line: int,
    allowed_third_party: set[str],
    test_helpers: set[str],
) -> Finding | None:
    top = _top_level_of(name)
    if not top or top == "__future__":
        return None
    if top in TALISMAN_TOP_LEVELS:
        return Finding(
            rule="python-import",
            path=rel,
            line=line,
            detail=f"Talisman module {name!r} is not allowed",
        )
    if top in sys.stdlib_module_names or top == "longaeva_app":
        return None
    if top in test_helpers:
        return None
    if top in allowed_third_party:
        return None
    return Finding(
        rule="python-import",
        path=rel,
        line=line,
        detail=f"import {name!r} is outside package namespace / pinned third-party deps",
    )


def _resolve_relative_import(file_path: Path, module: str | None, level: int) -> Path | None:
    """Resolve a relative import to a candidate directory/file under the package."""
    package_dir = file_path.parent
    # Climb ``level - 1`` parents from the containing package.
    target_dir = package_dir
    for _ in range(level - 1):
        target_dir = target_dir.parent
    if module:
        return target_dir.joinpath(*module.split("."))
    return target_dir


def _scan_python_file(
    root: Path,
    path: Path,
    *,
    allowed_third_party: set[str],
    test_helpers: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    rel = _rel_posix(root, path)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            Finding(rule="python-import", path=rel, line=None, detail=f"unreadable: {exc}"),
        ]
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as exc:
        return [
            Finding(
                rule="python-import",
                path=rel,
                line=exc.lineno,
                detail=f"syntax error: {exc.msg}",
            ),
        ]

    root_resolved = root.resolve()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                finding = _check_python_module_name(
                    alias.name,
                    rel=rel,
                    line=getattr(node, "lineno", 1),
                    allowed_third_party=allowed_third_party,
                    test_helpers=test_helpers,
                )
                if finding is not None:
                    findings.append(finding)
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            if level:
                resolved = _resolve_relative_import(path, node.module, level)
                if resolved is None:
                    continue
                try:
                    resolved.resolve().relative_to(root_resolved)
                except (ValueError, OSError):
                    findings.append(
                        Finding(
                            rule="python-import",
                            path=rel,
                            line=getattr(node, "lineno", 1),
                            detail=f"relative import escapes package root (level={level})",
                        )
                    )
            elif node.module:
                finding = _check_python_module_name(
                    node.module,
                    rel=rel,
                    line=getattr(node, "lineno", 1),
                    allowed_third_party=allowed_third_party,
                    test_helpers=test_helpers,
                )
                if finding is not None:
                    findings.append(finding)
        elif isinstance(node, ast.Call):
            findings.extend(
                _scan_dynamic_import_call(
                    node,
                    rel=rel,
                    allowed_third_party=allowed_third_party,
                    test_helpers=test_helpers,
                )
            )
            findings.extend(_scan_sys_path_mutation(node, rel=rel))
        findings.extend(
            _scan_path_parents(
                node,
                file_path=path,
                root=root_resolved,
                rel=rel,
                source=source,
            )
        )
    return findings


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _scan_dynamic_import_call(
    node: ast.Call,
    *,
    rel: str,
    allowed_third_party: set[str],
    test_helpers: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    func = node.func
    is_import_module = (
        isinstance(func, ast.Attribute)
        and func.attr == "import_module"
        and isinstance(func.value, ast.Name)
        and func.value.id in {"importlib", "import_module"}
    ) or (
        isinstance(func, ast.Attribute)
        and func.attr == "import_module"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "importlib"
    )
    is_dunder_import = isinstance(func, ast.Name) and func.id == "__import__"
    if not (is_import_module or is_dunder_import):
        # Also: importlib.import_module via Name if from-imported.
        if isinstance(func, ast.Name) and func.id == "import_module":
            is_import_module = True
        else:
            return findings
    if not node.args:
        return findings
    name = _const_str(node.args[0])
    if name is None:
        return findings
    finding = _check_python_module_name(
        name,
        rel=rel,
        line=getattr(node, "lineno", 1),
        allowed_third_party=allowed_third_party,
        test_helpers=test_helpers,
    )
    if finding is not None:
        findings.append(finding)
    return findings


def _scan_sys_path_mutation(node: ast.Call, *, rel: str) -> list[Finding]:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return []
    if func.attr not in SYS_PATH_MUTATION_ATTRS:
        return []
    # sys.path.append(...)
    target = func.value
    if isinstance(target, ast.Attribute) and target.attr == "path":
        if isinstance(target.value, ast.Name) and target.value.id == "sys":
            return [
                Finding(
                    rule="python-import",
                    path=rel,
                    line=getattr(node, "lineno", 1),
                    detail=f"sys.path.{func.attr}(...) mutates import path",
                )
            ]
    return []


def _ast_mentions_file(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id == "__file__":
            return True
    return False


def _scan_path_parents(
    node: ast.AST,
    *,
    file_path: Path,
    root: Path,
    rel: str,
    source: str,
) -> list[Finding]:
    """Flag ``Path(__file__).resolve().parents[k]`` that resolve outside the root."""
    del source  # reserved for richer source-segment messaging later
    if not isinstance(node, ast.Subscript):
        return []
    if not isinstance(node.value, ast.Attribute) or node.value.attr != "parents":
        return []
    slice_node = node.slice
    if not isinstance(slice_node, ast.Constant) or not isinstance(slice_node.value, int):
        return []
    k = slice_node.value
    if k < 0:
        return []
    if not _ast_mentions_file(node.value):
        return []

    try:
        resolved = file_path.resolve().parents[k]
    except IndexError:
        return [
            Finding(
                rule="python-import",
                path=rel,
                line=getattr(node, "lineno", 1),
                detail=f"Path(__file__).parents[{k}] index out of range",
            )
        ]
    try:
        resolved.relative_to(root)
    except ValueError:
        return [
            Finding(
                rule="python-import",
                path=rel,
                line=getattr(node, "lineno", 1),
                detail=f"Path(__file__).parents[{k}] resolves outside package root",
            )
        ]
    return []


def _package_json_deps(root: Path) -> set[str]:
    """Collect dependency names declared in any ``package.json`` under the root."""
    names: set[str] = set()
    for path in root.rglob("package.json"):
        if any(part in {".venv", "node_modules", ".git"} for part in path.parts):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            block = data.get(section) or {}
            if isinstance(block, dict):
                names.update(str(k) for k in block)
                for value in block.values():
                    if isinstance(value, str) and (value.startswith("file:") or value.startswith("link:")):
                        # file:/link: targets are checked separately per import site.
                        pass
    return names


def _scan_js_file(root: Path, path: Path, *, declared_deps: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    rel = _rel_posix(root, path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding(rule="js-import", path=rel, line=None, detail=f"unreadable: {exc}")]

    specs: list[tuple[int, str]] = []
    for pattern in (JS_FROM_RE, JS_REQUIRE_RE, JS_DYNAMIC_IMPORT_RE):
        for match in pattern.finditer(text):
            specs.append((_line_of(text, match.start()), match.group(1)))

    root_resolved = root.resolve()
    for line, spec in specs:
        if spec.startswith("@/"):
            # Alias; path-escape on config files covers the definition.
            continue
        if spec.startswith(".") or spec.startswith("/"):
            # Relative / absolute path-like specifier.
            if spec.startswith("/"):
                findings.append(
                    Finding(
                        rule="js-import",
                        path=rel,
                        line=line,
                        detail=f"absolute import specifier {spec!r}",
                    )
                )
                continue
            candidate = (path.parent / spec).resolve()
            try:
                candidate.relative_to(root_resolved)
            except ValueError:
                findings.append(
                    Finding(
                        rule="js-import",
                        path=rel,
                        line=line,
                        detail=f"relative import {spec!r} escapes package root",
                    )
                )
            continue
        # Bare / scoped package.
        bare = spec
        if bare.startswith("node:"):
            if bare not in NODE_BUILTINS and bare.removeprefix("node:") not in NODE_BUILTINS:
                # Still allow any node: builtin prefix.
                pass
            continue
        if bare in NODE_BUILTINS:
            continue
        pkg = bare if not bare.startswith("@") else "/".join(bare.split("/")[:2])
        if bare.startswith("@"):
            top = pkg
        else:
            top = bare.split("/", 1)[0]
        if top in declared_deps or pkg in declared_deps:
            continue
        # file: / link: handled via package.json scan below; bare unknown = finding.
        findings.append(
            Finding(
                rule="js-import",
                path=rel,
                line=line,
                detail=f"undeclared dependency {spec!r}",
            )
        )

    # package.json file:/link: dependency targets.
    if path.name == "package.json":
        findings.extend(_scan_package_json_file_deps(root, path, text))
    return findings


def _scan_package_json_file_deps(root: Path, path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return findings
    rel = _rel_posix(root, path)
    root_resolved = root.resolve()
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        block = data.get(section) or {}
        if not isinstance(block, dict):
            continue
        for name, value in block.items():
            if not isinstance(value, str):
                continue
            if not (value.startswith("file:") or value.startswith("link:")):
                continue
            target = value.split(":", 1)[1]
            candidate = (path.parent / target).resolve()
            try:
                candidate.relative_to(root_resolved)
            except ValueError:
                findings.append(
                    Finding(
                        rule="js-import",
                        path=rel,
                        line=None,
                        detail=f"{section}.{name} {value!r} resolves outside package root",
                    )
                )
    return findings


def _scan_path_escape(root: Path, path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    rel = _rel_posix(root, path)
    root_resolved = root.resolve()
    for match in PATH_DOTDOT_RE.finditer(text):
        raw = match.group(0)
        # Skip pure language / regex discussion without a path-like continuation.
        candidate_str = raw.rstrip(".,;:)]}\"'>")
        if candidate_str in {"..", "../", "..\\"}:
            # Alone in prose is noisy; only flag when it participates in a path join.
            # Still check resolution of "../" relative to the file.
            pass
        try:
            # Resolve relative to the file's directory.
            resolved = (path.parent / candidate_str).resolve()
        except (OSError, RuntimeError):
            continue
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            findings.append(
                Finding(
                    rule="path-escape",
                    path=rel,
                    line=_line_of(text, match.start()),
                    detail=f"path {candidate_str!r} resolves outside package root",
                )
            )
    return findings


def _scan_absolute_paths(rel: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for label, pattern in ABS_PATH_RES:
        for match in pattern.finditer(text):
            findings.append(
                Finding(
                    rule="absolute-path",
                    path=rel,
                    line=_line_of(text, match.start()),
                    detail=f"{label} path {_redact(match.group(0), keep=6)}",
                )
            )
    return findings


def _scan_secrets_bytes(rel: str, label: str, data: bytes) -> list[Finding]:
    findings: list[Finding] = []
    for rule_label, pattern in SECRET_RES:
        for match in pattern.finditer(data):
            snippet = match.group(0).decode("utf-8", errors="replace")
            findings.append(
                Finding(
                    rule="secret",
                    path=rel,
                    line=None if label != "raw" else _line_of(_decode_text(data), match.start()),
                    detail=f"{rule_label} {_redact(snippet)}",
                )
            )
    for match in URL_CRED_RE.finditer(data):
        full = match.group(0).decode("utf-8", errors="replace")
        # Rebuild without consuming password for allowlist check of prefix form.
        prefix = (
            match.group(1).decode("utf-8", errors="replace")
            + match.group(2).decode("utf-8", errors="replace")
            + match.group(3).decode("utf-8", errors="replace")
            + match.group(4).decode("utf-8", errors="replace")
        )
        # Allowlist compares the scheme://user:pass@ prefix.
        allowed = any(prefix.startswith(item) or full.startswith(item) for item in URL_CREDENTIAL_ALLOWLIST)
        # Also allow if the user:pass portion is a known placeholder pair.
        user = match.group(2).decode("utf-8", errors="replace")
        password = match.group(3).decode("utf-8", errors="replace").lstrip(":")
        if (user, password) in {("longaeva", "longaeva"), ("u", "p"), ("user", "pass")}:
            allowed = True
        if allowed:
            continue
        findings.append(
            Finding(
                rule="secret",
                path=rel,
                line=None,
                detail=f"url-credentials {_redact(full)}",
            )
        )
    return findings


def _scan_generic_secret_assignments(rel: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in GENERIC_SECRET_ASSIGN_RE.finditer(text):
        key = match.group(1)
        value = match.group(2)
        # Skip obvious placeholders / empty-looking.
        if value.lower() in {"your_api_key_here", "changeme", "placeholder", "example", "xxx"}:
            continue
        if not re.search(r"[A-Za-z]", value) or not re.search(r"[0-9]", value):
            continue
        findings.append(
            Finding(
                rule="secret",
                path=rel,
                line=_line_of(text, match.start()),
                detail=f"generic-assignment {key}={_redact(value)}",
            )
        )
    return findings


def _scan_local_secrets(rel: str, text: str, secrets: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    if not secrets:
        return findings
    # Prefer longer values first so a full UA string wins over an embedded email.
    ordered = sorted(secrets.items(), key=lambda kv: len(kv[0]), reverse=True)
    seen_spans: list[tuple[int, int]] = []
    for value, key in ordered:
        start = 0
        while True:
            idx = text.find(value, start)
            if idx < 0:
                break
            end = idx + len(value)
            if any(idx < s_end and end > s_start for s_start, s_end in seen_spans):
                start = end
                continue
            seen_spans.append((idx, end))
            findings.append(
                Finding(
                    rule="local-secret",
                    path=rel,
                    line=_line_of(text, idx),
                    detail=f"value of {key} appears in export set",
                )
            )
            start = end
    return findings


def _scan_content_rules(
    root: Path,
    path: Path,
    *,
    local_secrets: dict[str, str],
) -> list[Finding]:
    findings: list[Finding] = []
    rel = _rel_posix(root, path)
    for label, data in _read_content_blobs(path):
        findings.extend(_scan_secrets_bytes(rel, label, data))
        # Text-oriented rules on decodable blobs.
        if label == "raw" and not _is_text_path(path) and path.suffix.lower() not in {".gz"}:
            # Still decode gz above; for pdf/xlsx raw we only do byte secret patterns.
            if path.suffix.lower() in {".pdf", ".xlsx", ".xlsm", ".zip", ".png", ".jpg", ".jpeg"}:
                continue
        text = _decode_text(data)
        if label == "raw" and _is_text_path(path):
            findings.extend(_scan_path_escape(root, path, text))
            findings.extend(_scan_absolute_paths(rel, text))
            findings.extend(_scan_generic_secret_assignments(rel, text))
            findings.extend(_scan_local_secrets(rel, text, local_secrets))
        elif label == "gz":
            # Decompressed HTML/text originals.
            findings.extend(_scan_absolute_paths(rel, text))
            findings.extend(_scan_local_secrets(rel, text, local_secrets))
    return findings


def scan(root: Path | None = None, *, strict: bool = False) -> list[Finding]:
    """Run all isolation-guard rules and return findings (empty = clean)."""
    resolved = resolve_root(root)
    spec = load_exportignore(resolved)
    findings: list[Finding] = []
    findings.extend(check_manifest(resolved, spec))
    if strict:
        findings.extend(_scan_excluded_present(resolved, spec))

    files = iter_export_files(resolved, strict=strict)
    findings.extend(_scan_env_and_special(resolved, files))

    lock_path = resolved / "backend" / "requirements.lock"
    distributions = _parse_lock_distributions(lock_path)
    allowed_third_party = _dist_to_top_levels(distributions)
    test_helpers = _test_helper_modules(resolved)
    declared_deps = _package_json_deps(resolved)
    local_secrets = _collect_local_secrets(resolved)

    for path in files:
        if _is_symlink(path) or not _is_file_nofollow(path):
            continue
        suffix = path.suffix.lower()
        if suffix == ".py":
            findings.extend(
                _scan_python_file(
                    resolved,
                    path,
                    allowed_third_party=allowed_third_party,
                    test_helpers=test_helpers,
                )
            )
        if suffix in JS_SUFFIXES or path.name == "package.json":
            findings.extend(_scan_js_file(resolved, path, declared_deps=declared_deps))
        findings.extend(_scan_content_rules(resolved, path, local_secrets=local_secrets))

    findings.sort(key=lambda f: (f.path, f.line or 0, f.rule, f.detail))
    return findings


def format_findings(findings: Sequence[Finding]) -> str:
    if not findings:
        return "isolation guard: 0 findings"
    lines = [f.format() for f in findings]
    lines.append(f"isolation guard: {len(findings)} finding(s)")
    return "\n".join(lines)


def list_export_paths(root: Path | None = None) -> list[str]:
    """Return relative POSIX paths in the export set (for LON-24 ZIP builders)."""
    resolved = resolve_root(root)
    return [_rel_posix(resolved, path) for path in iter_export_files(resolved)]


__all__ = [
    "EXPORTIGNORE_NAME",
    "Finding",
    "check_manifest",
    "format_findings",
    "iter_export_files",
    "list_export_paths",
    "load_exportignore",
    "resolve_root",
    "scan",
]
