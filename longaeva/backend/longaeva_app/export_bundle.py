"""Deterministic submission ZIP builder (LON-24 / PR-06, PR-07).

The isolation guard's ``.exportignore`` walk is the only definition of what ships.
A finding from :func:`longaeva_app.isolation_guard.scan` aborts the build and leaves
no ZIP behind. The archive is then read back and checked independently.
"""

from __future__ import annotations

import gzip
import os
import re
import stat
import tempfile
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from longaeva_app.hashing import sha256_hex
from longaeva_app.isolation_guard import Finding, format_findings, iter_export_files, scan

ZIP_PREFIX = "longaeva"
FIXED_DATE = (1980, 1, 1, 0, 0, 0)
STORE_SUFFIXES: frozenset[str] = frozenset({".gz", ".pdf", ".xlsx", ".xlsm", ".zip", ".png", ".jpg", ".jpeg"})
BANNED_PATH_PARTS: frozenset[str] = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", "var"})
ABS_PATH_BYTES_RE = re.compile(rb"(?:/Users|/home)/[A-Za-z0-9._-]+")
MIN_FORBID_LEN = 4


class ExportBundleError(Exception):
    """Raised when the guard or the ZIP self-check reports findings."""

    def __init__(self, findings: Sequence[Finding], message: str = "export bundle failed") -> None:
        self.findings = list(findings)
        super().__init__(message if not findings else format_findings(findings))


@dataclass(frozen=True, slots=True)
class ExportSummary:
    """Result of a successful ZIP build."""

    path: Path
    sha256: str
    file_count: int
    uncompressed_bytes: int
    zip_bytes: int


def load_forbid_file(path: Path) -> tuple[str, ...]:
    """Load non-empty, non-comment lines from ``path`` as forbidden substrings."""
    text = path.read_text(encoding="utf-8")
    values: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        values.append(line)
    return tuple(values)


def _rel_posix(root: Path, path: Path) -> str:
    return Path(os.path.relpath(os.path.abspath(path), os.path.abspath(root))).as_posix()


def _is_executable(path: Path) -> bool:
    try:
        return bool(os.lstat(path).st_mode & stat.S_IXUSR)
    except OSError:
        return False


def _zip_mode(path: Path) -> int:
    return 0o755 if _is_executable(path) else 0o644


def _compress_type(rel: str) -> int:
    suffix = Path(rel).suffix.lower()
    if suffix in STORE_SUFFIXES:
        return zipfile.ZIP_STORED
    return zipfile.ZIP_DEFLATED


def _make_zipinfo(arcname: str, *, mode: int, compress_type: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=arcname, date_time=FIXED_DATE)
    info.compress_type = compress_type
    info.create_system = 3  # Unix
    info.create_version = 20
    info.extract_version = 20
    info.flag_bits = 0
    info.external_attr = (stat.S_IFREG | (mode & 0o777)) << 16
    return info


def _write_zip(root: Path, dest: Path) -> tuple[int, int]:
    files = iter_export_files(root)
    file_count = 0
    uncompressed = 0
    with zipfile.ZipFile(
        dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=False
    ) as archive:
        archive.comment = b""
        for path in files:
            rel = _rel_posix(root, path)
            arcname = f"{ZIP_PREFIX}/{rel}"
            data = path.read_bytes()
            info = _make_zipinfo(arcname, mode=_zip_mode(path), compress_type=_compress_type(rel))
            archive.writestr(info, data)
            file_count += 1
            uncompressed += len(data)
    return file_count, uncompressed


def _inner_name(arcname: str) -> str | None:
    prefix = ZIP_PREFIX + "/"
    if not arcname.startswith(prefix):
        return None
    return arcname[len(prefix) :]


def _banned_part(inner: str) -> str | None:
    for part in Path(inner).parts:
        if part in BANNED_PATH_PARTS:
            return part
    return None


def _is_forbidden_env(inner: str) -> bool:
    name = Path(inner).name
    if name == ".env.example":
        return False
    return name == ".env" or name.startswith(".env.")


def _member_blobs(info: zipfile.ZipInfo, data: bytes) -> list[tuple[str, bytes]]:
    blobs: list[tuple[str, bytes]] = [("raw", data)]
    name = info.filename.lower()
    if name.endswith(".gz"):
        try:
            blobs.append(("gz", gzip.decompress(data)))
        except OSError:
            pass
    return blobs


def _redact_len(value: str) -> str:
    return f"(redacted, len={len(value)})"


def check_export_zip(path: Path, forbid: Sequence[str] = ()) -> list[Finding]:
    """Read ``path`` and return self-check findings (empty = clean)."""
    findings: list[Finding] = []
    forbid_values = [item for item in forbid if len(item) >= MIN_FORBID_LEN]
    try:
        archive = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as exc:
        return [Finding(rule="zip", path=str(path), line=None, detail=f"not a zip: {exc}")]

    with archive:
        names = archive.namelist()
        if not names:
            findings.append(Finding(rule="zip", path=str(path), line=None, detail="archive is empty"))
        for info in archive.infolist():
            name = info.filename
            if name.startswith("/") or name.startswith("\\") or name.startswith(ZIP_PREFIX + "\\"):
                findings.append(
                    Finding(rule="zip-path", path=name, line=None, detail="absolute or non-posix archive path")
                )
                continue
            if ".." in Path(name).parts:
                findings.append(Finding(rule="zip-path", path=name, line=None, detail="parent-segment in archive path"))
                continue
            if name.endswith("/"):
                findings.append(
                    Finding(rule="zip-path", path=name, line=None, detail="directory entries are not written")
                )
                continue
            if not name.startswith(ZIP_PREFIX + "/"):
                findings.append(
                    Finding(
                        rule="zip-path",
                        path=name,
                        line=None,
                        detail=f"entry must start with {ZIP_PREFIX}/",
                    )
                )
                continue
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(unix_mode):
                findings.append(Finding(rule="symlink", path=name, line=None, detail="symlink member"))
            inner = _inner_name(name)
            if inner is None:
                continue
            banned = _banned_part(inner)
            if banned is not None:
                findings.append(
                    Finding(rule="excluded-entry", path=name, line=None, detail=f"banned path part {banned!r}")
                )
            if _is_forbidden_env(inner):
                findings.append(Finding(rule="env-file", path=name, line=None, detail="`.env` files must not ship"))
            try:
                data = archive.read(info)
            except (KeyError, OSError, RuntimeError) as exc:
                findings.append(Finding(rule="zip", path=name, line=None, detail=f"unreadable member: {exc}"))
                continue
            for label, blob in _member_blobs(info, data):
                for match in ABS_PATH_BYTES_RE.finditer(blob):
                    findings.append(
                        Finding(
                            rule="absolute-path",
                            path=name,
                            line=None,
                            detail=f"{label} developer home path {_redact_len(match.group(0).decode('ascii', 'replace'))}",
                        )
                    )
                text = blob.decode("utf-8", errors="replace")
                for value in forbid_values:
                    if value in text:
                        findings.append(
                            Finding(
                                rule="personal-string",
                                path=name,
                                line=None,
                                detail=f"forbidden identity string {_redact_len(value)}",
                            )
                        )
    findings.sort(key=lambda f: (f.path, f.line or 0, f.rule, f.detail))
    return findings


def build_export_zip(root: Path, output: Path, forbid: Iterable[str] = ()) -> ExportSummary:
    """Scan ``root``, write a deterministic ZIP to ``output``, then self-check it."""
    resolved = root.resolve()
    findings = scan(resolved, strict=False)
    if findings:
        raise ExportBundleError(findings, "isolation guard failed; ZIP not written")

    out = Path(output)
    if not out.is_absolute():
        out = Path.cwd() / out
    out.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(prefix=out.name + ".", suffix=".partial", dir=out.parent)
    os.close(fd)
    tmp_path = Path(tmp_name)
    forbid_tuple = tuple(forbid)
    try:
        file_count, uncompressed = _write_zip(resolved, tmp_path)
        zip_findings = check_export_zip(tmp_path, forbid=forbid_tuple)
        if zip_findings:
            raise ExportBundleError(zip_findings, "ZIP self-check failed")
        os.replace(tmp_path, out)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        if out.exists() and out != tmp_path:
            # Leave a previously successful ZIP in place; only delete a partial.
            pass
        raise

    digest = sha256_hex(out.read_bytes())
    return ExportSummary(
        path=out,
        sha256=digest,
        file_count=file_count,
        uncompressed_bytes=uncompressed,
        zip_bytes=out.stat().st_size,
    )


def summary_payload(summary: ExportSummary) -> dict[str, object]:
    """JSON-serializable summary for the CLI."""
    return {
        "path": str(summary.path),
        "sha256": summary.sha256,
        "file_count": summary.file_count,
        "uncompressed_bytes": summary.uncompressed_bytes,
        "zip_bytes": summary.zip_bytes,
    }


__all__ = [
    "ExportBundleError",
    "ExportSummary",
    "ZIP_PREFIX",
    "build_export_zip",
    "check_export_zip",
    "load_forbid_file",
    "summary_payload",
]
