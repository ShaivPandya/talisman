"""Curated source manifests for the source collection collector."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from longaeva_app.collect.edgar_index import (
    BOOKING_CIK,
    PACKAGE_ROOT,
    VISA_CIK,
    format_utc,
    load_snapshot,
    parse_acceptance_datetime,
)

MANIFEST_DIR = PACKAGE_ROOT / "data" / "manifest"
FIXTURES_DIR = PACKAGE_ROOT / "data" / "fixtures"

Availability = Literal["available", "unavailable_for_automation"]
PublicationTsSource = Literal[
    "edgar_acceptance",
    "census_release_line",
    "http_last_modified",
    "manifest",
]

SKIP_MANIFESTS = frozenset({"benchmarks.yaml"})
ADAPTER_MANIFESTS = frozenset({"visa_ir.yaml", "second_wave.yaml"})
GENERATED_MANIFESTS = ("visa.yaml", "booking.yaml", "census.yaml")

SEC_LICENSE = "SEC EDGAR U.S. government work / public domain; redistribution allowed (bundled)."
CENSUS_LICENSE = (
    "U.S. Census Bureau public domain. The parsed vintage table is bundled; "
    "original advance PDFs are fetched and hash-checked, with seven test PDFs bundled."
)
IR_LICENSE = (
    "Visa IR CDN: personal non-commercial download only; fetch-by-script, never bundled. "
    "Transcripts may carry FactSet CallStreet copyright — short fair-use quotes only."
)


class Period(BaseModel):
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    period_start: date | None = None
    period_end: date | None = None
    reference_month: str | None = None
    release_id: str | None = None
    reported_quarter: str | None = None


class DocumentEntry(BaseModel):
    """One curated document the collector may fetch."""

    key: str
    provider: str
    company: str
    doc_type: str
    url: str | None = None
    cik: str | None = None
    accession: str | None = None
    document: str | None = None
    exhibit: str | None = None
    publication_ts: datetime | None = None
    publication_ts_source: PublicationTsSource | None = None
    period: Period | None = None
    expected_sha256: str | None = None
    license_note: str | None = None
    availability: Availability = "available"
    unavailable_reason: str | None = None
    supersedes: str | None = None
    integrity_flag: str | None = None
    cutoff_utc: datetime | None = None
    call_date: date | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("publication_ts", "cutoff_utc", mode="before")
    @classmethod
    def _parse_ts(cls, value: object) -> object:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                from datetime import UTC

                return value.replace(tzinfo=UTC)
            return value
        if isinstance(value, str):
            return parse_acceptance_datetime(value)
        return value

    @field_validator("call_date", mode="before")
    @classmethod
    def _parse_date(cls, value: object) -> object:
        if value is None or value == "":
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def _require_locator(self) -> DocumentEntry:
        if self.availability != "available":
            return self
        has_url = bool(self.url)
        has_edgar = bool(self.cik and self.accession and (self.document or self.exhibit))
        if not has_url and not has_edgar:
            raise ValueError(f"{self.key}: available entries need url or cik+accession+(document|exhibit)")
        return self

    def to_manifest_dict(self) -> dict[str, Any]:
        """Serialize for deterministic YAML output (ISO timestamps, omit nulls)."""
        payload = self.model_dump(mode="python", exclude_none=True)
        for ts_key in ("publication_ts", "cutoff_utc"):
            if ts_key in payload and isinstance(payload[ts_key], datetime):
                payload[ts_key] = format_utc(payload[ts_key])
        if "call_date" in payload and isinstance(payload["call_date"], date):
            payload["call_date"] = payload["call_date"].isoformat()
        if "period" in payload and isinstance(payload["period"], dict):
            period = payload["period"]
            for dk in ("period_start", "period_end"):
                if dk in period and isinstance(period[dk], date):
                    period[dk] = period[dk].isoformat()
            payload["period"] = {k: v for k, v in period.items() if v is not None}
            if not payload["period"]:
                del payload["period"]
        if not payload.get("attributes"):
            payload.pop("attributes", None)
        return payload


class ManifestFile(BaseModel):
    schema_version: int = 1
    name: str
    documents: list[DocumentEntry]


def load_manifests(
    manifest_dir: Path | None = None,
    *,
    names: list[str] | None = None,
) -> list[DocumentEntry]:
    """Load curated + generated manifests and adapter sources; keys must be unique."""
    root = manifest_dir or MANIFEST_DIR
    entries: list[DocumentEntry] = []
    seen: set[str] = set()

    paths = _manifest_paths(root, names=names)
    for path in paths:
        if path.name in SKIP_MANIFESTS:
            continue
        if path.name in ADAPTER_MANIFESTS:
            batch = _adapt_manifest(path)
        else:
            batch = _load_document_manifest(path)
        for entry in batch:
            if entry.key in seen:
                raise ValueError(f"duplicate manifest key: {entry.key}")
            seen.add(entry.key)
            entries.append(entry)
    return entries


def build_manifests(
    *,
    manifest_dir: Path | None = None,
    fixtures_dir: Path | None = None,
    write: bool = True,
) -> dict[str, list[DocumentEntry]]:
    """Generate visa/booking/census YAML manifests from committed snapshots."""
    out_dir = manifest_dir or MANIFEST_DIR
    fix = fixtures_dir or FIXTURES_DIR
    built = {
        "visa.yaml": _build_visa_manifest(fix),
        "booking.yaml": _build_booking_manifest(fix),
        "census.yaml": _build_census_manifest(fix),
    }
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, docs in built.items():
            _write_manifest_yaml(out_dir / name, name.removesuffix(".yaml"), docs)
    return built


def _manifest_paths(root: Path, *, names: list[str] | None) -> list[Path]:
    if names:
        paths = []
        for name in names:
            candidate = root / name if not name.endswith(".yaml") else root / name
            if not candidate.name.endswith(".yaml"):
                candidate = root / f"{name}.yaml"
            if not candidate.is_file():
                raise FileNotFoundError(candidate)
            paths.append(candidate)
        return paths
    return sorted(root.glob("*.yaml"))


def _load_document_manifest(path: Path) -> list[DocumentEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    docs = raw.get("documents") or []
    return [DocumentEntry.model_validate(item) for item in docs]


def _adapt_manifest(path: Path) -> list[DocumentEntry]:
    if path.name == "visa_ir.yaml":
        return _adapt_visa_ir(path)
    if path.name == "second_wave.yaml":
        return _adapt_second_wave(path)
    return []


def _adapt_visa_ir(path: Path) -> list[DocumentEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    origins_by_fq = _origins_by_fy_fq()
    entries: list[DocumentEntry] = [
        DocumentEntry(
            key="visa_ir:quarterly_html",
            provider="visa_ir",
            company="visa",
            doc_type="ir_quarterly_html",
            url="https://investor.visa.com/news/quarterly-earnings/",
            availability="unavailable_for_automation",
            unavailable_reason="Cloudflare JavaScript challenge (DR-09); HTTP 403; not bypassed",
            license_note=IR_LICENSE,
            attributes={"http_status": 403},
        )
    ]
    for origin in raw.get("origins") or []:
        fy = int(origin["fiscal_year"])
        fq = int(origin["fiscal_quarter"])
        origin_row = origins_by_fq.get((fy, fq))
        cutoff = parse_acceptance_datetime(origin_row["cutoff_utc"]) if origin_row else None
        deck = origin.get("deck") or {}
        if deck.get("url"):
            entries.append(
                DocumentEntry(
                    key=f"visa_ir:deck:FY{fy}Q{fq}",
                    provider="visa_ir",
                    company="visa",
                    doc_type="ir_deck",
                    url=deck["url"],
                    publication_ts_source="http_last_modified",
                    period=Period(fiscal_year=fy, fiscal_quarter=fq),
                    license_note=IR_LICENSE,
                    cutoff_utc=cutoff,
                    attributes={"model_input": False, "discovery": deck.get("discovery")},
                )
            )
        transcript = origin.get("transcript") or {}
        if transcript.get("url"):
            call_date = date.fromisoformat(transcript["call_date"]) if transcript.get("call_date") else None
            entries.append(
                DocumentEntry(
                    key=f"visa_ir:transcript:FY{fy}Q{fq}",
                    provider="visa_ir",
                    company="visa",
                    doc_type="ir_transcript",
                    url=transcript["url"],
                    publication_ts_source="http_last_modified",
                    period=Period(fiscal_year=fy, fiscal_quarter=fq),
                    license_note=IR_LICENSE,
                    cutoff_utc=cutoff,
                    call_date=call_date,
                    attributes={"model_input": False, "discovery": transcript.get("discovery")},
                )
            )
    return entries


def _adapt_second_wave(path: Path) -> list[DocumentEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    retained = set(raw.get("retained_origins") or [])
    selected_ids = {
        (raw.get("selected") or {}).get("airline"),
        (raw.get("selected") or {}).get("retailer"),
        (raw.get("selected") or {}).get("processor"),
    }
    selected_ids.discard(None)
    sources_manifest = json.loads(
        (FIXTURES_DIR / "second_wave" / "sources" / "manifest.json").read_text(encoding="utf-8")
    )
    entries: list[DocumentEntry] = []
    for src in sources_manifest.get("sources") or []:
        origins = set(src.get("origins") or [])
        if retained and not (origins & retained):
            continue
        if src.get("candidate_id") not in selected_ids:
            continue
        company = str(src["candidate_id"])
        exhibit = str(src.get("exhibit") or "EX-99.1")
        fy_label = sorted(origins)[0] if origins else src["accession"]
        key = f"second_wave:{company}:{exhibit}:{src['accession']}"
        entries.append(
            DocumentEntry(
                key=key,
                provider="sec_edgar",
                company=company,
                doc_type=f"earnings_release_{exhibit.lower().replace('-', '_')}",
                cik=str(src["cik"]).zfill(10),
                accession=src["accession"],
                document=src.get("document"),
                exhibit=exhibit,
                publication_ts=parse_acceptance_datetime(src["acceptance_utc"]),
                publication_ts_source="edgar_acceptance",
                expected_sha256=src.get("content_sha256"),
                license_note=SEC_LICENSE,
                url=src.get("url"),
                attributes={
                    "family": src.get("family"),
                    "origins": list(origins),
                    "origin_label": fy_label,
                    "model_input": False,
                },
            )
        )
    return entries


def _build_visa_manifest(fix: Path) -> list[DocumentEntry]:
    snapshot = load_snapshot(fix / "edgar" / "filing_index.json")
    filings = {f["accession"]: f for f in snapshot.get("visa_filings") or []}
    hash_by_accession_doc = _states_hashes(fix)
    entries: list[DocumentEntry] = []
    seen_keys: set[str] = set()
    tenq_seen: set[str] = set()

    for row in _iter_origins(fix):
        fy = int(row["fiscal_year"])
        fq = int(row["fiscal_quarter"])
        if (fy, fq) < (2017, 1) or (fy, fq) > (2026, 3):
            continue
        accession = row["release_accession"]
        if not accession:
            continue
        key = f"visa:release:FY{fy}Q{fq}"
        expected = None
        document = None
        for (acc, doc), digest in hash_by_accession_doc.items():
            if acc == accession and "earningsrelease" in doc.lower().replace("-", ""):
                expected = digest
                document = doc
                break
        # Also match states manifest docs that don't include "earningsrelease" in the stem.
        if expected is None:
            for (acc, doc), digest in hash_by_accession_doc.items():
                if acc == accession:
                    expected = digest
                    document = doc
                    break
        entry = DocumentEntry(
            key=key,
            provider="sec_edgar",
            company="visa",
            doc_type="earnings_release",
            cik=VISA_CIK,
            accession=accession,
            document=document,
            exhibit="EX-99.1",
            publication_ts=parse_acceptance_datetime(row["cutoff_utc"]),
            publication_ts_source="edgar_acceptance",
            period=Period(
                fiscal_year=fy,
                fiscal_quarter=fq,
                period_end=date.fromisoformat(row["period_end"]) if row.get("period_end") else None,
            ),
            expected_sha256=expected,
            license_note=SEC_LICENSE,
            attributes={"origin_status": row.get("status"), "origin_window": row.get("origin_window")},
        )
        if key not in seen_keys:
            seen_keys.add(key)
            entries.append(entry)

        for field, label in (
            ("prior_10q_accession", "prior_10q"),
            ("same_q_10q_accession", "same_q_10q"),
        ):
            acc = (row.get(field) or "").strip()
            if not acc or acc in tenq_seen:
                continue
            filing = filings.get(acc)
            if not filing:
                continue
            form = filing.get("form") or row.get(field.replace("_accession", "_form")) or "10-Q"
            primary = filing.get("primary_document") or ""
            tenq_seen.add(acc)
            expected = hash_by_accession_doc.get((acc, primary))
            tkey = f"visa:{form.lower().replace('/', '_')}:{acc}"
            entries.append(
                DocumentEntry(
                    key=tkey,
                    provider="sec_edgar",
                    company="visa",
                    doc_type=form.lower().replace("/", "_"),
                    cik=VISA_CIK,
                    accession=acc,
                    document=primary or None,
                    publication_ts=parse_acceptance_datetime(filing["accepted_utc"]),
                    publication_ts_source="edgar_acceptance",
                    period=Period(
                        period_end=date.fromisoformat(filing["period_of_report"])
                        if filing.get("period_of_report")
                        else None
                    ),
                    expected_sha256=expected,
                    license_note=SEC_LICENSE,
                    attributes={"role": label},
                )
            )
    return entries


def _build_booking_manifest(fix: Path) -> list[DocumentEntry]:
    path = fix / "booking" / "release_calendar.csv"
    entries: list[DocumentEntry] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("error"):
                continue
            accession = row["accession"]
            document = row["document"]
            key = f"booking:release:{accession}"
            entries.append(
                DocumentEntry(
                    key=key,
                    provider="sec_edgar",
                    company="booking",
                    doc_type="earnings_release",
                    cik=BOOKING_CIK,
                    accession=accession,
                    document=document,
                    exhibit="EX-99.1",
                    publication_ts=parse_acceptance_datetime(row["acceptance_utc"]),
                    publication_ts_source="edgar_acceptance",
                    period=Period(reported_quarter=row.get("reported_quarter") or None),
                    expected_sha256=row.get("content_sha256") or None,
                    license_note=SEC_LICENSE,
                    attributes={
                        "filed_date": row.get("filed_date"),
                        "guidance_table": row.get("guidance_table"),
                    },
                )
            )
    return entries


def _build_census_manifest(fix: Path) -> list[DocumentEntry]:
    path = fix / "census" / "release_calendar.csv"
    entries: list[DocumentEntry] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("error"):
                continue
            release_id = row["release_id"]
            entries.append(
                DocumentEntry(
                    key=f"census:marts:{release_id}",
                    provider="census",
                    company="census",
                    doc_type="marts_advance",
                    url=row["url"],
                    publication_ts=parse_acceptance_datetime(row["publication_ts"]),
                    publication_ts_source="census_release_line",
                    period=Period(
                        reference_month=row.get("reference_month"),
                        release_id=release_id,
                    ),
                    expected_sha256=row.get("content_sha256") or None,
                    license_note=CENSUS_LICENSE,
                    integrity_flag=row.get("integrity_flag") or None,
                    attributes={
                        "release_number": row.get("release_number"),
                        "http_last_modified": row.get("http_last_modified"),
                    },
                )
            )
    return entries


def _write_manifest_yaml(path: Path, name: str, documents: list[DocumentEntry]) -> None:
    payload = {
        "schema_version": 1,
        "name": name,
        "generated_by": "longaeva_app.collect.manifest.build_manifests",
        "plan_id": "DRAFT-14",
        "linear_id": "LON-13",
        "documents": [doc.to_manifest_dict() for doc in documents],
    }
    text = (
        "# Generated by `python -m longaeva_app.cli build-manifests` · LON-13\n"
        "# Do not edit by hand; regenerate from committed fixtures.\n"
        + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, default_flow_style=False)
    )
    path.write_text(text, encoding="utf-8")


def _iter_origins(fix: Path) -> list[dict[str, str]]:
    path = fix / "origins.csv"
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _origins_by_fy_fq() -> dict[tuple[int, int], dict[str, str]]:
    return {(int(r["fiscal_year"]), int(r["fiscal_quarter"])): r for r in _iter_origins(FIXTURES_DIR)}


def _states_hashes(fix: Path) -> dict[tuple[str, str], str]:
    path = fix / "states" / "sources" / "manifest.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], str] = {}
    for src in data.get("sources") or []:
        out[(src["accession"], src["document"])] = src["content_sha256"]
    return out
