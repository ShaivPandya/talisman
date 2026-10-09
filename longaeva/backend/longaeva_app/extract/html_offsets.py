"""Offset-preserving HTML table and prose reader for structured parser.

Character offsets are into the UTF-8-decoded original document, so
``html[char_start:char_end] == quote`` for every emitted span.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from typing import Literal

SKIP_TAGS = frozenset({"script", "style", "noscript", "template"})
BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "br",
        "hr",
        "blockquote",
        "pre",
        "ul",
        "ol",
    }
)
_HIDDEN_STYLE_RE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)
_WHITE_FONT_RE = re.compile(r"color\s*:\s*white", re.IGNORECASE)
_TINY_FONT_RE = re.compile(r"font-size\s*:\s*1pt", re.IGNORECASE)
_NAME_RE = re.compile(r"[a-zA-Z][\w:.-]*")


@dataclass(frozen=True, slots=True)
class TextRun:
    """One contiguous text node with raw document offsets."""

    text: str
    raw_start: int
    raw_end: int
    kind: Literal["visible", "hidden", "text_layer"] = "visible"


@dataclass
class Cell:
    runs: list[TextRun] = field(default_factory=list)
    is_header: bool = False

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs).strip()

    @property
    def raw_start(self) -> int | None:
        if not self.runs:
            return None
        return self.runs[0].raw_start

    @property
    def raw_end(self) -> int | None:
        if not self.runs:
            return None
        return self.runs[-1].raw_end

    def find_quote(self, quote: str) -> tuple[int, int] | None:
        """Locate ``quote`` as a contiguous raw substring covering cell runs."""
        if not quote or not self.runs:
            return None
        for run in self.runs:
            idx = run.text.find(quote)
            if idx >= 0:
                start = run.raw_start + idx
                return start, start + len(quote)
        return None


@dataclass
class Row:
    cells: list[Cell] = field(default_factory=list)


@dataclass
class Table:
    start: int
    end: int
    rows: list[Row] = field(default_factory=list)
    preceding_text: str = ""

    def row_texts(self) -> list[str]:
        return [" | ".join(cell.text for cell in row.cells if cell.text) for row in self.rows]

    def joined_text(self) -> str:
        return "\n".join(t for t in self.row_texts() if t)


@dataclass
class DocumentLayout:
    html: str
    tables: list[Table]
    visible_runs: list[TextRun]
    text_layer_runs: list[TextRun]
    era_hints: dict[str, int]

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def img_count(self) -> int:
        return self.era_hints.get("img", 0)

    @property
    def text_layer_chars(self) -> int:
        return sum(len(run.text) for run in self.text_layer_runs)

    def visible_text(self) -> str:
        return "".join(run.text for run in self.visible_runs)

    def text_layer_text(self) -> str:
        return "".join(run.text for run in self.text_layer_runs)


def parse_html(html: str) -> DocumentLayout:
    """Walk ``html`` and collect tables, visible runs, and image-era text layers."""
    parser = _OffsetParser(html)
    parser.feed()
    return DocumentLayout(
        html=html,
        tables=parser.tables,
        visible_runs=parser.visible_runs,
        text_layer_runs=parser.text_layer_runs,
        era_hints=dict(parser.era_hints),
    )


class _OffsetParser:
    def __init__(self, html: str) -> None:
        self.html = html
        self.tables: list[Table] = []
        self.visible_runs: list[TextRun] = []
        self.text_layer_runs: list[TextRun] = []
        self.era_hints: dict[str, int] = {"img": 0, "table": 0, "white_font": 0}
        self._table_stack: list[Table] = []
        self._row: Row | None = None
        self._cell: Cell | None = None
        self._skip_depth = 0
        self._hidden_depth = 0
        self._text_layer_depth = 0
        self._preceding: list[str] = []
        self._tag_stack: list[str] = []

    def feed(self) -> None:
        html = self.html
        n = len(html)
        pos = 0
        while pos < n:
            lt = html.find("<", pos)
            if lt < 0:
                if self._skip_depth == 0:
                    self._handle_text(html[pos:], pos, n)
                break
            if lt > pos and self._skip_depth == 0:
                self._handle_text(html[pos:lt], pos, lt)
            if html.startswith("<!--", lt):
                end = html.find("-->", lt + 4)
                pos = n if end < 0 else end + 3
                continue
            if html.startswith("<![", lt) or html.startswith("<!", lt):
                gt = html.find(">", lt)
                pos = n if gt < 0 else gt + 1
                continue
            closing = lt + 1 < n and html[lt + 1] == "/"
            name_at = lt + 2 if closing else lt + 1
            m = _NAME_RE.match(html, name_at)
            if not m:
                if self._skip_depth == 0:
                    self._handle_text(html[lt : lt + 1], lt, lt + 1)
                pos = lt + 1
                continue
            name = m.group(0).lower()
            gt = html.find(">", m.end())
            if gt < 0:
                pos = n
                break
            attrs_raw = html[m.end() : gt]
            if closing:
                self._handle_end(name)
            else:
                self._handle_start(name, attrs_raw, lt)
                if name == "img":
                    self.era_hints["img"] = self.era_hints.get("img", 0) + 1
            pos = gt + 1
        for table in self.tables:
            if table.end == 0:
                table.end = n

    def _handle_start(self, name: str, attrs_raw: str, start: int) -> None:
        style = _attr(attrs_raw, "style")
        if name in SKIP_TAGS or name == "ix:header" or name.endswith(":header"):
            self._skip_depth += 1
            self._tag_stack.append(name)
            return
        if self._skip_depth:
            self._tag_stack.append(name)
            return
        hidden = _is_hidden(attrs_raw, style)
        text_layer = _is_text_layer(style)
        if hidden:
            self._hidden_depth += 1
        if text_layer:
            self._text_layer_depth += 1
            self.era_hints["white_font"] = self.era_hints.get("white_font", 0) + 1
        self._tag_stack.append(name)

        if name == "table":
            self.era_hints["table"] = self.era_hints.get("table", 0) + 1
            preceding = " ".join(self._preceding[-8:])
            table = Table(start=start, end=0, preceding_text=preceding)
            self._table_stack.append(table)
        elif name == "tr" and self._table_stack:
            self._row = Row()
        elif name in {"td", "th"} and self._row is not None:
            self._cell = Cell(is_header=name == "th")
        elif name in BLOCK_TAGS and not self._table_stack:
            self.visible_runs.append(TextRun("\n", start, start, "visible"))

    def _handle_end(self, name: str) -> None:
        if self._tag_stack:
            self._tag_stack.pop()
        if name in SKIP_TAGS or name == "ix:header" or name.endswith(":header"):
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if name in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.cells.append(self._cell)
            self._cell = None
        elif name == "tr" and self._row is not None and self._table_stack:
            self._table_stack[-1].rows.append(self._row)
            self._row = None
        elif name == "table" and self._table_stack:
            table = self._table_stack.pop()
            table.end = table.start
            # end filled by caller approximately; keep last row raw_end if present
            last = 0
            for row in table.rows:
                for cell in row.cells:
                    if cell.raw_end is not None:
                        last = max(last, cell.raw_end)
            table.end = last or table.start
            self.tables.append(table)
            preview = table.joined_text()[:80]
            if preview:
                self._preceding.append(preview)
        if self._hidden_depth and name in {
            "div",
            "span",
            "font",
            "p",
            "section",
            "table",
            "tr",
            "td",
            "th",
            "a",
        }:
            self._hidden_depth = max(0, self._hidden_depth - 1)
        if self._text_layer_depth and name in {"div", "span", "font", "p"}:
            self._text_layer_depth = max(0, self._text_layer_depth - 1)

    def _handle_text(self, raw: str, start: int, end: int) -> None:
        if not raw:
            return
        decoded = html_lib.unescape(raw)
        if self._cell is not None:
            kind: Literal["visible", "hidden", "text_layer"] = "visible"
            if self._text_layer_depth:
                kind = "text_layer"
            elif self._hidden_depth:
                kind = "hidden"
            self._cell.runs.append(TextRun(decoded, start, end, kind))
            return
        if self._text_layer_depth:
            self.text_layer_runs.append(TextRun(decoded, start, end, "text_layer"))
            return
        if self._hidden_depth:
            return
        if not self._table_stack:
            self.visible_runs.append(TextRun(decoded, start, end, "visible"))
            stripped = decoded.strip()
            if stripped:
                self._preceding.append(stripped[:120])
                if len(self._preceding) > 40:
                    self._preceding = self._preceding[-40:]


def _attr(attrs_raw: str, name: str) -> str:
    match = re.search(rf"""{name}\s*=\s*(["'])(.*?)\1""", attrs_raw, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(2)
    match = re.search(rf"""{name}\s*=\s*([^\s>]+)""", attrs_raw, re.IGNORECASE)
    return match.group(1) if match else ""


def _is_hidden(attrs_raw: str, style: str) -> bool:
    if re.search(r"\bhidden\b", attrs_raw, re.IGNORECASE) and 'hidden="false"' not in attrs_raw.lower():
        return True
    if re.search(r'aria-hidden\s*=\s*["\']true["\']', attrs_raw, re.IGNORECASE):
        return True
    return bool(_HIDDEN_STYLE_RE.search(style))


def _is_text_layer(style: str) -> bool:
    return bool(_WHITE_FONT_RE.search(style) or _TINY_FONT_RE.search(style))


def locate_in_html(html: str, quote: str, *, after: int = 0, before: int | None = None) -> tuple[int, int] | None:
    """Find ``quote`` in raw HTML after ``after``, optionally bounded by ``before``."""
    end = before if before is not None else len(html)
    idx = html.find(quote, after, end)
    if idx < 0:
        return None
    return idx, idx + len(quote)


def map_joined_index(runs: list[TextRun], joined_index: int) -> int | None:
    """Map an index in concatenated run text to a raw document offset."""
    cursor = 0
    for run in runs:
        length = len(run.text)
        if cursor + length > joined_index:
            return run.raw_start + (joined_index - cursor)
        cursor += length
    return None


def locate_after_anchor(html: str, anchor: str, quote: str) -> tuple[int, int]:
    """Find ``quote`` after the first ``anchor`` (starting-state reconstruction locate_span semantics)."""
    if not anchor:
        raise ValueError("anchor must be non-empty")
    if not quote:
        raise ValueError("quote must be non-empty")
    anchor_at = html.find(anchor)
    if anchor_at < 0:
        raise ValueError(f"anchor not found: {anchor!r}")
    first = html.find(quote, anchor_at + len(anchor))
    if first < 0:
        raise ValueError(f"quote not found after anchor: quote={quote!r} anchor={anchor!r}")
    return first, first + len(quote)
