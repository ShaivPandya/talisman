"""Visa earnings-release and 10-Q/10-K structured table parser (LON-14)."""

from __future__ import annotations

import csv
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from longaeva_app.api.schemas import ObservationCreate
from longaeva_app.collect.visa_filings import (
    RELEASES_DIR,
    load_manifest,
    source_text,
    verify_source_hash,
)
from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.definitions import (
    FIELDS,
    REPORTED_FIELDS,
    VISA_FISCAL_CALENDAR,
)
from longaeva_app.companies.visa.starting_state import parse_numeric_quote
from longaeva_app.extract.html_offsets import (
    Cell,
    DocumentLayout,
    Row,
    Table,
    map_joined_index,
    parse_html,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
EXTRACTOR_ID = "visa_tables"
EXTRACTOR_VERSION = "lon-14-v1"
SOURCE_UUID_NAMESPACE = uuid.UUID("a14e0c14-14a4-4c14-a14e-000000000014")

FIELD_BY_NAME = {f.name: f for f in (*FIELDS, *REPORTED_FIELDS)}
_PERIOD_RE = re.compile(r"^FY(20\d{2})Q([1-4])$")

FormatEra = Literal["table_2017", "image_text_layer", "table_modern"]
ParseStatus = Literal["parsed", "partial", "failed"]

MONEY_RE = re.compile(r"^\(?-?\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?$")
PCT_RE = re.compile(r"^\(?-?\d+(?:\.\d+)?\)?%?$")
MONTHS_ENDED_RE = re.compile(
    r"(Three|Six|Nine|Twelve)\s*Months?\s*Ended\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})",
    re.IGNORECASE,
)
MONTH_ENDED_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s*\d{4}",
    re.IGNORECASE,
)

ISS_LABELS: dict[str, str] = {
    "service revenue": "service_revenue",
    "service revenues": "service_revenue",
    "data processing revenue": "data_processing_revenue",
    "data processing revenues": "data_processing_revenue",
    "international transaction revenue": "international_transaction_revenue",
    "international transaction revenues": "international_transaction_revenue",
    "other revenue": "other_revenue",
    "other revenues": "other_revenue",
    "client incentives": "client_incentives",
    "net revenue": "net_revenue",
    "net revenues": "net_revenue",
    "net operating revenue": "net_revenue",
    "net operating revenues": "net_revenue",
    "total operating expenses": "operating_expenses_gaap",
    "non-operating income (expense)": "net_interest_other",
    "non-operating (expense) income": "net_interest_other",
    "non-operating income/(expense)": "net_interest_other",
    "non-operating (expense)/income": "net_interest_other",
    "non-operating expense": "net_interest_other",
    "non-operating income": "net_interest_other",
    "earnings per share": "eps_diluted_gaap",
    "operating income": "operating_profit_gaap",
}

KBD_LABELS: dict[str, tuple[str, str]] = {
    "payments volume": ("payments_volume_growth_constant", "payments_volume_growth_nominal"),
    "cross-border volume excluding intra-europe": (
        "cross_border_ex_intra_europe_growth_constant",
        "cross_border_ex_intra_europe_growth_nominal",
    ),
    "cross-border volume excluding transactions within europe": (
        "cross_border_ex_intra_europe_growth_constant",
        "cross_border_ex_intra_europe_growth_nominal",
    ),
    "cross-border volume total": (
        "cross_border_total_growth_constant",
        "cross_border_total_growth_nominal",
    ),
    "cross-border volume": (
        "cross_border_total_growth_constant",
        "cross_border_total_growth_nominal",
    ),
    "processed transactions": ("processed_transactions_growth", "processed_transactions_growth"),
}

NONGAP_OPEX_LABELS = frozenset({"total operating expenses"})
BRIDGE_SKIP = frozenset({"as reported", "non-gaap", "as adjusted", "adjusted"})


class Span(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor: str
    quote: str
    char_start: int
    char_end: int

    @model_validator(mode="after")
    def _order(self) -> Span:
        if self.char_end < self.char_start:
            raise ValueError("char_end must be >= char_start")
        if self.char_end - self.char_start != len(self.quote):
            raise ValueError("span length != quote length")
        return self


class ParsedObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    value: float
    unit: str
    basis: str
    period_label: str
    period_start: date
    period_end: date
    statement_type: Literal["measured", "derived"] = "measured"
    geography: str = "global"
    source_id: str
    span: Span
    location: Literal["primary", "cross_check"] = "primary"
    attributes: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


@dataclass
class IdentityCheck:
    name: str
    left: float
    right: float
    residual: float
    tolerance: float
    passed: bool


@dataclass
class ParseResult:
    accession: str
    document: str
    form: str
    era: FormatEra | str
    period_label: str | None
    observations: list[ParsedObservation] = field(default_factory=list)
    identities: list[IdentityCheck] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    status: ParseStatus = "failed"

    def primary_by_field(self) -> dict[str, ParsedObservation]:
        out: dict[str, ParsedObservation] = {}
        for obs in self.observations:
            if obs.location != "primary":
                continue
            if obs.field not in out:
                out[obs.field] = obs
        return out


def _period_key(label: str) -> tuple[int, int]:
    match = _PERIOD_RE.match(label)
    if not match:
        return (0, 0)
    return int(match.group(1)), int(match.group(2))


def period_in_range(label: str, first: str, last: str) -> bool:
    return _period_key(first) <= _period_key(label) <= _period_key(last)


def fiscal_dates(fy: int, fq: int) -> tuple[str, date, date]:
    period = FiscalPeriod(fy, fq)
    return period.label(), VISA_FISCAL_CALENDAR.period_start(period), VISA_FISCAL_CALENDAR.period_end(period)


def prev_fiscal(fy: int, fq: int) -> tuple[int, int]:
    if fq == 1:
        return fy - 1, 4
    return fy, fq - 1


def detect_format(layout: DocumentLayout, fiscal_year: int) -> FormatEra:
    if fiscal_year == 2017:
        return "table_2017"
    if layout.table_count >= 15:
        return "table_modern"
    return "image_text_layer"


def source_uuid_for(source_id: str) -> UUID:
    return uuid.uuid5(SOURCE_UUID_NAMESPACE, source_id)


def _norm_label(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = re.sub(r"\([0-9]+\)$", "", text).strip()
    return text


def _is_money_token(text: str) -> bool:
    cleaned = text.replace("\xa0", "").replace("$", "").strip()
    if cleaned in {"—", "-", "–", "nm", "n/m"}:
        return False
    if "%" in cleaned:
        return False
    return bool(MONEY_RE.match(cleaned))


def _is_pct_token(text: str) -> bool:
    t = text.replace("\xa0", "").strip()
    return "%" in t or t.endswith("ppt")


def _combine_cells(a: Cell, b: Cell) -> Cell:
    return Cell(runs=list(a.runs) + list(b.runs), is_header=a.is_header)


def merged_cells(row: Row) -> list[Cell]:
    cells = list(row.cells)
    out: list[Cell] = []
    i = 0
    while i < len(cells):
        text = cells[i].text.replace("\xa0", " ").strip()
        nxt = cells[i + 1].text.replace("\xa0", " ").strip() if i + 1 < len(cells) else ""
        if text.startswith("(") and ")" not in text and nxt.startswith(")"):
            out.append(_combine_cells(cells[i], cells[i + 1]))
            i += 2
            continue
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text) and nxt in {"%", "%)"}:
            out.append(_combine_cells(cells[i], cells[i + 1]))
            i += 2
            continue
        if text.startswith("(") and ")" not in text and "%" in nxt:
            out.append(_combine_cells(cells[i], cells[i + 1]))
            i += 2
            continue
        out.append(cells[i])
        i += 1
    return out


def _first_money_cell(cells: list[Cell], *, skip: int = 1) -> Cell | None:
    """Return the first money cell after the label (skip=1 skips the label)."""
    seen = 0
    for cell in cells:
        text = cell.text.replace("\xa0", " ").strip()
        if seen < skip:
            seen += 1
            continue
        if text in {"$", ""}:
            continue
        if _is_pct_token(text):
            continue
        if _is_money_token(text):
            return cell
    return None


def _pct_cells(cells: list[Cell], *, skip: int = 1) -> list[Cell]:
    out: list[Cell] = []
    seen = 0
    for cell in cells:
        if seen < skip:
            seen += 1
            continue
        text = cell.text.replace("\xa0", " ").strip()
        if text.endswith("%") and re.search(r"\d", text):
            out.append(cell)
    return out


def _quote_and_span(cell: Cell, html: str, label: str) -> tuple[str, int, int, str]:
    text = cell.text.replace("\xa0", " ").strip()
    # Prefer the numeric/paren form used in LON-3 fixtures.
    quote = text
    found = cell.find_quote(quote)
    if found is None and quote.endswith("%"):
        found = cell.find_quote(quote)
    if found is None:
        # Fall back to the raw range of the first run.
        start = cell.raw_start or 0
        quote = html[start : start + len(text)] if text else ""
        if quote != text and text:
            idx = html.find(text, start, (cell.raw_end or start) + 20)
            if idx >= 0:
                return text, idx, idx + len(text), label
        return text, start, start + len(quote), label
    start, end = found
    raw_quote = html[start:end]
    return raw_quote, start, end, label


def _obs(
    *,
    field_name: str,
    value: float,
    fy: int,
    fq: int,
    source_id: str,
    html: str,
    cell: Cell | None = None,
    quote: str | None = None,
    start: int | None = None,
    end: int | None = None,
    anchor: str = "",
    location: Literal["primary", "cross_check"] = "primary",
    statement_type: Literal["measured", "derived"] = "measured",
    geography: str = "global",
    period_label: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    attributes: dict[str, Any] | None = None,
    note: str = "",
    unit: str | None = None,
    basis: str | None = None,
) -> ParsedObservation:
    spec = FIELD_BY_NAME[field_name]
    if cell is not None and (quote is None or start is None):
        quote, start, end, _ = _quote_and_span(cell, html, anchor or field_name)
        anchor = anchor or spec.name
    assert quote is not None and start is not None and end is not None
    if not period_label:
        period_label, period_start, period_end = fiscal_dates(fy, fq)
    assert period_start is not None and period_end is not None
    return ParsedObservation(
        field=field_name,
        value=value,
        unit=unit or spec.unit,
        basis=basis or spec.basis,
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        statement_type=statement_type,
        geography=geography,
        source_id=source_id,
        span=Span(anchor=anchor or field_name, quote=quote, char_start=start, char_end=end),
        location=location,
        attributes=attributes or {},
        note=note,
    )


def _parse_cell_number(cell: Cell, unit: str, *, field_name: str = "") -> float:
    quote = cell.text.replace("\xa0", " ").strip()
    return convert_quote(quote, unit, field_name=field_name)


def convert_quote(quote: str, unit: str, *, field_name: str = "") -> float:
    parsed = parse_numeric_quote(quote, unit if unit != "usd_per_share" else "usd_millions")
    if field_name == "tax_rate" or unit == "ratio" and field_name == "tax_rate":
        return parsed / 100.0 if abs(parsed) > 1.5 else parsed
    if field_name == "tax_rate":
        return parsed / 100.0
    if field_name == "processed_transactions_count" and abs(parsed) < 500:
        return parsed * 1000.0
    if field_name == "diluted_shares" and abs(parsed) < 20:
        return parsed * 1000.0  # billions of shares in prose
    if field_name == "client_incentives":
        return abs(parsed)
    if "%" in quote and unit == "percent":
        return parsed
    return parsed


def convert_quote_tax(quote: str) -> float:
    parsed = parse_numeric_quote(quote, "percent")
    return parsed / 100.0


def source_id_of(accession: str, document: str) -> str:
    return f"{accession}/{document}"


def _iss_table(layout: DocumentLayout) -> Table | None:
    candidates: list[Table] = []
    for table in layout.tables:
        joined = table.joined_text()
        if "INCOME STATEMENT SUMMARY" in joined.upper():
            candidates.append(table)
            continue
        if "CONSOLIDATED STATEMENTS OF OPERATIONS" in joined.upper() and "Client incentives" in joined:
            candidates.append(table)
    for table in candidates:
        if _short_label_row(table, "service revenue"):
            return table
    for table in layout.tables:
        if _short_label_row(table, "service revenue") and _short_label_row(table, "client incentives"):
            return table
    return None


def _short_label_row(table: Table, needle: str) -> bool:
    for row in table.rows:
        cells = merged_cells(row)
        if not cells:
            continue
        label = _norm_label(cells[0].text)
        if needle in label and len(cells[0].text.strip()) < 80 and _first_money_cell(cells) is not None:
            return True
    return False


def _ops_table(layout: DocumentLayout) -> Table | None:
    for table in layout.tables:
        joined = table.joined_text().lower()
        if "diluted weighted-average" in joined and "class" in joined:
            return table
    return None


def _recon_tables(layout: DocumentLayout) -> list[Table]:
    out: list[Table] = []
    for table in layout.tables:
        joined = table.joined_text()
        if "As reported" in joined and ("Non-GAAP" in joined or "As adjusted" in joined):
            out.append(table)
    return out


def _parse_iss_from_table(
    table: Table,
    html: str,
    *,
    fy: int,
    fq: int,
    source_id: str,
    nongap: bool = False,
) -> list[ParsedObservation]:
    observations: list[ParsedObservation] = []
    in_nongap = nongap
    for row in table.rows:
        cells = merged_cells(row)
        if not cells:
            continue
        label = _norm_label(cells[0].text)
        if label.startswith("non-gaap"):
            in_nongap = True
            continue
        if label in {"gaap", "revenue", "revenues", "operating expenses", "operating revenues"}:
            continue
        if label.startswith("key business"):
            break
        mapped = ISS_LABELS.get(label)
        if mapped is None:
            continue
        if len(cells[0].text.strip()) > 80:
            continue
        cell = _first_money_cell(cells)
        if cell is None:
            continue
        field_name = mapped
        if in_nongap and mapped == "operating_expenses_gaap":
            field_name = "operating_expenses_ex_special_items"
        if in_nongap and mapped == "eps_diluted_gaap":
            field_name = "eps_diluted_ex_special_items"
        if in_nongap and mapped not in {
            "operating_expenses_ex_special_items",
            "eps_diluted_ex_special_items",
            "net_interest_other",
        }:
            # Non-GAAP net income etc. are not FIELDS; skip except EPS/opex.
            if field_name not in {"eps_diluted_ex_special_items", "operating_expenses_ex_special_items"}:
                continue
        spec = FIELD_BY_NAME[field_name]
        value = _parse_cell_number(cell, spec.unit, field_name=field_name)
        location: Literal["primary", "cross_check"] = "primary"
        if field_name == "tax_rate":
            location = "cross_check"
        observations.append(
            _obs(
                field_name=field_name,
                value=value,
                fy=fy,
                fq=fq,
                source_id=source_id,
                html=html,
                cell=cell,
                anchor=cells[0].text.strip()[:80],
                location=location,
            )
        )
    return observations


def _parse_kbd_from_table(
    table: Table,
    html: str,
    *,
    fy: int,
    fq: int,
    source_id: str,
) -> list[ParsedObservation]:
    observations: list[ParsedObservation] = []
    started = False
    period = f"FY{fy}Q{fq}"
    for row in table.rows:
        cells = merged_cells(row)
        if not cells:
            continue
        label = _norm_label(cells[0].text)
        if label.startswith("key business"):
            started = True
            continue
        if not started and "payments volume" not in label:
            continue
        started = True
        mapped = None
        for key, fields in KBD_LABELS.items():
            if label.startswith(key):
                mapped = fields
                break
        if mapped is None:
            continue
        pcts = _pct_cells(cells)
        if not pcts:
            continue
        const_field, nom_field = mapped
        const_cell = pcts[0]
        const_val = parse_numeric_quote(const_cell.text.strip(), "percent")
        if period_in_range(period, FIELD_BY_NAME[const_field].first_period, FIELD_BY_NAME[const_field].last_period):
            observations.append(
                _obs(
                    field_name=const_field,
                    value=const_val,
                    fy=fy,
                    fq=fq,
                    source_id=source_id,
                    html=html,
                    cell=const_cell,
                    anchor=cells[0].text.strip()[:80],
                )
            )
        if len(pcts) >= 2 and const_field != nom_field:
            nom_cell = pcts[1]
            if period_in_range(period, FIELD_BY_NAME[nom_field].first_period, FIELD_BY_NAME[nom_field].last_period):
                observations.append(
                    _obs(
                        field_name=nom_field,
                        value=parse_numeric_quote(nom_cell.text.strip(), "percent"),
                        fy=fy,
                        fq=fq,
                        source_id=source_id,
                        html=html,
                        cell=nom_cell,
                        anchor=cells[0].text.strip()[:80],
                    )
                )
        elif const_field == nom_field and len(pcts) >= 1:
            # processed transactions: same field, prefer first (constant=count)
            pass
    return observations


def _parse_shares(table: Table, html: str, *, fy: int, fq: int, source_id: str) -> list[ParsedObservation]:
    observations: list[ParsedObservation] = []
    saw_header = False
    for row in table.rows:
        cells = merged_cells(row)
        if not cells:
            continue
        label = _norm_label(cells[0].text)
        if "diluted weighted-average" in label:
            saw_header = True
            continue
        if not saw_header:
            continue
        if "class" in label and "a" in label and "basic" not in label:
            cell = _first_money_cell(cells)
            if cell is None:
                continue
            observations.append(
                _obs(
                    field_name="diluted_shares",
                    value=_parse_cell_number(cell, "shares_millions", field_name="diluted_shares"),
                    fy=fy,
                    fq=fq,
                    source_id=source_id,
                    html=html,
                    cell=cell,
                    anchor=cells[0].text.strip()[:80],
                )
            )
            break
        if label.startswith("class b") or label.startswith("class c"):
            continue
        if label and not label.startswith("class"):
            # left the diluted shares block
            if saw_header and "class" not in label:
                break
    return observations


def _parse_ops_income(table: Table, html: str, *, fy: int, fq: int, source_id: str) -> list[ParsedObservation]:
    out: list[ParsedObservation] = []
    for row in table.rows:
        cells = merged_cells(row)
        if not cells:
            continue
        label = _norm_label(cells[0].text)
        if label == "operating income":
            cell = _first_money_cell(cells)
            if cell is None:
                continue
            out.append(
                _obs(
                    field_name="operating_profit_gaap",
                    value=_parse_cell_number(cell, "usd_millions"),
                    fy=fy,
                    fq=fq,
                    source_id=source_id,
                    html=html,
                    cell=cell,
                    anchor=cells[0].text.strip()[:80],
                    location="cross_check",
                    statement_type="measured",
                )
            )
    return out


def _first_opex_cell(cells: list[Cell]) -> Cell | None:
    """Operating-expense column is the first value after the label (dash means none)."""
    for cell in cells[1:]:
        token = cell.text.replace("\xa0", " ").strip()
        if token in {"$", ""}:
            continue
        if token in {"—", "-", "–"}:
            return None
        if _is_money_token(token):
            return cell
        return None
    return None


def _parse_recon(tables: list[Table], html: str, *, fy: int, fq: int, source_id: str) -> list[ParsedObservation]:
    observations: list[ParsedObservation] = []
    used_three = False
    for table in tables:
        joined = table.joined_text()
        if "Three Months Ended" not in joined:
            continue
        if used_three:
            continue
        used_three = True
        in_three = True
        for row in table.rows:
            cells = merged_cells(row)
            if not cells:
                continue
            label = _norm_label(cells[0].text)
            raw_label = re.sub(r"\s+", " ", cells[0].text.replace("\xa0", " ")).strip()
            if "three months ended" in label:
                in_three = True
                continue
            if "nine months ended" in label or "twelve months ended" in label:
                in_three = False
                continue
            if not in_three:
                continue
            if label in {"as reported", "non-gaap", "as adjusted", "adjusted"}:
                cell = _first_opex_cell(cells)
                if cell is None:
                    continue
                field_name = (
                    "operating_expenses_gaap" if label == "as reported" else "operating_expenses_ex_special_items"
                )
                observations.append(
                    _obs(
                        field_name=field_name,
                        value=_parse_cell_number(cell, "usd_millions"),
                        fy=fy,
                        fq=fq,
                        source_id=source_id,
                        html=html,
                        cell=cell,
                        anchor=raw_label[:80],
                        location="cross_check",
                    )
                )
                continue
            cell = _first_opex_cell(cells)
            if cell is None:
                continue
            token = cell.text.replace("\xa0", " ").strip()
            observations.append(
                _obs(
                    field_name="special_item_operating_expense",
                    value=parse_numeric_quote(token, "usd_millions"),
                    fy=fy,
                    fq=fq,
                    source_id=source_id,
                    html=html,
                    cell=cell,
                    anchor=raw_label[:80],
                    attributes={"item": raw_label},
                    note="three-month operating-expense bridge line",
                )
            )
    return observations


_PRIOR_PV_RE = re.compile(
    r"Payments volume for the three months ended (?P<date>[A-Za-z]+\s+\d{1,2},\s+\d{4}), "
    r"on which fiscal (?P<ordinal>first|second|third|fourth) quarter service revenues? "
    r"(?:is|are) recognized,\s+(?:increased|decreased|grew|was)\s+(?P<pct>-?\d+(?:\.\d+)?)%",
    re.IGNORECASE,
)
_TXN_RE = re.compile(
    r"three months ended (?P<date>[A-Za-z]+\s+\d{1,2},\s+\d{4}), were\s+(?P<n>\d+(?:\.\d+))\s+billion",
    re.IGNORECASE,
)
_TAX_RE = re.compile(
    r"(?:GAAP )?effective income tax rate was\s+(?P<n>\d+(?:\.\d+))\s*%",
    re.IGNORECASE,
)
_CB_FY2017_RE = re.compile(
    r"Cross-border volume growth, on a constant dollar basis, was\s+(?P<pct>-?\d+(?:\.\d+)?)%",
    re.IGNORECASE,
)
_PV_CURRENT_RE = re.compile(
    r"Payments volume for the three months ended (?P<date>[A-Za-z]+\s+\d{1,2},\s+\d{4}) "
    r"(?:increased|grew|was)\s+(?P<pct>-?\d+(?:\.\d+)?)%",
    re.IGNORECASE,
)


def _html_search(html: str, quote: str, needle: str) -> tuple[str, int, int] | None:
    idx = html.find(needle)
    if idx < 0:
        # allow missing tags by searching quote after a shortened needle
        idx = html.lower().find(needle.lower())
        if idx < 0:
            q = html.find(quote)
            if q < 0:
                return None
            return quote, q, q + len(quote)
    q = html.find(quote, idx)
    if q < 0:
        return None
    return quote, q, q + len(quote)


def _parse_prose(html: str, *, fy: int, fq: int, source_id: str) -> list[ParsedObservation]:
    observations: list[ParsedObservation] = []
    # Strip tags for regex, but locate quotes in raw HTML.
    text = re.sub(r"<[^>]+>", " ", html)
    text = html_lib_unescape(text)
    text = re.sub(r"\s+", " ", text)

    py, pq = prev_fiscal(fy, fq)
    m = _PRIOR_PV_RE.search(text)
    if m:
        quote = f"{m.group('pct')}%"
        loc = _html_search(html, quote, "on which fiscal")
        if loc:
            q, start, end = loc
            # Prefer the first % after the recognized phrase.
            phrase = "on which fiscal"
            p_at = html.find(phrase)
            if p_at >= 0:
                q_at = html.find(quote, p_at)
                if q_at >= 0:
                    q, start, end = quote, q_at, q_at + len(quote)
            pl, ps, pe = fiscal_dates(py, pq)
            observations.append(
                _obs(
                    field_name="payments_volume_prior_quarter_growth_constant",
                    value=float(m.group("pct")),
                    fy=py,
                    fq=pq,
                    source_id=source_id,
                    html=html,
                    quote=q,
                    start=start,
                    end=end,
                    anchor="on which fiscal",
                    period_label=pl,
                    period_start=ps,
                    period_end=pe,
                )
            )
    m = _TXN_RE.search(text)
    if m:
        quote = m.group("n")
        loc = _html_search(html, quote, "three months ended")
        if loc:
            q, start, end = loc
            date_s = m.group("date")
            d_at = html.find(date_s)
            if d_at >= 0:
                q_at = html.find(quote, d_at)
                if q_at >= 0:
                    q, start, end = quote, q_at, q_at + len(quote)
            observations.append(
                _obs(
                    field_name="processed_transactions_count",
                    value=float(m.group("n")) * 1000.0,
                    fy=fy,
                    fq=fq,
                    source_id=source_id,
                    html=html,
                    quote=q,
                    start=start,
                    end=end,
                    anchor="three months ended",
                )
            )
    m = _TAX_RE.search(text)
    if m:
        quote = m.group("n")
        loc = _html_search(html, quote, "effective income tax rate was")
        if loc:
            q, start, end = loc
            observations.append(
                _obs(
                    field_name="tax_rate",
                    value=round(float(m.group("n")) / 100.0, 6),
                    fy=fy,
                    fq=fq,
                    source_id=source_id,
                    html=html,
                    quote=q,
                    start=start,
                    end=end,
                    anchor="effective income tax rate was",
                )
            )
    if fy == 2017:
        m = _CB_FY2017_RE.search(text)
        if m:
            quote = f"{m.group('pct')}%"
            loc = _html_search(html, quote, "Cross-border volume growth")
            if loc:
                q, start, end = loc
                observations.append(
                    _obs(
                        field_name="cross_border_total_growth_constant",
                        value=float(m.group("pct")),
                        fy=fy,
                        fq=fq,
                        source_id=source_id,
                        html=html,
                        quote=q,
                        start=start,
                        end=end,
                        anchor="Cross-border volume growth",
                    )
                )
        m = re.search(
            r"Payments volume growth, on a constant dollar basis, for the three months ended "
            r"(?P<date>[A-Za-z]+\s+\d{1,2},\s+\d{4}), was\s+(?P<pct>-?\d+(?:\.\d+)?)%",
            text,
            re.I,
        )
        if m:
            quote = f"{m.group('pct')}%"
            loc = _html_search(html, quote, "Payments volume growth, on a constant dollar basis")
            if loc:
                q, start, end = loc
                observations.append(
                    _obs(
                        field_name="payments_volume_growth_constant",
                        value=float(m.group("pct")),
                        fy=fy,
                        fq=fq,
                        source_id=source_id,
                        html=html,
                        quote=q,
                        start=start,
                        end=end,
                        anchor="Payments volume growth, on a constant dollar basis",
                    )
                )
    return observations


def html_lib_unescape(text: str) -> str:
    import html as html_lib

    return html_lib.unescape(text)


def _parse_image_layer(
    layout: DocumentLayout,
    html: str,
    *,
    fy: int,
    fq: int,
    source_id: str,
) -> list[ParsedObservation]:
    observations: list[ParsedObservation] = []
    layer = layout.text_layer_text()
    runs = layout.text_layer_runs
    period = f"FY{fy}Q{fq}"

    def add_from_match(field_name: str, value: float, quote: str, match_start: int, anchor: str) -> None:
        raw = map_joined_index(runs, match_start + layer[match_start : match_start + 80].find(quote))
        if raw is None:
            loc = _html_search(html, quote, anchor[:40] if anchor else quote)
            if loc is None:
                return
            q, start, end = loc
        else:
            # map_joined_index of quote start
            rel = layer.find(quote, match_start)
            raw_start = map_joined_index(runs, rel) if rel >= 0 else raw
            if raw_start is None:
                return
            q, start, end = quote, raw_start, raw_start + len(quote)
        observations.append(
            _obs(
                field_name=field_name,
                value=value,
                fy=fy,
                fq=fq,
                source_id=source_id,
                html=html,
                quote=q,
                start=start,
                end=end,
                anchor=anchor,
            )
        )

    patterns: list[tuple[str, re.Pattern[str], str]] = [
        ("service_revenue", re.compile(r"Service revenues?\s*\$?\s*([\d,]+)", re.I), "Service revenue"),
        ("data_processing_revenue", re.compile(r"Data processing revenues?\s*\$?\s*([\d,]+)", re.I), "Data processing"),
        (
            "international_transaction_revenue",
            re.compile(r"International transaction revenues?\s*\$?\s*([\d,]+)", re.I),
            "International transaction",
        ),
        ("other_revenue", re.compile(r"Other revenues?\s*\$?\s*([\d,]+)", re.I), "Other revenue"),
        ("client_incentives", re.compile(r"Client incentives\s*\(([\d,]+)\)", re.I), "Client incentives"),
        (
            "net_revenue",
            re.compile(r"Net (?:operating )?revenues?\s*\$?\s*([\d,]+)", re.I),
            "Net revenue",
        ),
        (
            "operating_expenses_gaap",
            re.compile(r"Total operating expenses\s*\$?\s*([\d,]+)", re.I),
            "Total operating expenses",
        ),
    ]
    for field_name, cre, anchor in patterns:
        m = cre.search(layer)
        if not m:
            continue
        raw_num = m.group(1)
        quote = f"({raw_num})" if field_name == "client_incentives" else raw_num
        spec = FIELD_BY_NAME[field_name]
        try:
            value = convert_quote(quote, spec.unit, field_name=field_name)
        except ValueError:
            continue
        add_from_match(field_name, value, quote, m.start(), anchor)

    m = re.search(r"Non-operating[^\d%]{0,60}(\(?-?[\d,]+\)?)", layer, re.I)
    if m:
        quote = m.group(1)
        try:
            add_from_match(
                "net_interest_other",
                convert_quote(quote, "usd_millions"),
                quote,
                m.start(),
                "Non-operating",
            )
        except ValueError:
            pass

    m = re.search(r"Effective (?:income )?tax rate\s+(\d+(?:\.\d+))\s*%", layer, re.I)
    if m:
        add_from_match("tax_rate", float(m.group(1)) / 100.0, m.group(1), m.start(), "Effective")

    kbd_specs = [
        ("payments volume", "payments_volume_growth_constant", "payments_volume_growth_nominal"),
        (
            r"cross-border volume excluding intra-europe(?:\([^)]*\))?",
            "cross_border_ex_intra_europe_growth_constant",
            "cross_border_ex_intra_europe_growth_nominal",
        ),
        (
            "cross-border volume total",
            "cross_border_total_growth_constant",
            "cross_border_total_growth_nominal",
        ),
        ("cross-border volume", "cross_border_total_growth_constant", "cross_border_total_growth_nominal"),
        ("processed transactions", "processed_transactions_growth", "processed_transactions_growth"),
    ]
    for label, cfield, nfield in kbd_specs:
        cre = re.compile(rf"{label}\s+(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%", re.I)
        m = cre.search(layer)
        if not m:
            continue
        if period_in_range(period, FIELD_BY_NAME[cfield].first_period, FIELD_BY_NAME[cfield].last_period):
            add_from_match(cfield, float(m.group(1)), f"{m.group(1)}%", m.start(), label)
        if cfield != nfield and period_in_range(
            period, FIELD_BY_NAME[nfield].first_period, FIELD_BY_NAME[nfield].last_period
        ):
            add_from_match(nfield, float(m.group(2)), f"{m.group(2)}%", m.start(), label)
    return observations


def expected_release_fields(fy: int, fq: int) -> list[str]:
    period = f"FY{fy}Q{fq}"
    names = [
        "service_revenue",
        "data_processing_revenue",
        "international_transaction_revenue",
        "other_revenue",
        "client_incentives",
        "net_revenue",
        "operating_expenses_gaap",
        "operating_expenses_ex_special_items",
        "processed_transactions_count",
        "payments_volume_growth_constant",
        "payments_volume_prior_quarter_growth_constant",
        "cross_border_total_growth_constant",
        "processed_transactions_growth",
        "tax_rate",
        "net_interest_other",
        "diluted_shares",
    ]
    optional = [
        "payments_volume_growth_nominal",
        "cross_border_ex_intra_europe_growth_constant",
        "cross_border_ex_intra_europe_growth_nominal",
        "cross_border_total_growth_nominal",
    ]
    out: list[str] = []
    for name in names + optional:
        spec = FIELD_BY_NAME[name]
        if period_in_range(period, spec.first_period, spec.last_period):
            if name in optional and not period_in_range(period, spec.first_period, spec.last_period):
                continue
            out.append(name)
    return out


def _identity(name: str, left: float, right: float, unit: str) -> IdentityCheck:
    tol = {"usd_millions": 0.5, "usd_billions": 1.5, "percent": 0.5, "ratio": 0.0005}.get(unit, 0.5)
    residual = left - right
    return IdentityCheck(name, left, right, residual, tol, abs(residual) <= tol)


def _value_map(obs: list[ParsedObservation]) -> dict[str, ParsedObservation]:
    out: dict[str, ParsedObservation] = {}
    for item in obs:
        if item.location != "primary":
            continue
        if item.field in out:
            continue
        out[item.field] = item
    return out


def _run_identities(obs: list[ParsedObservation]) -> list[IdentityCheck]:
    by = _value_map(obs)
    checks: list[IdentityCheck] = []

    def g(name: str) -> float | None:
        item = by.get(name)
        return None if item is None else item.value

    service, data, intl, other, incentives, net = (
        g("service_revenue"),
        g("data_processing_revenue"),
        g("international_transaction_revenue"),
        g("other_revenue"),
        g("client_incentives"),
        g("net_revenue"),
    )
    if (
        service is not None
        and data is not None
        and intl is not None
        and other is not None
        and incentives is not None
        and net is not None
    ):
        checks.append(
            _identity("net_revenue_identity", service + data + intl + other - incentives, net, "usd_millions")
        )
    opex = g("operating_expenses_gaap")
    nr = g("net_revenue")
    op = g("operating_profit_gaap")
    if nr is not None and opex is not None and op is not None:
        checks.append(_identity("operating_profit_gaap_identity", nr - opex, op, "usd_millions"))
    opex_ex = g("operating_expenses_ex_special_items")
    if nr is not None and opex_ex is not None:
        op_ex = nr - opex_ex
        existing = next(
            (x for x in obs if x.field == "operating_profit_ex_special_items" and x.location == "primary"), None
        )
        if existing:
            checks.append(_identity("operating_profit_ex_identity", op_ex, existing.value, "usd_millions"))
    if opex is not None and opex_ex is not None:
        special = opex - opex_ex
        existing_s = next((x for x in obs if x.field == "special_items" and x.location == "primary"), None)
        if existing_s:
            checks.append(_identity("opex_bridge_identity", opex - existing_s.value, opex_ex, "usd_millions"))
        else:
            checks.append(_identity("opex_bridge_identity", opex - special, opex_ex, "usd_millions"))
    # Recon vs summary Non-GAAP opex
    recon_ex = next(
        (x for x in obs if x.field == "operating_expenses_ex_special_items" and x.location == "cross_check"),
        None,
    )
    if opex_ex is not None and recon_ex is not None:
        checks.append(_identity("nongap_opex_cross_check", opex_ex, recon_ex.value, "usd_millions"))
    items = [x.value for x in obs if x.field == "special_item_operating_expense"]
    recon_gaap = next(
        (x for x in obs if x.field == "operating_expenses_gaap" and x.location == "cross_check"),
        None,
    )
    if recon_gaap is not None and recon_ex is not None and items:
        checks.append(_identity("recon_sum_identity", recon_gaap.value + sum(items), recon_ex.value, "usd_millions"))
    return checks


def parse_release(
    html: str,
    *,
    accession: str,
    document: str,
    fiscal_year: int,
    fiscal_quarter: int,
) -> ParseResult:
    layout = parse_html(html)
    era = detect_format(layout, fiscal_year)
    source_id = source_id_of(accession, document)
    period_label, _, _ = fiscal_dates(fiscal_year, fiscal_quarter)
    result = ParseResult(
        accession=accession,
        document=document,
        form="8-K Ex. 99.1",
        era=era,
        period_label=period_label,
    )
    obs: list[ParsedObservation] = []
    iss = _iss_table(layout)
    if iss is not None:
        obs.extend(_parse_iss_from_table(iss, html, fy=fiscal_year, fq=fiscal_quarter, source_id=source_id))
        obs.extend(_parse_kbd_from_table(iss, html, fy=fiscal_year, fq=fiscal_quarter, source_id=source_id))
    elif era == "table_2017":
        ops = _iss_table(layout) or next(
            (
                t
                for t in layout.tables
                if "Service revenues" in t.joined_text() and "Client incentives" in t.joined_text()
            ),
            None,
        )
        if ops is not None:
            obs.extend(_parse_iss_from_table(ops, html, fy=fiscal_year, fq=fiscal_quarter, source_id=source_id))
    if era == "image_text_layer":
        obs.extend(_parse_image_layer(layout, html, fy=fiscal_year, fq=fiscal_quarter, source_id=source_id))
    ops = _ops_table(layout)
    if ops is not None:
        obs.extend(_parse_shares(ops, html, fy=fiscal_year, fq=fiscal_quarter, source_id=source_id))
        obs.extend(_parse_ops_income(ops, html, fy=fiscal_year, fq=fiscal_quarter, source_id=source_id))
    recon = _parse_recon(_recon_tables(layout), html, fy=fiscal_year, fq=fiscal_quarter, source_id=source_id)
    obs.extend(recon)
    obs.extend(_parse_prose(html, fy=fiscal_year, fq=fiscal_quarter, source_id=source_id))

    # Dedup: keep first primary per field (table before prose except tax/txn/prior which prose is primary).
    prose_primary = {
        "tax_rate",
        "processed_transactions_count",
        "payments_volume_prior_quarter_growth_constant",
    }
    chosen: list[ParsedObservation] = []
    seen_primary: set[str] = set()

    def _pkey(item: ParsedObservation) -> str:
        if item.field == "special_item_operating_expense":
            return f"special:{item.attributes.get('item', '')}:{item.span.char_start}"
        return item.field

    # Pass 1: preferred locations
    for item in obs:
        if item.location != "primary":
            chosen.append(item)
            continue
        key = _pkey(item)
        if item.field in prose_primary and item.span.anchor in {
            "effective income tax rate was",
            "three months ended",
            "on which fiscal",
            "GAAP effective income tax rate was ",
        }:
            if key not in seen_primary:
                chosen.append(item)
                seen_primary.add(key)
            continue
        if item.field in prose_primary:
            continue
        if key not in seen_primary:
            chosen.append(item)
            seen_primary.add(key)
    for item in obs:
        if item.location != "primary":
            continue
        key = _pkey(item)
        if key in seen_primary:
            continue
        chosen.append(item)
        seen_primary.add(key)

    by = {x.field: x for x in chosen if x.location == "primary"}
    opex = by.get("operating_expenses_gaap")
    opex_ex = by.get("operating_expenses_ex_special_items")
    recon_ex = next(
        (x for x in chosen if x.field == "operating_expenses_ex_special_items" and x.location == "cross_check"),
        None,
    )
    if opex_ex is None or (
        opex_ex.statement_type == "derived" and recon_ex is not None and abs(recon_ex.value - opex_ex.value) > 0.5
    ):
        if recon_ex is not None:
            if opex_ex is not None and opex_ex.statement_type == "derived":
                chosen = [x for x in chosen if x is not opex_ex]
            promoted = recon_ex.model_copy(update={"location": "primary"})
            chosen.append(promoted)
            opex_ex = promoted
            by["operating_expenses_ex_special_items"] = promoted
        elif opex is not None and opex_ex is None:
            chosen.append(
                _obs(
                    field_name="operating_expenses_ex_special_items",
                    value=opex.value,
                    fy=fiscal_year,
                    fq=fiscal_quarter,
                    source_id=source_id,
                    html=html,
                    quote=opex.span.quote,
                    start=opex.span.char_start,
                    end=opex.span.char_end,
                    anchor=opex.span.anchor,
                    statement_type="derived",
                    note="No operating-expense adjustments in the three-month reconciliation; set equal to GAAP.",
                )
            )
            opex_ex = chosen[-1]
            by["operating_expenses_ex_special_items"] = opex_ex
    if opex is not None and opex_ex is not None and "special_items" not in by:
        chosen.append(
            ParsedObservation(
                field="special_items",
                value=opex.value - opex_ex.value,
                unit="usd_millions",
                basis="gaap",
                period_label=period_label,
                period_start=by["operating_expenses_gaap"].period_start,
                period_end=by["operating_expenses_gaap"].period_end,
                statement_type="derived",
                geography="global",
                source_id=source_id,
                span=opex.span,
                location="primary",
                attributes={"formula": "opex_gaap - opex_ex"},
                note="Net amount removed from GAAP opex",
            )
        )
        by["special_items"] = chosen[-1]
    nr = by.get("net_revenue")
    if nr is not None and opex is not None and "operating_profit_gaap" not in by:
        chosen.append(
            ParsedObservation(
                field="operating_profit_gaap",
                value=nr.value - opex.value,
                unit="usd_millions",
                basis="gaap",
                period_label=period_label,
                period_start=nr.period_start,
                period_end=nr.period_end,
                statement_type="derived",
                geography="global",
                source_id=source_id,
                span=nr.span,
                location="primary",
                attributes={"formula": "net_revenue - opex_gaap"},
            )
        )
        by["operating_profit_gaap"] = chosen[-1]
    if nr is not None and opex_ex is not None and "operating_profit_ex_special_items" not in by:
        chosen.append(
            ParsedObservation(
                field="operating_profit_ex_special_items",
                value=nr.value - opex_ex.value,
                unit="usd_millions",
                basis="ex_special_items",
                period_label=period_label,
                period_start=nr.period_start,
                period_end=nr.period_end,
                statement_type="derived",
                geography="global",
                source_id=source_id,
                span=opex_ex.span,
                location="primary",
                attributes={"formula": "net_revenue - opex_ex"},
            )
        )

    result.observations = chosen
    result.identities = _run_identities(chosen)
    expected = expected_release_fields(fiscal_year, fiscal_quarter)
    have = {x.field for x in chosen if x.location == "primary"}
    for name in expected:
        if name not in have:
            result.missing.append((name, "not found in parsed tables/prose"))
    core = {"service_revenue", "net_revenue", "client_incentives"}
    if not core <= have:
        result.status = "failed"
        result.notes.append("missing core income-statement fields")
    elif result.missing or any(not c.passed for c in result.identities):
        result.status = "partial"
        if any(not c.passed for c in result.identities):
            result.notes.append("identity check failed")
    else:
        result.status = "parsed"
    return result


# --- 10-Q / 10-K payments volume --------------------------------------------

_REGION_ORDER = ("us", "international", "global")


def _parse_month_end(text: str) -> date | None:
    match = MONTH_ENDED_DATE_RE.search(text.replace("\xa0", " "))
    if not match:
        return None
    from datetime import datetime as dt

    return dt.strptime(match.group(0).replace("  ", " "), "%B %d, %Y").date()


def _window_label(kind: str, end: date) -> tuple[str, date, date]:
    if kind.lower().startswith("three"):
        period = VISA_FISCAL_CALENDAR.period_containing(end)
        return period.label(), VISA_FISCAL_CALENDAR.period_start(period), end
    months = {"six": 6, "nine": 9, "twelve": 12}[kind.lower()]
    # Six months ended Dec 31, 2023 = Jul 1 – Dec 31.
    month_index = end.month - 1 - (months - 1)
    year = end.year
    while month_index < 0:
        month_index += 12
        year -= 1
    start = date(year, month_index + 1, 1)
    prefix = {6: "6M", 9: "9M", 12: "TTM"}[months]
    return f"{prefix}_{end.isoformat()}", start, end


def _money_cells(cells: list[Cell]) -> list[Cell]:
    out: list[Cell] = []
    for cell in cells[1:]:
        text = cell.text.replace("\xa0", " ").strip()
        if text in {"$", ""}:
            continue
        if _is_pct_token(text) and not _is_money_token(text.replace("%", "")):
            continue
        if _is_money_token(text):
            out.append(cell)
    return out


def parse_form_financials(
    html: str,
    *,
    accession: str,
    document: str,
    form: str,
) -> ParseResult:
    layout = parse_html(html)
    source_id = source_id_of(accession, document)
    result = ParseResult(
        accession=accession,
        document=document,
        form=form,
        era="table_modern" if layout.table_count else "unknown",
        period_label=None,
    )
    observations: list[ParsedObservation] = []
    identities: list[IdentityCheck] = []

    for table in layout.tables:
        joined = table.joined_text()
        if "Total nominal payments volume" not in joined:
            continue
        current_kind: str | None = None
        current_end: date | None = None
        pending_kind: str | None = None
        pending_month: str | None = None
        pending_day: int | None = None
        for row in table.rows:
            cells = merged_cells(row)
            if not cells:
                continue
            row_text = " ".join(c.text for c in cells).replace("\xa0", " ")
            header = re.search(
                r"(Three|Six|Nine|Twelve)\s*Months?\s*Ended\s*([A-Za-z]+)\s+(\d{1,2})",
                row_text,
                re.IGNORECASE,
            )
            if header:
                pending_kind = header.group(1)
                pending_month = header.group(2)
                pending_day = int(header.group(3))
                continue
            years = [c.text.strip() for c in cells if re.fullmatch(r"20\d{2}", c.text.strip())]
            if pending_kind and pending_month and pending_day and years:
                from datetime import datetime as dt

                current_end = dt.strptime(f"{pending_month} {pending_day} {years[0]}", "%B %d %Y").date()
                current_kind = pending_kind
                continue
            label = _norm_label(cells[0].text)
            field_name: str | None = None
            if label.startswith("total nominal payments volume"):
                field_name = "payments_volume_nominal_us"
            elif label.startswith("cash volume"):
                field_name = "cash_volume_nominal_us"
            elif label.startswith("total nominal volume"):
                field_name = "total_volume_nominal_us"
            if field_name is None or current_kind is None or current_end is None:
                continue
            numbers = _money_cells(cells)
            # Expect 9 values: 3 regions × (current, prior, pct) — pct may have been skipped
            # If pct included as money-like integers, take groups of 3.
            if len(numbers) < 6:
                continue
            # Prefer pattern of 9: current, prior, yoy per region.
            triples: list[tuple[Cell, Cell]] = []
            if len(numbers) >= 9:
                for i in range(0, 9, 3):
                    triples.append((numbers[i], numbers[i + 1]))
            elif len(numbers) >= 6:
                for i in range(0, 6, 2):
                    triples.append((numbers[i], numbers[i + 1]))
            if len(triples) != 3:
                continue
            period_label, p_start, p_end = _window_label(current_kind, current_end)
            spec = FIELD_BY_NAME[field_name]
            region_vals: dict[str, float] = {}
            for region, (cur_cell, prior_cell) in zip(_REGION_ORDER, triples, strict=True):
                cur_val = _parse_cell_number(cur_cell, spec.unit)
                prior_val = _parse_cell_number(prior_cell, spec.unit)
                region_vals[region] = cur_val
                observations.append(
                    _obs(
                        field_name=field_name,
                        value=cur_val,
                        fy=1,
                        fq=1,
                        source_id=source_id,
                        html=html,
                        cell=cur_cell,
                        anchor=cells[0].text.strip()[:80],
                        geography=region,
                        period_label=period_label,
                        period_start=p_start,
                        period_end=p_end,
                        attributes={"vintage_role": "current", "window": current_kind.lower()},
                    )
                )
                observations.append(
                    _obs(
                        field_name=field_name,
                        value=prior_val,
                        fy=1,
                        fq=1,
                        source_id=source_id,
                        html=html,
                        cell=prior_cell,
                        anchor=cells[0].text.strip()[:80],
                        geography=region,
                        period_label=period_label,
                        period_start=p_start,
                        period_end=p_end,
                        attributes={"vintage_role": "comparative", "window": current_kind.lower()},
                        note="prior-year column; not a first print (DR-04)",
                    )
                )
            us, intl, total = (region_vals.get("us"), region_vals.get("international"), region_vals.get("global"))
            if us is not None and intl is not None and total is not None:
                identities.append(_identity(f"pv_geo_{period_label}_{field_name}", us + intl, total, spec.unit))

    result.observations = observations
    result.identities = identities
    if not observations:
        result.status = "failed"
        result.missing.append(("payments_volume_nominal_us", "no Total nominal payments volume table"))
    elif any(not c.passed for c in identities):
        result.status = "partial"
        result.notes.append("geography identity failed")
    else:
        result.status = "parsed"
    return result


def to_observation_create(item: ParsedObservation) -> ObservationCreate:
    return ObservationCreate(
        company="visa",
        source_id=source_uuid_for(item.source_id),
        document_text_id=None,
        span_page=None,
        span_char_start=item.span.char_start,
        span_char_end=item.span.char_end,
        statement_type=item.statement_type if item.statement_type == "measured" else "measured",
        activity_type=item.field,
        geography=item.geography,
        period_start=item.period_start,
        period_end=item.period_end,
        value=item.value,
        unit=item.unit,
        basis=item.basis,
        source_family="visa",
        extractor_id=EXTRACTOR_ID,
        extractor_version=EXTRACTOR_VERSION,
        review_status="pending",
        attributes={
            **item.attributes,
            "field": item.field,
            "period_label": item.period_label,
            "source_id": item.source_id,
            "anchor": item.span.anchor,
            "quote": item.span.quote,
            "location": item.location,
            "note": item.note,
            "content_statement_type": item.statement_type,
        },
    )


def reject_after_cutoff(acceptance_utc: str, cutoff_utc: str, *, accession: str) -> None:
    """Raise if a document's EDGAR acceptance is after the origin cutoff (D-03)."""
    from longaeva_app.collect.edgar_index import _parse_utc

    if _parse_utc(acceptance_utc) > _parse_utc(cutoff_utc):
        raise ValueError(f"{accession} accepted after cutoff {cutoff_utc}")


def lookup_document(accession: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    data = manifest if manifest is not None else load_manifest()
    for row in data.get("sources", []):
        if row["accession"] == accession:
            return row  # type: ignore[no-any-return]
    raise KeyError(accession)


def parse_release_accession(accession: str, *, fy: int, fq: int, manifest: dict[str, Any] | None = None) -> ParseResult:
    row = lookup_document(accession, manifest)
    html = source_text(row["accession"], row["document"])
    verify_source_hash(row["accession"], row["document"], expected=row.get("content_sha256"))
    return parse_release(html, accession=row["accession"], document=row["document"], fiscal_year=fy, fiscal_quarter=fq)


def parse_form_accession(accession: str, *, form: str, manifest: dict[str, Any] | None = None) -> ParseResult:
    row = lookup_document(accession, manifest)
    html = source_text(row["accession"], row["document"])
    verify_source_hash(row["accession"], row["document"], expected=row.get("content_sha256"))
    return parse_form_financials(html, accession=row["accession"], document=row["document"], form=form)


STATUS_COLUMNS = [
    "period",
    "accession",
    "document",
    "era",
    "status",
    "expected_fields",
    "found_fields",
    "missing_fields",
    "identities_passed",
    "identities_failed",
    "prior_10q_accession",
    "prior_10q_status",
    "notes",
]

OBS_COLUMNS = [
    "period_label",
    "field",
    "value",
    "unit",
    "basis",
    "geography",
    "statement_type",
    "location",
    "source_id",
    "char_start",
    "char_end",
    "quote",
    "anchor",
    "vintage_role",
    "note",
]


def iter_origin_parses() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    from longaeva_app.collect.edgar_index import ORIGINS_CSV_PATH

    manifest = load_manifest()
    status_rows: list[dict[str, str]] = []
    obs_rows: list[dict[str, Any]] = []
    with ORIGINS_CSV_PATH.open(encoding="utf-8") as fh:
        origins = list(csv.DictReader(fh))
    for row in origins:
        fy = int(row["fiscal_year"])
        fq = int(row["fiscal_quarter"])
        cutoff = row["cutoff_utc"]
        rel_row = lookup_document(row["release_accession"], manifest)
        prior_row = lookup_document(row["prior_10q_accession"], manifest)
        reject_after_cutoff(rel_row["acceptance_utc"], cutoff, accession=rel_row["accession"])
        reject_after_cutoff(prior_row["acceptance_utc"], cutoff, accession=prior_row["accession"])
        release = parse_release_accession(row["release_accession"], fy=fy, fq=fq, manifest=manifest)
        form = parse_form_accession(row["prior_10q_accession"], form=row["prior_10q_form"], manifest=manifest)
        expected = expected_release_fields(fy, fq)
        found = sorted({o.field for o in release.observations if o.location == "primary"})
        missing = ";".join(f"{n}:{reason}" for n, reason in release.missing)
        status_rows.append(
            {
                "period": f"FY{fy}Q{fq}",
                "accession": release.accession,
                "document": release.document,
                "era": str(release.era),
                "status": release.status,
                "expected_fields": str(len(expected)),
                "found_fields": str(len(found)),
                "missing_fields": missing,
                "identities_passed": str(sum(1 for c in release.identities if c.passed)),
                "identities_failed": str(sum(1 for c in release.identities if not c.passed)),
                "prior_10q_accession": form.accession,
                "prior_10q_status": form.status,
                "notes": "; ".join(release.notes + form.notes),
            }
        )
        for parsed in (*release.observations, *form.observations):
            if parsed.location == "cross_check":
                continue
            to_observation_create(parsed)
            obs_rows.append(
                {
                    "period_label": parsed.period_label,
                    "field": parsed.field,
                    "value": parsed.value,
                    "unit": parsed.unit,
                    "basis": parsed.basis,
                    "geography": parsed.geography,
                    "statement_type": parsed.statement_type,
                    "location": parsed.location,
                    "source_id": parsed.source_id,
                    "char_start": parsed.span.char_start,
                    "char_end": parsed.span.char_end,
                    "quote": parsed.span.quote,
                    "anchor": parsed.span.anchor,
                    "vintage_role": parsed.attributes.get("vintage_role", ""),
                    "note": parsed.note,
                }
            )
    return status_rows, obs_rows


def write_outputs(
    status_rows: list[dict[str, str]],
    obs_rows: list[dict[str, Any]],
    *,
    out_dir: Path | None = None,
) -> tuple[Path, Path]:
    dest = out_dir if out_dir is not None else RELEASES_DIR
    dest.mkdir(parents=True, exist_ok=True)
    status_path = dest / "parse_status.csv"
    obs_path = dest / "observations.csv"
    with status_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=STATUS_COLUMNS)
        writer.writeheader()
        writer.writerows(status_rows)
    obs_rows.sort(
        key=lambda row: (
            str(row["period_label"]),
            str(row["field"]),
            str(row["geography"]),
            str(row["vintage_role"]),
            int(row["char_start"]),
        )
    )
    with obs_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OBS_COLUMNS)
        writer.writeheader()
        writer.writerows(obs_rows)
    return status_path, obs_path
