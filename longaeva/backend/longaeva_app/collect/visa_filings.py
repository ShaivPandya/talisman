"""Download Visa earnings-release and 10-Q/10-K originals for structured parser.

CLI:

  fetch  — live EDGAR requests; writes deterministic ``.htm.gz`` originals + manifest
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from longaeva_app.collect.edgar import document_url, resolve_document_name
from longaeva_app.collect.edgar_index import (
    ORIGINS_CSV_PATH,
    PACKAGE_ROOT,
    SNAPSHOT_PATH,
    VISA_CIK_INT,
    load_snapshot,
)
from longaeva_app.collect.http import PoliteClient
from longaeva_app.collect.state_sources import (
    SOURCES_DIR as STATES_SOURCES_DIR,
)
from longaeva_app.collect.state_sources import (
    absolute_gz_path as states_gz_path,
)
from longaeva_app.collect.state_sources import (
    read_gzip_bytes,
    sha256_bytes,
    write_deterministic_gzip,
)
from longaeva_app.config import get_settings

RELEASES_DIR = PACKAGE_ROOT / "data" / "fixtures" / "visa_releases"
SOURCES_DIR = RELEASES_DIR / "sources"
MANIFEST_PATH = SOURCES_DIR / "manifest.json"
VISA_YAML = PACKAGE_ROOT / "data" / "manifest" / "visa.yaml"
STATES_MANIFEST_PATH = STATES_SOURCES_DIR / "manifest.json"


@dataclass(frozen=True, slots=True)
class FilingTarget:
    accession: str
    document: str | None
    exhibit: str | None
    form: str
    role: str  # release | prior_10q
    fiscal_year: int | None
    fiscal_quarter: int | None
    origin_period: str | None


def _origins() -> list[dict[str, str]]:
    with ORIGINS_CSV_PATH.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _yaml_documents() -> dict[str, tuple[str, str]]:
    """Map accession -> (doc_type, document filename) from visa.yaml."""
    payload = yaml.safe_load(VISA_YAML.read_text(encoding="utf-8"))
    out: dict[str, tuple[str, str]] = {}
    for doc in payload.get("documents", []):
        accession = str(doc.get("accession") or "")
        document = doc.get("document")
        if accession and document:
            out[accession] = (str(doc.get("doc_type") or ""), str(document))
    return out


def _states_index() -> dict[tuple[str, str], dict[str, Any]]:
    if not STATES_MANIFEST_PATH.exists():
        return {}
    data = json.loads(STATES_MANIFEST_PATH.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in data.get("sources", []):
        out[(row["accession"], row["document"])] = row
    return out


def list_targets() -> list[FilingTarget]:
    yaml_docs = _yaml_documents()
    seen: set[tuple[str, str | None, str]] = set()
    out: list[FilingTarget] = []
    for row in _origins():
        fy = int(row["fiscal_year"])
        fq = int(row["fiscal_quarter"])
        period = f"FY{fy}Q{fq}"
        release = FilingTarget(
            accession=row["release_accession"],
            document=None,
            exhibit="EX-99.1",
            form="8-K Ex. 99.1",
            role="release",
            fiscal_year=fy,
            fiscal_quarter=fq,
            origin_period=period,
        )
        key_r = (release.accession, release.document, release.role)
        if key_r not in seen:
            seen.add(key_r)
            out.append(release)
        prior_acc = row["prior_10q_accession"]
        yaml_hit = yaml_docs.get(prior_acc)
        prior = FilingTarget(
            accession=prior_acc,
            document=yaml_hit[1] if yaml_hit else None,
            exhibit=None,
            form=row["prior_10q_form"],
            role="prior_10q",
            fiscal_year=fy,
            fiscal_quarter=fq,
            origin_period=period,
        )
        key_p = (prior.accession, prior.document, prior.role)
        if key_p not in seen:
            seen.add(key_p)
            out.append(prior)
    return out


def unique_fetch_keys(targets: list[FilingTarget] | None = None) -> list[FilingTarget]:
    """Deduplicate by accession (one primary document per accession)."""
    items = targets if targets is not None else list_targets()
    seen: set[str] = set()
    out: list[FilingTarget] = []
    for target in items:
        if target.accession in seen:
            continue
        seen.add(target.accession)
        out.append(target)
    return out


def relative_gz_path(accession: str, document: str) -> str:
    return f"{accession}/{document}.gz"


def local_gz_path(accession: str, document: str) -> Path:
    return SOURCES_DIR / accession / f"{document}.gz"


def locate_original(accession: str, document: str) -> Path:
    """Return the gzip path, preferring the structured parser store then starting-state reconstruction originals."""
    local = local_gz_path(accession, document)
    if local.exists():
        return local
    reused = states_gz_path(accession, document)
    if reused.exists():
        return reused
    raise FileNotFoundError(f"Missing original: {accession}/{document}")


def source_bytes(accession: str, document: str) -> bytes:
    return read_gzip_bytes(locate_original(accession, document))


def source_text(accession: str, document: str) -> str:
    return source_bytes(accession, document).decode("utf-8", errors="replace")


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return data


def manifest_entry(accession: str, document: str, *, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    data = manifest if manifest is not None else load_manifest()
    for row in data.get("sources", []):
        if row.get("accession") == accession and row.get("document") == document:
            return row  # type: ignore[no-any-return]
    raise KeyError(f"{accession}/{document} not in {MANIFEST_PATH}")


def verify_source_hash(accession: str, document: str, *, expected: str | None = None) -> bytes:
    raw = source_bytes(accession, document)
    digest = sha256_bytes(raw)
    if expected is not None and digest != expected:
        raise ValueError(f"SHA-256 mismatch for {accession}/{document}")
    return raw


def acceptance_utc_for(snapshot: dict[str, Any], accession: str) -> str:
    for row in snapshot["visa_filings"]:
        if row["accession"] == accession:
            return str(row["accepted_utc"])
    raise KeyError(f"Accession {accession} not in LON-1 snapshot")


def _resolve_document(client: PoliteClient, target: FilingTarget) -> str:
    if target.document:
        return target.document
    return resolve_document_name(
        client,
        cik=VISA_CIK_INT,
        accession=target.accession,
        document=target.document,
        exhibit=target.exhibit,
    )


def cmd_fetch(_args: argparse.Namespace) -> int:
    snapshot = load_snapshot(SNAPSHOT_PATH)
    settings = get_settings()
    client = PoliteClient(user_agent=settings.sec_user_agent)
    retrieval_ts = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    states = _states_index()
    entries: list[dict[str, Any]] = []
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)

    try:
        for target in unique_fetch_keys():
            document = _resolve_document(client, target)
            url = document_url(VISA_CIK_INT, target.accession, document)
            reused = states.get((target.accession, document))
            reused_path = states_gz_path(target.accession, document)
            if reused is not None and reused_path.exists():
                raw = read_gzip_bytes(reused_path)
                digest = sha256_bytes(raw)
                store = "states"
                print(f"reuse {target.accession}/{document} ({len(raw)} bytes)", flush=True)
            else:
                dest = local_gz_path(target.accession, document)
                if dest.exists():
                    raw = read_gzip_bytes(dest)
                    digest = sha256_bytes(raw)
                    store = "visa_releases"
                    print(f"cached {target.accession}/{document}", flush=True)
                else:
                    print(f"fetch {target.accession}/{document} …", flush=True)
                    result = client.get(url)
                    raw = result.content
                    write_deterministic_gzip(dest, raw)
                    digest = sha256_bytes(raw)
                    store = "visa_releases"
                    print(f"  wrote {dest.relative_to(PACKAGE_ROOT)} ({len(raw)} bytes)")
            path = (
                f"data/fixtures/states/sources/{relative_gz_path(target.accession, document)}"
                if store == "states"
                else f"data/fixtures/visa_releases/sources/{relative_gz_path(target.accession, document)}"
            )
            entries.append(
                {
                    "accession": target.accession,
                    "document": document,
                    "form": target.form,
                    "role": target.role,
                    "origin_period": target.origin_period,
                    "url": url,
                    "path": path,
                    "store": store,
                    "content_sha256": digest,
                    "raw_bytes": len(raw),
                    "acceptance_utc": acceptance_utc_for(snapshot, target.accession),
                    "retrieval_ts": reused["retrieval_ts"] if reused else retrieval_ts,
                }
            )
    finally:
        client.close()

    manifest = {
        "schema_version": 1,
        "generated_for": "LON-14",
        "retrieved_at": retrieval_ts,
        "snapshot_path": str(SNAPSHOT_PATH.relative_to(PACKAGE_ROOT)),
        "sources": entries,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST_PATH.relative_to(PACKAGE_ROOT)} ({len(entries)} sources)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch_p = sub.add_parser("fetch", help="Download originals and write manifest.json")
    fetch_p.set_defaults(func=cmd_fetch)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
