"""Second-wave disclosure family gate.

CLI:

  snapshot  — live EDGAR submissions for all candidates → filing_index.json
  timing    — offline: candidate × Visa-origin age table → timing.csv
  scan      — live: finalist Ex. 99.x metric/guidance probe → release_scan.csv
  fetch     — download retained originals for selected companies → sources/
  locate    — fill char spans in an observation fixture
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html as htmlmod
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import yaml

from longaeva_app.collect.edgar_index import (
    PACKAGE_ROOT,
    SEC_MAX_RETRIES,
    EdgarClient,
    Filing,
    _load_env_user_agent,
    _parse_utc,
    accession_to_index_url,
    extract_accepted_from_index_html,
    fetch_company_filings,
    format_utc,
    is_earnings_8k,
    parse_acceptance_datetime,
)
from longaeva_app.collect.state_sources import locate_span
from longaeva_app.extract.booking_release import (
    guidance_covers_target,
)

EASTERN = ZoneInfo("America/New_York")

SECOND_WAVE_DIR = PACKAGE_ROOT / "data" / "fixtures" / "second_wave"
SNAPSHOT_PATH = SECOND_WAVE_DIR / "filing_index.json"
TIMING_PATH = SECOND_WAVE_DIR / "timing.csv"
SCAN_PATH = SECOND_WAVE_DIR / "release_scan.csv"
SOURCES_DIR = SECOND_WAVE_DIR / "sources"
MANIFEST_PATH = SOURCES_DIR / "manifest.json"
YAML_PATH = PACKAGE_ROOT / "data" / "manifest" / "second_wave.yaml"
ORIGINS_CSV_PATH = PACKAGE_ROOT / "data" / "fixtures" / "origins.csv"
OBSERVATIONS_DIR = PACKAGE_ROOT / "data" / "fixtures" / "observations"

TIMING_COLUMNS = [
    "candidate_id",
    "family",
    "origin_date",
    "fiscal_year",
    "fiscal_quarter",
    "target_fiscal_year",
    "target_fiscal_quarter",
    "cutoff_utc",
    "origin_status",
    "accession",
    "accepted_utc",
    "filed_date",
    "age_seconds",
    "age_days",
    "age_weeks",
    "same_day",
    "margin_seconds",
    "fallback_accession",
    "next_after_cutoff_accession",
    "next_after_cutoff_days",
    "eligible",
]

SCAN_COLUMNS = [
    "candidate_id",
    "family",
    "origin_date",
    "cutoff_utc",
    "accession",
    "accepted_utc",
    "age_days",
    "document",
    "exhibit",
    "content_sha256",
    "bytes",
    "metric_hits",
    "guidance_present",
    "guidance_quarter",
    "guidance_covers_target",
    "error",
]

_INDEX_JSON_SKIP = frozenset(
    {
        "index.htm",
        "index.html",
        "index-headers.html",
        "filing-index.htm",
        "filing-index.html",
    }
)
_EXHIBIT_HREF_RE = re.compile(
    r'href=["\']([^"\']+\.htm)["\'][^>]*>\s*(EX-99\.\d)',
    re.IGNORECASE,
)
# Modern EDGAR filing index: Document link in one cell, Type (EX-99.1) in the next.
_EXHIBIT_ROW_RE = re.compile(
    r'href=["\']([^"\']+\.htm)["\'][^<]*</a>\s*</td>\s*<td[^>]*>\s*(EX-99\.\d)',
    re.IGNORECASE,
)
_QUARTER_WORD = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest_yaml(path: Path = YAML_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise TypeError(f"Expected mapping in {path}")
    return data


def candidates_by_id(manifest: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    data = manifest if manifest is not None else load_manifest_yaml()
    return {str(c["id"]): cast(dict[str, Any], c) for c in data["candidates"]}


def selected_ids(manifest: dict[str, Any] | None = None) -> list[str]:
    data = manifest if manifest is not None else load_manifest_yaml()
    selected = data["selected"]
    return [str(selected["airline"]), str(selected["retailer"]), str(selected["processor"])]


def finalist_ids(manifest: dict[str, Any] | None = None) -> list[str]:
    data = manifest if manifest is not None else load_manifest_yaml()
    out: list[str] = []
    for cand in data["candidates"]:
        if cand["status"] in {"selected", "finalist_rejected"}:
            out.append(str(cand["id"]))
    return out


def load_visa_origins() -> list[dict[str, str]]:
    with ORIGINS_CSV_PATH.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if r["status"] in {"candidate", "prospective"}]


def get_bytes(client: EdgarClient, url: str) -> bytes:
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


def write_deterministic_gzip(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(filename="", mode="wb", fileobj=path.open("wb"), mtime=0, compresslevel=9) as gz:
        gz.write(data)


def read_gzip_bytes(path: Path) -> bytes:
    with gzip.open(path, "rb") as gz:
        return gz.read()


def archive_url(cik: int, accession: str, document: str) -> str:
    nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{document}"


def strip_html(raw: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", htmlmod.unescape(text))


def find_exhibits(index_html: str, index_json: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """Return [(document, exhibit_label), ...] preferring EX-99.*."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pattern in (_EXHIBIT_ROW_RE, _EXHIBIT_HREF_RE):
        for match in pattern.finditer(index_html):
            name = match.group(1).rsplit("/", 1)[-1]
            label = match.group(2).upper()
            if not name.lower().endswith(".htm"):
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append((name, label))
    if found:
        return found
    if index_json is None:
        return []
    items = index_json.get("directory", {}).get("item", [])
    names = [
        str(item["name"])
        for item in items
        if isinstance(item, dict)
        and str(item.get("name", "")).lower().endswith((".htm", ".html"))
        and str(item.get("name", "")).lower() not in _INDEX_JSON_SKIP
        and not str(item.get("name", "")).startswith("R")
        and "-index" not in str(item.get("name", "")).lower()
    ]
    preferred: list[tuple[str, str]] = []
    for n in names:
        lower = n.lower()
        if "ex991" in lower or "ex-99.1" in lower or "erex991" in lower or "dex991" in lower:
            preferred.append((n, "EX-99.1"))
        elif "ex992" in lower or "ex-99.2" in lower or "erex992" in lower or "dex992" in lower:
            preferred.append((n, "EX-99.2"))
        elif "earnings" in lower or "press" in lower or "investor" in lower:
            preferred.append((n, "EX-99.?"))
    return preferred[:3]


def load_snapshot(path: Path = SNAPSHOT_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return data


def earnings_for_candidate(snapshot: dict[str, Any], candidate_id: str) -> list[Filing]:
    rows = snapshot["candidates"][candidate_id]["filings"]
    filings = [Filing(**row) for row in rows]
    return sorted(
        [f for f in filings if is_earnings_8k(f) and f.form == "8-K"],
        key=lambda f: f.accepted_utc,
    )


def newest_eligible(filings: list[Filing], cutoff_utc: str) -> Filing | None:
    cutoff = _parse_utc(cutoff_utc)
    hit: Filing | None = None
    for filing in filings:
        if _parse_utc(filing.accepted_utc) <= cutoff:
            hit = filing
        else:
            break
    return hit


def next_after(filings: list[Filing], cutoff_utc: str) -> Filing | None:
    cutoff = _parse_utc(cutoff_utc)
    for filing in filings:
        if _parse_utc(filing.accepted_utc) > cutoff:
            return filing
    return None


def previous_accession(filings: list[Filing], accession: str) -> str:
    accessions = [f.accession for f in filings]
    try:
        idx = accessions.index(accession)
    except ValueError:
        return ""
    if idx <= 0:
        return ""
    return accessions[idx - 1]


def build_timing_rows(
    snapshot: dict[str, Any],
    origins: list[dict[str, str]] | None = None,
    manifest: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    origins = origins if origins is not None else load_visa_origins()
    by_id = candidates_by_id(manifest)
    rows: list[dict[str, str]] = []
    for cand_id, cand in by_id.items():
        filings = earnings_for_candidate(snapshot, cand_id)
        for origin in origins:
            cutoff = origin["cutoff_utc"]
            hit = newest_eligible(filings, cutoff)
            nxt = next_after(filings, cutoff)
            row: dict[str, str] = {k: "" for k in TIMING_COLUMNS}
            row["candidate_id"] = cand_id
            row["family"] = str(cand["family"])
            row["origin_date"] = cutoff[:10]
            row["fiscal_year"] = origin["fiscal_year"]
            row["fiscal_quarter"] = origin["fiscal_quarter"]
            row["target_fiscal_year"] = origin["target_fiscal_year"]
            row["target_fiscal_quarter"] = origin["target_fiscal_quarter"]
            row["cutoff_utc"] = cutoff
            row["origin_status"] = origin["status"]
            if hit is None:
                row["eligible"] = "false"
            else:
                accepted = _parse_utc(hit.accepted_utc)
                cut_dt = _parse_utc(cutoff)
                age_seconds = (cut_dt - accepted).total_seconds()
                same_day = accepted.astimezone(EASTERN).date() == cut_dt.astimezone(EASTERN).date()
                row["accession"] = hit.accession
                row["accepted_utc"] = hit.accepted_utc
                row["filed_date"] = hit.filed_date
                row["age_seconds"] = str(int(age_seconds))
                row["age_days"] = f"{age_seconds / 86400:.4f}"
                row["age_weeks"] = f"{age_seconds / 86400 / 7:.4f}"
                row["same_day"] = str(same_day).lower()
                row["margin_seconds"] = str(int(age_seconds)) if same_day else ""
                row["fallback_accession"] = previous_accession(filings, hit.accession) if same_day else ""
                row["eligible"] = "true"
            if nxt is not None:
                row["next_after_cutoff_accession"] = nxt.accession
                delta = (_parse_utc(nxt.accepted_utc) - _parse_utc(cutoff)).total_seconds() / 86400
                row["next_after_cutoff_days"] = f"{delta:.4f}"
            rows.append(row)
    return rows


def write_timing_csv(rows: list[dict[str, str]], path: Path = TIMING_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TIMING_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_timing(path: Path = TIMING_PATH) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_scan(path: Path = SCAN_PATH) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def detect_guidance_quarter(text: str) -> tuple[str, str]:
    """Return (present true/false, guidance_quarter like 2025Q4 or empty)."""
    # Prefer explicit "guidance for the Nth quarter of YYYY" style (Booking/United-like).
    explicit = re.search(
        r"(?:guidance|outlook)\s+for\s+the\s+(first|second|third|fourth)\s+quarter"
        r"(?:\s+and\s+full\s+year)?\s+(?:of\s+)?(\d{4})",
        text,
        re.IGNORECASE,
    )
    if explicit:
        q = _QUARTER_WORD[explicit.group(1).lower()]
        year = int(explicit.group(2))
        return "true", f"{year}Q{q}"
    # "Q4 outlook" / "December quarter" / "fourth quarter" near guidance.
    q_num = re.search(
        r"(?:Q([1-4])|(first|second|third|fourth))\s+(?:quarter\s+)?(?:guidance|outlook)",
        text,
        re.IGNORECASE,
    )
    year_m = re.search(
        r"(?:fiscal\s+)?(?:year\s+)?(20\d{2})",
        text[max(0, (q_num.start() if q_num else 0) - 80) : (q_num.end() if q_num else 0) + 80] if q_num else "",
    )
    if q_num:
        if q_num.group(1):
            q = int(q_num.group(1))
        else:
            q = _QUARTER_WORD[q_num.group(2).lower()]
        year = int(year_m.group(1)) if year_m else 0
        if year:
            return "true", f"{year}Q{q}"
        return "true", ""
    if re.search(r"\b(?:guidance|outlook)\b", text, re.IGNORECASE):
        return "true", ""
    return "false", ""


def cmd_snapshot(_args: argparse.Namespace) -> int:
    manifest = load_manifest_yaml()
    client = EdgarClient(_load_env_user_agent())
    retrieved = format_utc(datetime.now(tz=UTC))
    since = "2021-07-01"
    candidates_out: dict[str, Any] = {}
    for cand in manifest["candidates"]:
        cik = str(cand["cik"])
        cand_id = str(cand["id"])
        print(f"snapshot {cand_id} CIK {cik} …", flush=True)
        filings, urls = fetch_company_filings(client, cik)
        earnings = [f for f in filings if is_earnings_8k(f) and f.form in {"8-K", "8-K/A"} and f.filed_date >= since]
        candidates_out[cand_id] = {
            "id": cand_id,
            "name": cand["name"],
            "family": cand["family"],
            "cik": int(cik),
            "ticker": cand.get("ticker", ""),
            "status": cand["status"],
            "source_urls": urls,
            "filings": [asdict(f) for f in earnings],
            "earnings_count": len([f for f in earnings if f.form == "8-K" and not f.is_amendment]),
        }
        print(f"  earnings 8-K since {since}: {candidates_out[cand_id]['earnings_count']}")

    snapshot = {
        "schema_version": 1,
        "generated_for": "LON-8",
        "retrieved_at_utc": retrieved,
        "since": since,
        "user_agent_declared": True,
        "candidates": candidates_out,
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {SNAPSHOT_PATH.relative_to(PACKAGE_ROOT)} ({len(candidates_out)} candidates)")
    return 0


def cmd_timing(_args: argparse.Namespace) -> int:
    snapshot = load_snapshot()
    rows = build_timing_rows(snapshot)
    write_timing_csv(rows)
    eligible = sum(1 for r in rows if r["eligible"] == "true")
    print(f"wrote {TIMING_PATH.relative_to(PACKAGE_ROOT)} rows={len(rows)} eligible={eligible}")
    # Summary per candidate
    by_cand: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_cand.setdefault(row["candidate_id"], []).append(row)
    for cand_id, cand_rows in by_cand.items():
        ages = [float(r["age_days"]) for r in cand_rows if r["eligible"] == "true"]
        same = sum(1 for r in cand_rows if r["same_day"] == "true")
        miss = sum(1 for r in cand_rows if r["eligible"] != "true")
        if ages:
            ages_sorted = sorted(ages)
            med = ages_sorted[len(ages_sorted) // 2]
            print(
                f"  {cand_id:16s} covered={len(ages)}/{len(cand_rows)} "
                f"age_days min={min(ages):5.1f} med={med:5.1f} max={max(ages):5.1f} "
                f"same_day={same} missing={miss}"
            )
        else:
            print(f"  {cand_id:16s} covered=0/{len(cand_rows)}")
    return 0


def cmd_scan(_args: argparse.Namespace) -> int:
    manifest = load_manifest_yaml()
    timing = load_timing()
    client = EdgarClient(_load_env_user_agent())
    finalists = set(finalist_ids(manifest))
    by_id = candidates_by_id(manifest)
    # One scan row per finalist × origin (primary exhibit), plus secondary exhibit rows.
    rows: list[dict[str, str]] = []
    timing_by_key = {(r["candidate_id"], r["origin_date"]): r for r in timing}

    for cand_id in finalists:
        cand = by_id[cand_id]
        cik = int(cand["cik"])
        patterns = [re.compile(p) for p in cand.get("scan_patterns", [])]
        print(f"scan {cand_id} …", flush=True)
        for origin in load_visa_origins():
            origin_date = origin["cutoff_utc"][:10]
            trow = timing_by_key.get((cand_id, origin_date))
            if trow is None or trow["eligible"] != "true":
                row = {k: "" for k in SCAN_COLUMNS}
                row["candidate_id"] = cand_id
                row["family"] = str(cand["family"])
                row["origin_date"] = origin_date
                row["cutoff_utc"] = origin["cutoff_utc"]
                row["error"] = "no eligible release"
                rows.append(row)
                continue
            accession = trow["accession"]
            try:
                index_url = accession_to_index_url(cik, accession)
                index_html = client.get_text(index_url)
                nodash = accession.replace("-", "")
                index_json = json.loads(
                    client.get_text(f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/index.json")
                )
                exhibits = find_exhibits(index_html, index_json)
                if not exhibits:
                    raise RuntimeError("no EX-99 exhibits found")
                # Prefer EX-99.1 first, then EX-99.2
                exhibits_sorted = sorted(
                    exhibits,
                    key=lambda x: (0 if x[1].upper() == "EX-99.1" else 1 if x[1].upper() == "EX-99.2" else 2, x[0]),
                )
                # Scan up to two exhibits; record one primary row aggregating hits.
                combined_text = ""
                primary_doc = exhibits_sorted[0][0]
                primary_label = exhibits_sorted[0][1]
                primary_raw = b""
                for doc, label in exhibits_sorted[:2]:
                    raw = get_bytes(client, archive_url(cik, accession, doc))
                    if doc == primary_doc:
                        primary_raw = raw
                        primary_label = label
                    combined_text += " " + strip_html(raw.decode("utf-8", errors="replace"))
                hits = [p.pattern for p in patterns if p.search(combined_text)]
                guidance_present, guidance_quarter = detect_guidance_quarter(combined_text)
                covers = (
                    guidance_covers_target(
                        guidance_quarter,
                        int(origin["target_fiscal_year"]),
                        int(origin["target_fiscal_quarter"]),
                    )
                    if guidance_quarter
                    else ("false" if guidance_present == "false" else "unknown")
                )
                row = {k: "" for k in SCAN_COLUMNS}
                row["candidate_id"] = cand_id
                row["family"] = str(cand["family"])
                row["origin_date"] = origin_date
                row["cutoff_utc"] = origin["cutoff_utc"]
                row["accession"] = accession
                row["accepted_utc"] = trow["accepted_utc"]
                row["age_days"] = trow["age_days"]
                row["document"] = primary_doc
                row["exhibit"] = primary_label
                row["content_sha256"] = sha256_bytes(primary_raw) if primary_raw else ""
                row["bytes"] = str(len(primary_raw)) if primary_raw else ""
                row["metric_hits"] = ";".join(hits)
                row["guidance_present"] = guidance_present
                row["guidance_quarter"] = guidance_quarter
                row["guidance_covers_target"] = covers
                rows.append(row)
                print(
                    f"  {origin_date} {accession}: hits={len(hits)} "
                    f"guidance={guidance_present}/{guidance_quarter} covers={covers}"
                )
            except Exception as exc:  # noqa: BLE001 — scan must record failures
                row = {k: "" for k in SCAN_COLUMNS}
                row["candidate_id"] = cand_id
                row["family"] = str(cand["family"])
                row["origin_date"] = origin_date
                row["cutoff_utc"] = origin["cutoff_utc"]
                row["accession"] = accession
                row["accepted_utc"] = trow["accepted_utc"]
                row["age_days"] = trow["age_days"]
                row["error"] = str(exc)[:400]
                rows.append(row)
                print(f"  {origin_date} ERROR {exc}")

    SCAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SCAN_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SCAN_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    errors = sum(1 for r in rows if r["error"])
    print(f"wrote {SCAN_PATH.relative_to(PACKAGE_ROOT)} rows={len(rows)} errors={errors}")
    return 0 if errors == 0 else 1


def retained_specs(manifest: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build retained-source specs for selected companies at the two gate origins."""
    data = manifest if manifest is not None else load_manifest_yaml()
    timing = {(r["candidate_id"], r["origin_date"]): r for r in load_timing()}
    specs: list[dict[str, Any]] = []
    for cand_id in selected_ids(data):
        cand = candidates_by_id(data)[cand_id]
        cik = int(cand["cik"])
        for origin_date in data["retained_origins"]:
            trow = timing[(cand_id, origin_date)]
            if trow["eligible"] != "true":
                raise RuntimeError(f"{cand_id} ineligible at {origin_date}")
            specs.append(
                {
                    "candidate_id": cand_id,
                    "family": cand["family"],
                    "cik": cik,
                    "name": cand["name"],
                    "origin_date": origin_date,
                    "accession": trow["accession"],
                    "accepted_utc": trow["accepted_utc"],
                    "role": "input",
                    "exhibits": list(cand.get("exhibits") or ["EX-99.1"]),
                }
            )
    return specs


def cmd_fetch(_args: argparse.Namespace) -> int:
    manifest = load_manifest_yaml()
    client = EdgarClient(_load_env_user_agent())
    retrieval_ts = format_utc(datetime.now(tz=UTC))
    entries: list[dict[str, Any]] = []
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)

    for spec in retained_specs(manifest):
        cik = int(spec["cik"])
        accession = str(spec["accession"])
        print(f"fetch {spec['candidate_id']} {accession} …", flush=True)
        index_url = accession_to_index_url(cik, accession)
        index_html = client.get_text(index_url)
        page_accepted = extract_accepted_from_index_html(index_html)
        if not page_accepted:
            raise RuntimeError(f"Accepted timestamp missing on {index_url}")
        index_utc = format_utc(parse_acceptance_datetime(page_accepted))
        if index_utc != spec["accepted_utc"]:
            raise RuntimeError(f"Index page UTC {index_utc} != snapshot {spec['accepted_utc']} for {accession}")
        nodash = accession.replace("-", "")
        index_json = json.loads(client.get_text(f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/index.json"))
        exhibits = find_exhibits(index_html, index_json)
        wanted = {str(e).upper() for e in spec["exhibits"]}
        chosen = [(d, lab) for d, lab in exhibits if lab.upper() in wanted]
        if not chosen:
            # Fall back to first exhibit when labels are EX-99.?
            chosen = exhibits[: len(wanted)]
        if not chosen:
            raise RuntimeError(f"No exhibits for {accession}")
        for document, label in chosen:
            raw = get_bytes(client, archive_url(cik, accession, document))
            out = SOURCES_DIR / accession / f"{document}.gz"
            write_deterministic_gzip(out, raw)
            entries.append(
                {
                    "candidate_id": spec["candidate_id"],
                    "family": spec["family"],
                    "cik": cik,
                    "name": spec["name"],
                    "accession": accession,
                    "document": document,
                    "exhibit": label,
                    "form": f"8-K {label}",
                    "role": "input",
                    "origins": [spec["origin_date"]],
                    "url": archive_url(cik, accession, document),
                    "path": f"{accession}/{document}.gz",
                    "content_sha256": sha256_bytes(raw),
                    "raw_bytes": len(raw),
                    "acceptance_utc": spec["accepted_utc"],
                    "index_page_accepted_utc": index_utc,
                    "retrieval_ts": retrieval_ts,
                    "note": (f"{spec['name']} release eligible at Visa origin {spec['origin_date']}"),
                }
            )
            print(
                f"  wrote {out.relative_to(PACKAGE_ROOT)} "
                f"({len(raw)} bytes, sha256={entries[-1]['content_sha256'][:12]}…)"
            )

    payload = {
        "schema_version": 1,
        "generated_for": "LON-8",
        "retrieved_at": retrieval_ts,
        "snapshot_path": str(SNAPSHOT_PATH.relative_to(PACKAGE_ROOT)),
        "sources": entries,
    }
    MANIFEST_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST_PATH.relative_to(PACKAGE_ROOT)} ({len(entries)} sources)")
    return 0


def source_text(accession: str, document: str) -> str:
    path = SOURCES_DIR / accession / f"{document}.gz"
    if not path.exists():
        raise FileNotFoundError(f"Missing source original: {path}")
    return read_gzip_bytes(path).decode("utf-8", errors="replace")


def cmd_locate(args: argparse.Namespace) -> int:
    fixture_path = Path(args.fixture)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    sources = fixture.get("sources") or []
    if not sources and fixture.get("source"):
        sources = [fixture["source"]]
    by_id = {s["source_id"]: s for s in sources}
    # Also index by accession/document
    by_acc_doc = {(s["accession"], s["document"]): s for s in sources}
    updated = 0
    for entry in fixture.get("observations", []):
        span = entry.get("span")
        if not span:
            continue
        source_id = entry.get("source_id") or (sources[0]["source_id"] if sources else None)
        if source_id and source_id in by_id:
            src = by_id[source_id]
        else:
            # Fallback: first source
            src = sources[0]
        text = source_text(src["accession"], src["document"])
        # Prefer raw HTML for span location (Booking pattern uses HTML char offsets).
        start, end = locate_span(text, span["anchor"], span["quote"])
        span["char_start"] = start
        span["char_end"] = end
        entry["source_id"] = src["source_id"]
        updated += 1
        print(f"{entry.get('observation_id', '?')}: [{start}:{end}] via {src['source_id']}")
        _ = by_acc_doc  # kept for clarity / future multi-source routing
    fixture_path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated {updated} spans in {fixture_path}")
    return 0


def load_sources_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="Fetch EDGAR filings for all candidates")
    snap.set_defaults(func=cmd_snapshot)

    timing = sub.add_parser("timing", help="Build timing.csv from the snapshot")
    timing.set_defaults(func=cmd_timing)

    scan = sub.add_parser("scan", help="Scan finalist releases for metrics/guidance")
    scan.set_defaults(func=cmd_scan)

    fetch = sub.add_parser("fetch", help="Download retained originals for selected companies")
    fetch.set_defaults(func=cmd_fetch)

    locate = sub.add_parser("locate", help="Fill char spans in an observation fixture")
    locate.add_argument("fixture", help="Path to second-wave observation JSON")
    locate.set_defaults(func=cmd_locate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
