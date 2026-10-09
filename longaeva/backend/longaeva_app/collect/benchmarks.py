"""Numeric benchmark inputs, kept exclusively in volatile memory.

The benchmark data review probe remains metadata-only. These readers deliberately have no cache
or writer; callers may serialize only explicit aggregate report fields.
"""

from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import xlrd

from longaeva_app.collect.benchmark_sources import (
    ProbeClient,
    _shiller_date_to_month,
    load_manifest,
    sha256_bytes,
)


def number(raw: Any, *, positive: bool = False) -> float | None:
    if str(raw).strip() in {"", ".", "-99.99", "-999"}:
        return None
    value = float(raw)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError("non-finite or non-positive benchmark value")
    return value


def read_fred(body: bytes) -> dict[date, float | None]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    if not reader.fieldnames or "SP500" not in reader.fieldnames:
        raise ValueError("FRED CSV missing SP500")
    result: dict[date, float | None] = {}
    for row in reader:
        day = date.fromisoformat(row.get("observation_date") or row.get("DATE") or "")
        if day in result:
            raise ValueError("duplicate FRED date")
        result[day] = number(row["SP500"], positive=True)
    if not any(value is not None for value in result.values()):
        raise ValueError("FRED has no prices")
    return result


def read_french(body: bytes) -> dict[date, float | None]:
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError("expected one Ken French CSV")
        lines = archive.read(names[0]).decode("utf-8-sig").splitlines()
    header = next((i for i, line in enumerate(lines) if "Mkt-RF" in line and "RF" in line.split(",")), None)
    if header is None:
        # Header cells can have leading spaces.
        header = next(
            (i for i, line in enumerate(lines) if {"Mkt-RF", "RF"} <= set(c.strip() for c in line.split(","))), None
        )
    if header is None:
        raise ValueError("Ken French header missing Mkt-RF / RF")
    columns = [c.strip() for c in lines[header].split(",")]
    result: dict[date, float | None] = {}
    for cells in csv.reader(lines[header + 1 :]):
        if not cells or not re.fullmatch(r"\d{8}", cells[0].strip()):
            if result:
                break
            continue
        day = datetime.strptime(cells[0].strip(), "%Y%m%d").date()
        if day in result:
            raise ValueError("duplicate Ken French date")
        market, risk_free = (number(cells[columns.index(key)].strip()) for key in ("Mkt-RF", "RF"))
        value = None if market is None or risk_free is None else (market + risk_free) / 100
        if value is not None and value <= -1:
            raise ValueError("invalid Ken French gross return")
        result[day] = value
    if not result:
        raise ValueError("Ken French has no dated rows")
    return result


@dataclass
class ShillerData:
    dividends: dict[str, float] = field(default_factory=dict)
    cpi: dict[str, float] = field(default_factory=dict)
    real_total_return: dict[str, float] = field(default_factory=dict)
    diagnostic_basis: str | None = None


def read_shiller(body: bytes) -> ShillerData:
    book = xlrd.open_workbook(file_contents=body)
    sheet = book.sheet_by_name("Data")
    header = next(
        (
            r
            for r in range(min(20, sheet.nrows))
            if [str(sheet.cell_value(r, c)).strip() for c in range(3)] == ["Date", "P", "D"]
        ),
        None,
    )
    if header is None:
        raise ValueError("Shiller Date/P/D header missing")
    columns = [str(sheet.cell_value(header, c)).strip() for c in range(sheet.ncols)]
    cpi_col = columns.index("CPI") if "CPI" in columns else None
    # Recognize the complete stacked heading, not the ambiguous word 'Price'.
    stacked = [
        " ".join(str(sheet.cell_value(r, c)).strip() for r in range(max(0, header - 3), header + 1)).strip()
        for c in range(sheet.ncols)
    ]
    tr_col = next((c for c, label in enumerate(stacked) if " ".join(label.split()) == "Real Total Return Price"), None)
    result = ShillerData(
        diagnostic_basis="monthly_average_real_total_return" if tr_col is not None and cpi_col is not None else None
    )
    seen: set[str] = set()
    for r in range(header + 1, sheet.nrows):
        month = _shiller_date_to_month(sheet.cell_value(r, 0))
        if month is None:
            continue
        if month in seen:
            raise ValueError("duplicate Shiller month")
        seen.add(month)
        dividend = number(sheet.cell_value(r, 2))
        if dividend is not None:
            if dividend < 0:
                raise ValueError("negative Shiller dividend")
            result.dividends[month] = dividend
        for col, target in ((cpi_col, result.cpi), (tr_col, result.real_total_return)):
            if col is not None:
                value = number(sheet.cell_value(r, col), positive=True)
                if value is not None:
                    target[month] = value
    if not result.dividends:
        raise ValueError("Shiller has no dividends")
    return result


@dataclass
class BenchmarkInputs:
    fred: dict[date, float | None] = field(default_factory=dict)
    french: dict[date, float | None] = field(default_factory=dict)
    shiller: ShillerData = field(default_factory=ShillerData)
    sources: list[dict[str, Any]] = field(default_factory=list)

    def sessions(self) -> list[date]:
        # FRED includes holiday placeholders. French dates identify actual
        # sessions even when a factor is missing; union exposes one-source gaps.
        return sorted({d for d, value in self.fred.items() if value is not None} | set(self.french))


Fetch = Callable[[str], tuple[bytes, dict[str, str]]]


def fetch_inputs(manifest: dict[str, Any] | None = None, *, fetch: Fetch | None = None) -> BenchmarkInputs:
    manifest = load_manifest() if manifest is None else manifest
    fetch = fetch or ProbeClient("Longaeva benchmark research (aggregate output only)").get
    result = BenchmarkInputs()
    for source_id in ("fred_sp500", "shiller_ie_data", "ken_french_daily"):
        config = manifest["sources"][source_id]
        meta: dict[str, Any] = {
            "source_id": source_id,
            "url": config["url"],
            "terms_url": config["terms_url"],
            "retrieved_at": datetime.now(UTC).isoformat(),
            "status": "unavailable",
        }
        try:
            body, headers = fetch(config["url"])
            meta.update(sha256=sha256_bytes(body), size_bytes=len(body), last_modified=headers.get("last-modified"))
            if source_id == "fred_sp500":
                result.fred = read_fred(body)
                dates = sorted(d.isoformat() for d in result.fred)
            elif source_id == "ken_french_daily":
                result.french = read_french(body)
                dates = sorted(d.isoformat() for d in result.french)
            else:
                result.shiller = read_shiller(body)
                dates = sorted(result.shiller.dividends)
            meta.update(status="ok", row_count=len(dates), first_date=dates[0], last_date=dates[-1])
        except Exception as exc:
            # Do not serialize exception text: HTTP errors may contain response
            # bodies. A bounded category is enough to diagnose this source.
            meta["reason"] = f"Download or parse failed ({type(exc).__name__}); source unavailable."
        result.sources.append(meta)
    return result
