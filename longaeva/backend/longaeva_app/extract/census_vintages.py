"""Vintage table for archived Census MARTS advance releases (LON-15 / DR-04).

Each row is one cell from one advance PDF: a selected series, a measure, and the
period that cell describes. ``supersedes_release_id`` points at the previous
release that printed the same cell. A NAICS-code change on that series is a
definition break, not a revision, so the link is left empty.

``as_of`` returns the newest print of each cell whose release was published at
or before the cutoff. Later revisions are never visible at an earlier cutoff.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from longaeva_app.collect.census_sources import (
    CACHE_DIR,
    CENSUS_DIR,
    census_archive_entries,
    load_calendar,
    resolve_pdf,
    sha256_bytes,
)
from longaeva_app.collect.edgar_index import PACKAGE_ROOT
from longaeva_app.extract.census_marts import (
    ObservationRow,
    ReleaseMeta,
    extract_page_texts,
    find_table_page,
    naics_era_from_rows,
    parse_release_meta,
    parse_table1_rows,
    parse_table2_rows,
    sa_advance_total,
)

SELECTED_SERIES = frozenset(
    {
        "retail_food_services_total",
        "retail_total",
        "total_ex_motor",
        "total_ex_gas",
        "total_ex_motor_gas",
        "gafo",
        "naics_441",
        "naics_447",
        "naics_452",
        "naics_452_dept",
        "naics_454",
        "naics_722",
    }
)
PERCENT_MEASURES = frozenset({"mom_pct", "yoy_pct", "qoq_pct", "yoy_3m_pct"})

VINTAGES_PATH = CENSUS_DIR / "vintages.csv.gz"
PARSE_STATUS_PATH = CENSUS_DIR / "parse_status.csv"

VINTAGE_COLUMNS = [
    "release_id",
    "release_number",
    "publication_ts",
    "reference_month",
    "integrity_flag",
    "naics_era",
    "supersedes_release_id",
    "table",
    "series_key",
    "naics_code",
    "kind_of_business",
    "measure",
    "basis",
    "period_start",
    "period_end",
    "base_period_start",
    "base_period_end",
    "estimate_status",
    "value",
    "value_flag",
    "unit",
    "geography",
]

PARSE_STATUS_COLUMNS = [
    "release_id",
    "reference_month",
    "publication_ts",
    "status",
    "row_count",
    "selected_row_count",
    "error",
    "integrity_flag",
    "hash_verified",
    "pdf_creation_date",
    "pdf_mod_date",
    "pdf_creation_vs_release",
    "pdf_mod_vs_release",
    "naics_era",
    "source",
]


@dataclass(frozen=True)
class VintageRow:
    """One selected cell from one advance release."""

    release_id: str
    release_number: str
    publication_ts: str
    reference_month: str
    integrity_flag: str
    naics_era: str
    supersedes_release_id: str
    table: str
    series_key: str
    naics_code: str
    kind_of_business: str
    measure: str
    basis: str
    period_start: str
    period_end: str
    base_period_start: str
    base_period_end: str
    estimate_status: str
    value: str
    value_flag: str
    unit: str
    geography: str


@dataclass(frozen=True)
class VintageBuild:
    """Summary of one vintage-table build."""

    parsed: int
    failed: int
    total: int
    hash_failures: int
    vintage_rows: int
    vintages_path: Path
    status_path: Path
    failures: list[dict[str, str]]

    @property
    def parse_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.parsed / self.total


def parse_cutoff(cutoff: datetime | str) -> datetime:
    """Parse a UTC cutoff. A date with no time is the start of that UTC day."""
    if isinstance(cutoff, datetime):
        if cutoff.tzinfo is None:
            return cutoff.replace(tzinfo=UTC)
        return cutoff.astimezone(UTC)
    text = cutoff.strip()
    if len(text) == 10:
        text = f"{text}T00:00:00Z"
    if text.endswith("Z"):
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _publication(row: VintageRow) -> datetime:
    return datetime.strptime(row.publication_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def cell_key(row: VintageRow) -> tuple[str, str, str, str, str, str, str]:
    """Identity of the economic quantity, independent of which release printed it."""
    return (
        row.series_key,
        row.measure,
        row.basis,
        row.period_start,
        row.period_end,
        row.base_period_start,
        row.base_period_end,
    )


def _selected(row: ObservationRow) -> bool:
    if row.series_key not in SELECTED_SERIES:
        return False
    if row.table == "1" and row.measure == "level":
        return True
    return row.table == "2" and row.measure in PERCENT_MEASURES


def _has_advance_total(rows: list[ObservationRow]) -> bool:
    return any(
        row.series_key == "retail_food_services_total"
        and row.measure == "level"
        and row.basis == "sa"
        and row.estimate_status == "advance"
        and row.value
        for row in rows
    )


def _level(rows: list[ObservationRow], status: str) -> float | None:
    for row in rows:
        if (
            row.table == "1"
            and row.series_key == "retail_food_services_total"
            and row.measure == "level"
            and row.basis == "sa"
            and row.estimate_status == status
            and row.value
        ):
            return float(row.value)
    return None


def _mom(rows: list[ObservationRow]) -> float | None:
    for row in rows:
        if (
            row.table == "2"
            and row.series_key == "retail_food_services_total"
            and row.measure == "mom_pct"
            and row.estimate_status == "advance"
            and row.value
        ):
            return float(row.value)
    return None


def assert_release_consistent(meta: ReleaseMeta, rows: list[ObservationRow]) -> None:
    """Reject a parse whose total disagrees with the headline or with Table 2."""
    if not _has_advance_total(rows):
        raise ValueError("seasonally adjusted advance total was not parsed")
    total = sa_advance_total(rows)
    if meta.headline_billions is not None and round(total / 1000, 1) != meta.headline_billions:
        raise ValueError(f"SA advance total {total:.0f} does not match headline {meta.headline_billions} billion")
    advance = _level(rows, "advance")
    preliminary = _level(rows, "preliminary")
    mom = _mom(rows)
    if advance is not None and preliminary is not None and preliminary != 0.0 and mom is not None:
        computed = 100.0 * (advance - preliminary) / preliminary
        if abs(computed - mom) >= 0.2:
            raise ValueError(
                f"Table 2 month change {mom} disagrees with Table 1 levels ({computed:.2f}) for the advance total"
            )


def _pdf_date_vs_release(publication_ts: str, pdf_date: str | None) -> str:
    """Compare a PDF timestamp with the printed release time. Evidence only."""
    if not pdf_date:
        return "missing"
    try:
        created = datetime.strptime(pdf_date[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        published = datetime.strptime(publication_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return "unparsed"
    if created > published + timedelta(days=2):
        return "after_release"
    return "at_or_before_release"


def _to_vintage(
    row: ObservationRow,
    *,
    integrity_flag: str,
    naics_era: str,
) -> VintageRow:
    return VintageRow(
        release_id=row.release_id,
        release_number=row.release_number,
        publication_ts=row.publication_ts,
        reference_month=row.reference_month,
        integrity_flag=integrity_flag,
        naics_era=naics_era,
        supersedes_release_id="",
        table=row.table,
        series_key=row.series_key,
        naics_code=row.naics_code,
        kind_of_business=row.kind_of_business,
        measure=row.measure,
        basis=row.basis,
        period_start=row.period_start,
        period_end=row.period_end,
        base_period_start=row.base_period_start,
        base_period_end=row.base_period_end,
        estimate_status=row.estimate_status,
        value=row.value,
        value_flag=row.value_flag,
        unit=row.unit,
        geography=row.geography,
    )


def link_supersedes(rows: list[VintageRow]) -> list[VintageRow]:
    """Point each print at the previous print of the same cell.

    A changed NAICS code on that series is a definition break: the link stays
    empty so level values are not chained across the era change.
    """
    groups: dict[tuple[str, str, str, str, str, str, str], list[VintageRow]] = {}
    for row in rows:
        groups.setdefault(cell_key(row), []).append(row)
    linked: list[VintageRow] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda item: (item.publication_ts, item.release_id))
        previous: VintageRow | None = None
        for item in ordered:
            supersedes = ""
            if previous is not None and not _definition_break(previous, item):
                supersedes = previous.release_id
            current = replace(item, supersedes_release_id=supersedes)
            linked.append(current)
            previous = current
    linked.sort(
        key=lambda item: (
            item.release_id,
            item.series_key,
            item.table,
            item.measure,
            item.basis,
            item.period_start,
            item.estimate_status,
        )
    )
    return linked


def _definition_break(previous: VintageRow, current: VintageRow) -> bool:
    if not previous.naics_code or not current.naics_code:
        return False
    return previous.naics_code != current.naics_code


def parse_release_tables(source: Path, *, release_id: str) -> tuple[ReleaseMeta, list[ObservationRow]]:
    """Parse page-1 metadata plus Tables 1 and 2. Same rows as ``parse_marts_pdf``."""
    texts, _meta = extract_page_texts(source)
    meta = parse_release_meta(source, release_id=release_id)
    t1_page = find_table_page(texts, "Table 1.")
    t2_page = find_table_page(texts, "Table 2.")
    rows = parse_table1_rows(texts[t1_page - 1], meta, page_number=t1_page)
    rows.extend(parse_table2_rows(texts[t2_page - 1], meta, page_number=t2_page))
    return meta, rows


def _fetch_failure(release_id: str) -> str:
    path = CACHE_DIR / "fetch_failures.json"
    if not path.is_file():
        return ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return ""
    for item in payload:
        if isinstance(item, dict) and item.get("release_id") == release_id:
            return str(item.get("error") or "fetch failed")
    return ""


def _blank_status(release_id: str, **overrides: str) -> dict[str, str]:
    row = {column: "" for column in PARSE_STATUS_COLUMNS}
    row["release_id"] = release_id
    row["status"] = "failed"
    row["row_count"] = "0"
    row["selected_row_count"] = "0"
    row["hash_verified"] = "false"
    row.update(overrides)
    return row


def _entry_by_release() -> dict[str, Any]:
    found: dict[str, Any] = {}
    for entry in census_archive_entries():
        period = entry.period
        if period is None or not period.release_id:
            continue
        found[str(period.release_id)] = entry
    return found


def build_vintage_files(
    *,
    vintages_path: Path = VINTAGES_PATH,
    status_path: Path = PARSE_STATUS_PATH,
) -> VintageBuild:
    """Parse every calendar release and write the vintage table plus parse status."""
    calendar = load_calendar()
    entries = _entry_by_release()
    status_rows: list[dict[str, str]] = []
    vintage_rows: list[VintageRow] = []
    hash_failures = 0

    for cal in calendar:
        release_id = cal["release_id"]
        entry = entries.get(release_id)
        expected = (
            str(entry.expected_sha256) if entry is not None and entry.expected_sha256 else cal.get("content_sha256", "")
        )
        integrity = ""
        if entry is not None and entry.integrity_flag:
            integrity = str(entry.integrity_flag)
        elif cal.get("integrity_flag"):
            integrity = cal["integrity_flag"]
        resolved = resolve_pdf(release_id)
        if resolved is None:
            fetch_error = _fetch_failure(release_id)
            status_rows.append(
                _blank_status(
                    release_id,
                    reference_month=cal.get("reference_month", ""),
                    publication_ts=cal.get("publication_ts", ""),
                    error=fetch_error or f"pdf not found in fixtures or {CACHE_DIR.relative_to(PACKAGE_ROOT)}",
                    integrity_flag=integrity,
                    source="missing",
                )
            )
            continue
        path, source_kind = resolved
        raw = path.read_bytes()
        digest = sha256_bytes(raw)
        if expected and digest != expected:
            hash_failures += 1
            status_rows.append(
                _blank_status(
                    release_id,
                    reference_month=cal.get("reference_month", ""),
                    publication_ts=cal.get("publication_ts", ""),
                    error=f"sha256 {digest} != manifest {expected}",
                    integrity_flag=integrity,
                    hash_verified="false",
                    source=source_kind,
                )
            )
            continue
        try:
            meta, parsed = parse_release_tables(path, release_id=release_id)
            assert_release_consistent(meta, parsed)
        except Exception as exc:  # noqa: BLE001 — one bad PDF must not drop the rest of the window
            status_rows.append(
                _blank_status(
                    release_id,
                    reference_month=cal.get("reference_month", ""),
                    publication_ts=cal.get("publication_ts", ""),
                    error=f"{type(exc).__name__}: {exc}"[:500],
                    integrity_flag=integrity,
                    hash_verified="true",
                    source=source_kind,
                )
            )
            continue
        era = naics_era_from_rows(parsed)
        selected = [_to_vintage(row, integrity_flag=integrity, naics_era=era) for row in parsed if _selected(row)]
        vintage_rows.extend(selected)
        status_rows.append(
            {
                "release_id": release_id,
                "reference_month": meta.reference_month,
                "publication_ts": meta.publication_ts,
                "status": "parsed",
                "row_count": str(len(parsed)),
                "selected_row_count": str(len(selected)),
                "error": "",
                "integrity_flag": integrity,
                "hash_verified": "true",
                "pdf_creation_date": meta.pdf_creation_date or "",
                "pdf_mod_date": meta.pdf_mod_date or "",
                "pdf_creation_vs_release": _pdf_date_vs_release(meta.publication_ts, meta.pdf_creation_date),
                "pdf_mod_vs_release": _pdf_date_vs_release(meta.publication_ts, meta.pdf_mod_date),
                "naics_era": era,
                "source": source_kind,
            }
        )

    vintage_rows = link_supersedes(vintage_rows)
    _write_vintages(vintages_path, vintage_rows)
    _write_status(status_path, status_rows)
    failures = [row for row in status_rows if row["status"] != "parsed"]
    parsed_count = sum(1 for row in status_rows if row["status"] == "parsed")
    return VintageBuild(
        parsed=parsed_count,
        failed=len(failures),
        total=len(status_rows),
        hash_failures=hash_failures,
        vintage_rows=len(vintage_rows),
        vintages_path=vintages_path,
        status_path=status_path,
        failures=failures,
    )


def _write_vintages(path: Path, rows: list[VintageRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=VINTAGE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(asdict(row))
    payload = buf.getvalue().encode("utf-8")
    with path.open("wb") as handle:
        with gzip.GzipFile(fileobj=handle, mode="wb", mtime=0, filename="") as gz:
            gz.write(payload)


def _write_status(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PARSE_STATUS_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in PARSE_STATUS_COLUMNS})


def load_vintages(path: Path = VINTAGES_PATH) -> list[VintageRow]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return [VintageRow(**row) for row in csv.DictReader(handle)]


def load_parse_status(path: Path = PARSE_STATUS_PATH) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _loaded(rows: list[VintageRow] | None) -> list[VintageRow]:
    return load_vintages() if rows is None else rows


def as_of(
    cutoff: datetime | str,
    rows: list[VintageRow] | None = None,
    *,
    series: str | None = None,
    measure: str | None = None,
    basis: str | None = None,
    period_start: str | None = None,
    allow_possibly_replaced: bool = True,
) -> list[VintageRow]:
    """Newest print of each cell published at or before ``cutoff``.

    When ``allow_possibly_replaced`` is false, releases flagged
    ``possibly_replaced`` are skipped and the newest ``ok`` print is used.
    """
    limit = parse_cutoff(cutoff)
    chosen: dict[tuple[str, str, str, str, str, str, str], VintageRow] = {}
    for row in _loaded(rows):
        if series is not None and row.series_key != series:
            continue
        if measure is not None and row.measure != measure:
            continue
        if basis is not None and row.basis != basis:
            continue
        if period_start is not None and row.period_start != period_start:
            continue
        if _publication(row) > limit:
            continue
        if not allow_possibly_replaced and row.integrity_flag != "ok":
            continue
        key = cell_key(row)
        current = chosen.get(key)
        if current is None or (row.publication_ts, row.release_id) > (current.publication_ts, current.release_id):
            chosen[key] = row
    return sorted(chosen.values(), key=lambda item: (item.series_key, item.period_start, item.measure, item.basis))


def first_print(
    series: str,
    basis: str,
    period_start: str,
    rows: list[VintageRow] | None = None,
    *,
    measure: str = "level",
) -> VintageRow | None:
    """Earliest advance print of one cell. Later revisions are not returned."""
    matched = [
        row
        for row in _loaded(rows)
        if row.series_key == series
        and row.basis == basis
        and row.period_start == period_start
        and row.measure == measure
        and row.estimate_status == "advance"
        and row.value
    ]
    if not matched:
        return None
    return min(matched, key=lambda item: (item.publication_ts, item.release_id))


def revision_history(
    series: str,
    basis: str,
    period_start: str,
    rows: list[VintageRow] | None = None,
    *,
    measure: str = "level",
) -> list[VintageRow]:
    """Every print of one cell, oldest publication first."""
    matched = [
        row
        for row in _loaded(rows)
        if row.series_key == series
        and row.basis == basis
        and row.period_start == period_start
        and row.measure == measure
    ]
    return sorted(matched, key=lambda item: (item.publication_ts, item.release_id))
