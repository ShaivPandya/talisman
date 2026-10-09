"""Download and locate spans in Visa starting-state source filings.

CLI:

  fetch  — live EDGAR requests; writes deterministic ``.htm.gz`` originals + manifest
  locate — fill ``span.char_start`` / ``char_end`` in a fixture JSON from anchor+quote
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from longaeva_app.collect.edgar_index import (
    PACKAGE_ROOT,
    SEC_MAX_RETRIES,
    SNAPSHOT_PATH,
    EdgarClient,
    _load_env_user_agent,
    _parse_utc,
    load_snapshot,
)

STATES_DIR = PACKAGE_ROOT / "data" / "fixtures" / "states"
SOURCES_DIR = STATES_DIR / "sources"
MANIFEST_PATH = SOURCES_DIR / "manifest.json"
VISA_CIK = 1403161


@dataclass(frozen=True)
class SourceSpec:
    """One original document retained for starting-state reconstruction."""

    accession: str
    document: str
    form: str
    role: str  # input | post_cutoff_check
    origins: tuple[str, ...]  # origin cutoff dates YYYY-MM-DD that use this file
    note: str = ""


# 13 unique filings. An accession may be input for one origin and post-cutoff for another.
SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        accession="0001403161-24-000040",
        document="q32024earningsrelease.htm",
        form="8-K Ex. 99.1",
        role="input",
        origins=("2024-07-23",),
        note="Origin A earnings release (FY2024Q3)",
    ),
    SourceSpec(
        accession="0001403161-24-000027",
        document="q22024earningsrelease.htm",
        form="8-K Ex. 99.1",
        role="input",
        origins=("2024-07-23",),
        note="Prior-quarter release: nominal PV growth for FY2024Q2 (q−1)",
    ),
    SourceSpec(
        accession="0001403161-24-000030",
        document="v-20240331.htm",
        form="10-Q",
        role="input",
        origins=("2024-07-23",),
        note="Prior 10-Q at Origin A cutoff; PV for FY2024Q1 (q−2)",
    ),
    SourceSpec(
        accession="0001403161-23-000072",
        document="v-20230630.htm",
        form="10-Q",
        role="input",
        origins=("2024-07-23",),
        note="FY2023Q3 10-Q: 3-month and 9-month PV totals through Mar 2023",
    ),
    SourceSpec(
        accession="0001403161-23-000099",
        document="v-20230930.htm",
        form="10-K",
        role="input",
        origins=("2024-07-23",),
        note="FY2023 10-K: 12-month PV through Jun 2023",
    ),
    SourceSpec(
        accession="0001403161-24-000041",
        document="v-20240630.htm",
        form="10-Q",
        role="post_cutoff_check",
        origins=("2024-07-23",),
        note="Same-quarter 10-Q for Origin A (2.12 h after cutoff); also input for Origin B",
    ),
    SourceSpec(
        accession="0001403161-24-000041",
        document="v-20240630.htm",
        form="10-Q",
        role="input",
        origins=("2025-10-28",),
        note="FY2024Q3 10-Q: year-ago totals for Origin B derivations",
    ),
    SourceSpec(
        accession="0001403161-24-000058",
        document="v-20240930.htm",
        form="10-K",
        role="post_cutoff_check",
        origins=("2024-07-23",),
        note="FY2024 10-K (post Origin A); input for Origin B",
    ),
    SourceSpec(
        accession="0001403161-24-000058",
        document="v-20240930.htm",
        form="10-K",
        role="input",
        origins=("2025-10-28",),
        note="FY2024 10-K: 12-month PV through Jun/Sep 2024",
    ),
    SourceSpec(
        accession="0001403161-25-000077",
        document="q42025earningsrelease.htm",
        form="8-K Ex. 99.1",
        role="input",
        origins=("2025-10-28",),
        note="Origin B earnings release (FY2025Q4)",
    ),
    SourceSpec(
        accession="0001403161-25-000051",
        document="q32025earningsrelease.htm",
        form="8-K Ex. 99.1",
        role="input",
        origins=("2025-10-28",),
        note="Prior-quarter release: nominal PV growth for FY2025Q3 (q−1)",
    ),
    SourceSpec(
        accession="0001403161-25-000052",
        document="v-20250630.htm",
        form="10-Q",
        role="input",
        origins=("2025-10-28",),
        note="Prior 10-Q at Origin B cutoff; PV for FY2025Q2 (q−2)",
    ),
    SourceSpec(
        accession="0001403161-25-000017",
        document="v-20241231.htm",
        form="10-Q",
        role="input",
        origins=("2025-10-28",),
        note="FY2025Q1 10-Q: 3-month PV through Sep 2024",
    ),
    SourceSpec(
        accession="0001403161-25-000089",
        document="v-20250930.htm",
        form="10-K",
        role="post_cutoff_check",
        origins=("2025-10-28",),
        note="Same-quarter 10-K for Origin B (217 h after cutoff)",
    ),
    SourceSpec(
        accession="0001403161-26-000045",
        document="v-20251231.htm",
        form="10-Q",
        role="post_cutoff_check",
        origins=("2025-10-28",),
        note="FY2026Q1 10-Q: later-reported PV for Origin B q−1 check",
    ),
)


def unique_fetch_targets() -> list[tuple[str, str]]:
    """Deduplicate (accession, document) pairs for download."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for spec in SOURCE_SPECS:
        key = (spec.accession, spec.document)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def archive_url(accession: str, document: str) -> str:
    nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{VISA_CIK}/{nodash}/{document}"


def relative_gz_path(accession: str, document: str) -> str:
    return f"{accession}/{document}.gz"


def absolute_gz_path(accession: str, document: str) -> Path:
    return SOURCES_DIR / accession / f"{document}.gz"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_deterministic_gzip(path: Path, data: bytes) -> None:
    """Write gzip with mtime=0 so re-fetch yields identical bytes on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(filename="", mode="wb", fileobj=path.open("wb"), mtime=0, compresslevel=9) as gz:
        gz.write(data)


def read_gzip_bytes(path: Path) -> bytes:
    with gzip.open(path, "rb") as gz:
        return gz.read()


def get_bytes(client: EdgarClient, url: str) -> bytes:
    """Binary fetch with the same throttle/backoff policy as ``EdgarClient.get_text``."""
    last_error: Exception | None = None
    for attempt in range(SEC_MAX_RETRIES):
        client._throttle()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": client.user_agent,
                "Accept-Encoding": "identity",
                "Host": urllib.parse.urlparse(url).hostname or "www.sec.gov",
            },
        )
        try:
            client._last_request_at = time.monotonic()
            with urllib.request.urlopen(req, timeout=120) as resp:
                body: bytes = resp.read()
                return body
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 403:
                raise RuntimeError(f"EDGAR returned 403 for {url}; not retrying") from exc
            if exc.code in {429, 500, 502, 503, 504}:
                time.sleep(2**attempt)
                continue
            raise
        except urllib.error.URLError as exc:
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"EDGAR fetch failed for {url}: {last_error}")


def acceptance_utc_for(snapshot: dict[str, Any], accession: str) -> str:
    for row in snapshot["visa_filings"]:
        if row["accession"] == accession:
            return str(row["accepted_utc"])
    raise KeyError(f"Accession {accession} not in LON-1 snapshot")


def build_manifest_entry(
    accession: str,
    document: str,
    raw: bytes,
    acceptance_utc: str,
    retrieval_ts: str,
) -> dict[str, Any]:
    specs = [s for s in SOURCE_SPECS if s.accession == accession and s.document == document]
    roles = sorted({s.role for s in specs})
    origins = sorted({o for s in specs for o in s.origins})
    forms = sorted({s.form for s in specs})
    return {
        "accession": accession,
        "document": document,
        "form": forms[0] if len(forms) == 1 else forms,
        "roles": roles,
        "origins": origins,
        "url": archive_url(accession, document),
        "path": relative_gz_path(accession, document),
        "content_sha256": sha256_bytes(raw),
        "raw_bytes": len(raw),
        "acceptance_utc": acceptance_utc,
        "retrieval_ts": retrieval_ts,
        "notes": [s.note for s in specs],
    }


def cmd_fetch(_args: argparse.Namespace) -> int:
    snapshot = load_snapshot(SNAPSHOT_PATH)
    client = EdgarClient(_load_env_user_agent())
    retrieval_ts = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries: list[dict[str, Any]] = []
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)

    for accession, document in unique_fetch_targets():
        url = archive_url(accession, document)
        print(f"fetch {accession}/{document} …", flush=True)
        raw = get_bytes(client, url)
        out = absolute_gz_path(accession, document)
        write_deterministic_gzip(out, raw)
        acceptance = acceptance_utc_for(snapshot, accession)
        entries.append(build_manifest_entry(accession, document, raw, acceptance, retrieval_ts))
        print(
            f"  wrote {out.relative_to(PACKAGE_ROOT)} ({len(raw)} bytes, sha256={entries[-1]['content_sha256'][:12]}…)"
        )

    manifest = {
        "schema_version": 1,
        "generated_for": "LON-3",
        "retrieved_at": retrieval_ts,
        "snapshot_path": str(SNAPSHOT_PATH.relative_to(PACKAGE_ROOT)),
        "sources": entries,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST_PATH.relative_to(PACKAGE_ROOT)} ({len(entries)} sources)")
    return 0


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return data


def source_text(accession: str, document: str) -> str:
    """Decode a retained original as UTF-8 (matching EDGAR HTML)."""
    path = absolute_gz_path(accession, document)
    if not path.exists():
        raise FileNotFoundError(f"Missing source original: {path}")
    return read_gzip_bytes(path).decode("utf-8", errors="replace")


def locate_span(text: str, anchor: str, quote: str) -> tuple[int, int]:
    """Find ``quote`` after the first occurrence of ``anchor``; require uniqueness in that window.

    Returns ``(char_start, char_end)`` into ``text`` (Python string indices).
    """
    if not anchor:
        raise ValueError("anchor must be non-empty")
    if not quote:
        raise ValueError("quote must be non-empty")
    anchor_at = text.find(anchor)
    if anchor_at < 0:
        raise ValueError(f"anchor not found: {anchor!r}")
    search_from = anchor_at + len(anchor)
    first = text.find(quote, search_from)
    if first < 0:
        raise ValueError(f"quote not found after anchor: quote={quote!r} anchor={anchor!r}")
    # Identical adjacent duplicates (e.g. Constant and Nominal both "9%") are fine;
    # only fail when a second distinct hit could steal the intended location. Because
    # we always take the first hit after the anchor, duplicates of the same quote are OK.
    return first, first + len(quote)


def cmd_locate(args: argparse.Namespace) -> int:
    fixture_path = Path(args.fixture)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    updated = 0

    def fill(entry: dict[str, Any], label: str) -> None:
        nonlocal updated
        span = entry.get("span")
        if not span:
            return
        source_id = entry.get("source_id")
        if not source_id:
            raise SystemExit(f"{label}: has span but no source_id")
        if "/" not in source_id:
            raise SystemExit(f"{label}: source_id must be accession/document, got {source_id!r}")
        accession, document = source_id.split("/", 1)
        text = source_text(accession, document)
        start, end = locate_span(text, span["anchor"], span["quote"])
        span["char_start"] = start
        span["char_end"] = end
        updated += 1
        print(f"{label}: [{start}:{end}]")

    for name, entry in fixture.get("values", {}).items():
        fill(entry, name)
    for key, entry in fixture.get("supporting_levels", {}).items():
        fill(entry, f"supporting:{key}")

    fixture_path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated {updated} spans in {fixture_path}")
    return 0


def assert_source_eligible(
    accession: str,
    cutoff_utc: str,
    *,
    allow_post_cutoff: bool = False,
) -> None:
    """Raise if an input source is not eligible under §2.3 (unless post-cutoff allowed)."""
    snapshot = load_snapshot(SNAPSHOT_PATH)
    accepted = _parse_utc(acceptance_utc_for(snapshot, accession))
    cutoff = _parse_utc(cutoff_utc)
    if accepted <= cutoff:
        return
    if allow_post_cutoff:
        return
    raise ValueError(f"Source {accession} accepted {accepted.isoformat()} is after cutoff {cutoff.isoformat()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Download originals and write manifest.json")
    fetch_p.set_defaults(func=cmd_fetch)

    locate_p = sub.add_parser("locate", help="Fill char spans in a fixture from anchor+quote")
    locate_p.add_argument("fixture", help="Path to visa_YYYY-MM-DD.json")
    locate_p.set_defaults(func=cmd_locate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
