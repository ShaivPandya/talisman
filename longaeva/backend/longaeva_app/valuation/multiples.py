"""Trailing P/E band from Visa's SEC repurchase prices and EPS (LON-25).

The price is the quarterly "Average Purchase Price per Share" on the Total row of
the Issuer Purchases of Equity Securities table (10-Q Item 2, 10-K Item 5). That
is a buyback average, not a market close. Earnings are the trailing four quarters
of diluted EPS excluding special items from the earnings releases.

A quarter enters the band at a cutoff only when the price filing and all four EPS
releases were accepted at or before that cutoff.
"""

from __future__ import annotations

import csv
import html as html_lib
import io
import re
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from longaeva_app.collect.visa_filings import load_manifest, source_text
from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.definitions import VISA_FISCAL_CALENDAR
from longaeva_app.extract.html_offsets import Cell, Row, Table, parse_html

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = PACKAGE_ROOT / "data" / "fixtures" / "valuation" / "visa_pe_history.csv"
OBSERVATIONS_PATH = PACKAGE_ROOT / "data" / "fixtures" / "visa_releases" / "observations.csv"

WINDOW_START = FiscalPeriod(2023, 1)
WINDOW_END = FiscalPeriod(2026, 2)
MIN_BAND_QUARTERS = 4
EPS_FIELD = "eps_diluted_ex_special_items"
PRICE_ANCHOR = "Average Purchase Price per Share"

SOURCE_BASIS = (
    "Trailing P/E from Visa's average open-market repurchase price "
    "(SEC 10-Q/10-K Issuer Purchases of Equity Securities, quarterly Average Purchase Price per Share) "
    "divided by trailing four-quarter diluted EPS excluding special items (SEC earnings releases). "
    "This is a quarterly buyback average, not a market close. "
    "The trailing multiple is applied to forward earnings."
)
METHOD_LABEL = (
    "low, mid, and high are the minimum, median, and maximum of quarterly trailing P/E ratios "
    "whose price filing and all four EPS releases were accepted at or before the cutoff. "
    "The median of an even count is the average of the two central ratios."
)
OVERRIDE_SOURCE_LABEL = (
    "Request override multiple range. Not derived from the historical SEC repurchase-price window. "
    "The trailing multiple is applied to forward earnings."
)
OVERRIDE_METHOD_LABEL = "Caller-supplied low, mid, and high multiples. Not a historical distribution."

_ENDED_RE = re.compile(
    r"(?:three months|quarter) ended\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(r"^\d{2,4}\.\d{2}$")
_PERIOD_RE = re.compile(r"^FY(\d+)Q([1-4])$")

_BASE_COLUMNS: tuple[str, ...] = (
    "period_label",
    "period_end",
    "avg_purchase_price",
    "price_source_id",
    "price_form",
    "price_acceptance_utc",
    "price_url",
    "price_quote",
    "price_char_start",
    "price_char_end",
    "price_anchor",
    "ttm_eps",
    "trailing_pe",
)


def history_columns() -> tuple[str, ...]:
    extra: list[str] = []
    for index in range(4):
        extra.extend(
            (
                f"eps_{index}_period",
                f"eps_{index}_value",
                f"eps_{index}_source_id",
                f"eps_{index}_acceptance_utc",
            )
        )
    return _BASE_COLUMNS + tuple(extra)


class PeHistoryError(ValueError):
    """Raised when the repurchase-price history cannot be built."""


@dataclass(frozen=True, slots=True)
class EpsComponent:
    period_label: str
    value: float
    value_text: str
    source_id: str
    acceptance_utc: datetime


@dataclass(frozen=True, slots=True)
class PeQuarter:
    period_label: str
    period_end: date
    avg_purchase_price: float
    price_source_id: str
    price_form: str
    price_acceptance_utc: datetime
    price_url: str
    price_quote: str
    price_char_start: int
    price_char_end: int
    ttm_eps: float
    ttm_eps_text: str
    trailing_pe: float
    trailing_pe_text: str
    eps_components: tuple[EpsComponent, EpsComponent, EpsComponent, EpsComponent]

    def eligible(self, cutoff_ts: datetime) -> bool:
        cutoff = as_utc(cutoff_ts)
        if self.price_acceptance_utc > cutoff:
            return False
        return all(component.acceptance_utc <= cutoff for component in self.eps_components)


@dataclass(frozen=True, slots=True)
class MultipleBand:
    low: float
    mid: float
    high: float
    n_quarters: int
    window_start: str
    window_end: str
    source: str
    source_label: str
    method_label: str
    periods: tuple[str, ...] = ()


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_utc(value: datetime) -> str:
    return as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def period_sort_key(label: str) -> tuple[int, int]:
    match = _PERIOD_RE.match(label)
    if match is None:
        raise PeHistoryError(f"Unparseable period label: {label}")
    return int(match.group(1)), int(match.group(2))


def previous_period(period: FiscalPeriod, steps: int = 1) -> FiscalPeriod:
    year, quarter = period.year, period.quarter
    for _ in range(steps):
        if quarter == 1:
            year -= 1
            quarter = 4
        else:
            quarter -= 1
    return FiscalPeriod(year, quarter)


def window_periods() -> tuple[FiscalPeriod, ...]:
    out: list[FiscalPeriod] = []
    period = WINDOW_START
    while True:
        out.append(period)
        if period.year == WINDOW_END.year and period.quarter == WINDOW_END.quarter:
            return tuple(out)
        period = period.next()


def _manifest_index() -> dict[str, dict[str, Any]]:
    data = load_manifest()
    sources = data.get("sources")
    if not isinstance(sources, list):
        raise PeHistoryError("Visa releases manifest has no sources list")
    out: dict[str, dict[str, Any]] = {}
    for row in sources:
        if not isinstance(row, dict):
            continue
        accession = row.get("accession")
        document = row.get("document")
        if isinstance(accession, str) and isinstance(document, str):
            out[f"{accession}/{document}"] = row
    return out


def _require_str(row: dict[str, Any], key: str, source_id: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise PeHistoryError(f"{source_id} is missing {key}")
    return value


def _load_eps(manifest: dict[str, dict[str, Any]]) -> dict[str, EpsComponent]:
    if not OBSERVATIONS_PATH.is_file():
        raise PeHistoryError(f"Missing observations: {OBSERVATIONS_PATH}")
    found: dict[str, EpsComponent] = {}
    with OBSERVATIONS_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("field") != EPS_FIELD:
                continue
            label = row.get("period_label") or ""
            source_id = row.get("source_id") or ""
            value_text = row.get("value") or ""
            filing = manifest.get(source_id)
            if filing is None:
                raise PeHistoryError(f"EPS source {source_id} for {label} is not in the releases manifest")
            if label in found:
                raise PeHistoryError(f"Duplicate {EPS_FIELD} for {label}")
            found[label] = EpsComponent(
                period_label=label,
                value=float(value_text),
                value_text=value_text,
                source_id=source_id,
                acceptance_utc=parse_utc(_require_str(filing, "acceptance_utc", source_id)),
            )
    return found


def _period_end_before(table: Table, html: str) -> date:
    pre = html[max(0, table.start - 1500) : table.start]
    pre = re.sub(r"(?is)<[^>]+>", " ", pre)
    pre = html_lib.unescape(pre).replace("\xa0", " ")
    pre = re.sub(r"\s+", " ", pre)
    matches = list(_ENDED_RE.finditer(pre))
    if not matches:
        raise PeHistoryError("Issuer Purchases table has no 'three months ended' or 'quarter ended' date")
    month_name, day_text, year_text = matches[-1].groups()
    try:
        month = datetime.strptime(month_name, "%B").month
    except ValueError as exc:
        raise PeHistoryError(f"Unparseable month {month_name!r}") from exc
    return date(int(year_text), month, int(day_text))


def _is_total(row: Row) -> bool:
    for cell in row.cells:
        text = cell.text.replace("\xa0", " ").strip().lower()
        if text:
            return text == "total"
    return False


def _price_cell(row: Row) -> Cell:
    for cell in row.cells:
        text = cell.text.replace("\xa0", " ").replace(",", "").strip()
        if _PRICE_RE.match(text):
            return cell
    raise PeHistoryError("Total row has no average purchase price")


def _quote_span(cell: Cell, html: str, quote: str) -> tuple[int, int]:
    found = cell.find_quote(quote)
    if found is not None and html[found[0] : found[1]] == quote:
        return found
    if cell.raw_start is None or cell.raw_end is None:
        raise PeHistoryError(f"Price cell for {quote} has no raw offsets")
    window = html[cell.raw_start : cell.raw_end]
    index = window.find(quote)
    if index < 0:
        raise PeHistoryError(f"Price quote {quote} not in raw cell")
    start = cell.raw_start + index
    return start, start + len(quote)


def _issuer_table(html: str) -> Table:
    layout = parse_html(html)
    for table in layout.tables:
        if "average purchase price" not in table.joined_text().lower():
            continue
        if any(_is_total(row) for row in table.rows):
            return table
    raise PeHistoryError("No Issuer Purchases table with an Average Purchase Price Total row")


def _extract_price(html: str) -> tuple[FiscalPeriod, date, str, int, int]:
    table = _issuer_table(html)
    period_end = _period_end_before(table, html)
    period = VISA_FISCAL_CALENDAR.period_containing(period_end)
    total = next(row for row in table.rows if _is_total(row))
    cell = _price_cell(total)
    quote = cell.text.replace("\xa0", " ").replace(",", "").strip()
    start, end = _quote_span(cell, html, quote)
    if html[start:end] != quote:
        raise PeHistoryError(f"Span for {quote} does not round-trip")
    return period, period_end, quote, start, end


def build_history() -> tuple[PeQuarter, ...]:
    """Parse bundled 10-Q/10-K originals and join trailing EPS. One row per quarter."""
    manifest = _manifest_index()
    eps = _load_eps(manifest)
    parsed: dict[str, PeQuarter] = {}
    for source_id, row in manifest.items():
        form = row.get("form")
        if form not in {"10-Q", "10-K"}:
            continue
        accession = _require_str(row, "accession", source_id)
        document = _require_str(row, "document", source_id)
        html = source_text(accession, document)
        try:
            period, period_end, quote, char_start, char_end = _extract_price(html)
        except PeHistoryError:
            continue
        if period_sort_key(period.label()) < period_sort_key(WINDOW_START.label()):
            continue
        if period_sort_key(period.label()) > period_sort_key(WINDOW_END.label()):
            continue
        components: list[EpsComponent] = []
        for step in range(4):
            label = previous_period(period, step).label()
            component = eps.get(label)
            if component is None:
                raise PeHistoryError(f"{period.label()} is missing trailing EPS for {label}")
            if Decimal(component.value_text) <= 0:
                raise PeHistoryError(f"Non-positive EPS for {label}")
            components.append(component)
        ttm = sum((Decimal(item.value_text) for item in components), Decimal(0))
        price = Decimal(quote)
        pe = (price / ttm).quantize(Decimal("0.000001"))
        quarter = PeQuarter(
            period_label=period.label(),
            period_end=period_end,
            avg_purchase_price=float(price),
            price_source_id=source_id,
            price_form=str(form),
            price_acceptance_utc=parse_utc(_require_str(row, "acceptance_utc", source_id)),
            price_url=_require_str(row, "url", source_id),
            price_quote=quote,
            price_char_start=char_start,
            price_char_end=char_end,
            ttm_eps=float(ttm),
            ttm_eps_text=format(ttm, "f"),
            trailing_pe=float(pe),
            trailing_pe_text=format(pe, "f"),
            eps_components=(components[0], components[1], components[2], components[3]),
        )
        previous = parsed.get(period.label())
        if previous is not None and previous.price_source_id != quarter.price_source_id:
            raise PeHistoryError(f"Two price filings for {period.label()}: {previous.price_source_id} and {source_id}")
        parsed[period.label()] = quarter

    missing = [period.label() for period in window_periods() if period.label() not in parsed]
    if missing:
        raise PeHistoryError(f"Missing repurchase-price quarters: {', '.join(missing)}")
    return tuple(parsed[period.label()] for period in window_periods())


def history_csv_text(rows: tuple[PeQuarter, ...] | list[PeQuarter]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=history_columns(), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        payload: dict[str, str] = {
            "period_label": row.period_label,
            "period_end": row.period_end.isoformat(),
            "avg_purchase_price": row.price_quote,
            "price_source_id": row.price_source_id,
            "price_form": row.price_form,
            "price_acceptance_utc": format_utc(row.price_acceptance_utc),
            "price_url": row.price_url,
            "price_quote": row.price_quote,
            "price_char_start": str(row.price_char_start),
            "price_char_end": str(row.price_char_end),
            "price_anchor": PRICE_ANCHOR,
            "ttm_eps": row.ttm_eps_text,
            "trailing_pe": row.trailing_pe_text,
        }
        for index, component in enumerate(row.eps_components):
            payload[f"eps_{index}_period"] = component.period_label
            payload[f"eps_{index}_value"] = component.value_text
            payload[f"eps_{index}_source_id"] = component.source_id
            payload[f"eps_{index}_acceptance_utc"] = format_utc(component.acceptance_utc)
        writer.writerow(payload)
    return buffer.getvalue()


def write_history(rows: tuple[PeQuarter, ...] | list[PeQuarter], path: Path = FIXTURE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(history_csv_text(rows), encoding="utf-8")
    return path


def load_history(path: Path = FIXTURE_PATH) -> tuple[PeQuarter, ...]:
    if not path.is_file():
        raise PeHistoryError(f"Missing P/E history fixture: {path}")
    rows: list[PeQuarter] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            components: list[EpsComponent] = []
            for index in range(4):
                components.append(
                    EpsComponent(
                        period_label=raw[f"eps_{index}_period"],
                        value=float(raw[f"eps_{index}_value"]),
                        value_text=raw[f"eps_{index}_value"],
                        source_id=raw[f"eps_{index}_source_id"],
                        acceptance_utc=parse_utc(raw[f"eps_{index}_acceptance_utc"]),
                    )
                )
            rows.append(
                PeQuarter(
                    period_label=raw["period_label"],
                    period_end=date.fromisoformat(raw["period_end"]),
                    avg_purchase_price=float(raw["avg_purchase_price"]),
                    price_source_id=raw["price_source_id"],
                    price_form=raw["price_form"],
                    price_acceptance_utc=parse_utc(raw["price_acceptance_utc"]),
                    price_url=raw["price_url"],
                    price_quote=raw["price_quote"],
                    price_char_start=int(raw["price_char_start"]),
                    price_char_end=int(raw["price_char_end"]),
                    ttm_eps=float(raw["ttm_eps"]),
                    ttm_eps_text=raw["ttm_eps"],
                    trailing_pe=float(raw["trailing_pe"]),
                    trailing_pe_text=raw["trailing_pe"],
                    eps_components=(components[0], components[1], components[2], components[3]),
                )
            )
    return tuple(rows)


def _window_phrase(rows: tuple[PeQuarter, ...] | list[PeQuarter]) -> str:
    return f"{rows[0].period_label}–{rows[-1].period_label} ({len(rows)} quarters)"


def pe_band(
    cutoff_ts: datetime,
    *,
    rows: tuple[PeQuarter, ...] | list[PeQuarter] | None = None,
) -> MultipleBand | None:
    """Min/median/max trailing P/E among quarters published at or before ``cutoff_ts``."""
    history = tuple(rows) if rows is not None else load_history()
    kept = tuple(
        row for row in sorted(history, key=lambda item: period_sort_key(item.period_label)) if row.eligible(cutoff_ts)
    )
    if len(kept) < MIN_BAND_QUARTERS:
        return None
    ratios = [row.trailing_pe for row in kept]
    return MultipleBand(
        low=min(ratios),
        mid=float(statistics.median(ratios)),
        high=max(ratios),
        n_quarters=len(kept),
        window_start=kept[0].period_label,
        window_end=kept[-1].period_label,
        source="sec_trailing_pe",
        source_label=f"{SOURCE_BASIS} Window: {_window_phrase(kept)}.",
        method_label=METHOD_LABEL,
        periods=tuple(row.period_label for row in kept),
    )


def override_band(low: float, mid: float, high: float) -> MultipleBand:
    """Caller-supplied range. Validity is checked by the bridge, not here."""
    return MultipleBand(
        low=low,
        mid=mid,
        high=high,
        n_quarters=0,
        window_start="",
        window_end="",
        source="request_override",
        source_label=OVERRIDE_SOURCE_LABEL,
        method_label=OVERRIDE_METHOD_LABEL,
        periods=(),
    )


def eligible_rows(
    cutoff_ts: datetime,
    *,
    rows: tuple[PeQuarter, ...] | list[PeQuarter] | None = None,
) -> tuple[PeQuarter, ...]:
    history = tuple(rows) if rows is not None else load_history()
    kept = [row for row in history if row.eligible(cutoff_ts)]
    return tuple(sorted(kept, key=lambda item: period_sort_key(item.period_label)))


__all__ = [
    "EPS_FIELD",
    "FIXTURE_PATH",
    "METHOD_LABEL",
    "MIN_BAND_QUARTERS",
    "OVERRIDE_METHOD_LABEL",
    "OVERRIDE_SOURCE_LABEL",
    "PRICE_ANCHOR",
    "SOURCE_BASIS",
    "WINDOW_END",
    "WINDOW_START",
    "EpsComponent",
    "MultipleBand",
    "PeHistoryError",
    "PeQuarter",
    "as_utc",
    "build_history",
    "eligible_rows",
    "format_utc",
    "history_columns",
    "history_csv_text",
    "load_history",
    "override_band",
    "parse_utc",
    "pe_band",
    "period_sort_key",
    "previous_period",
    "window_periods",
    "write_history",
]
