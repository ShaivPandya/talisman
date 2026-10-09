"""Page-preserving text extraction for HTML and PDF originals.

HTML is split on CSS page breaks; PDFs use pdfminer.six ``extract_pages`` with
no page or character caps. Paragraph passages carry page-local
``[char_start, char_end)`` spans.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from typing import Any

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer

_PAGE_BREAK_RE = re.compile(
    r"page-break-(?:before|after)\s*:\s*always|break-(?:before|after)\s*:\s*page",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class Passage:
    """One extracted text span with a page-local character range."""

    page: int
    char_start: int
    char_end: int
    text: str


def extract_passages(data: bytes, *, content_type: str | None = None, filename: str | None = None) -> list[Passage]:
    """Extract page-preserving passages from ``data``.

    Detection order: explicit content type / filename suffix, then PDF magic,
    otherwise HTML.
    """
    kind = _detect_kind(data, content_type=content_type, filename=filename)
    if kind == "pdf":
        return extract_pdf_passages(data)
    return extract_html_passages(data)


def extract_pdf_passages(data: bytes) -> list[Passage]:
    """Extract passages from a PDF via pdfminer, one page at a time (1-indexed)."""
    passages: list[Passage] = []
    for page_index, page_layout in enumerate(extract_pages(BytesIO(data)), start=1):
        page_text = _page_layout_text(page_layout)
        passages.extend(_passages_from_page_text(page_index, page_text))
    return passages


def extract_html_passages(data: bytes) -> list[Passage]:
    """Extract passages from HTML, splitting pages on CSS page-break rules."""
    text = data.decode("utf-8", errors="replace")
    pages = _HtmlPageSplitter().split(text)
    if not pages:
        pages = [""]
    passages: list[Passage] = []
    for page_index, page_text in enumerate(pages, start=1):
        passages.extend(_passages_from_page_text(page_index, page_text))
    return passages


def _detect_kind(data: bytes, *, content_type: str | None, filename: str | None) -> str:
    lowered_type = (content_type or "").lower()
    name = (filename or "").lower()
    if "pdf" in lowered_type or name.endswith(".pdf"):
        return "pdf"
    if "html" in lowered_type or name.endswith((".htm", ".html", ".shtml")):
        return "html"
    if data[:4] == b"%PDF":
        return "pdf"
    return "html"


def _page_layout_text(page_layout: Any) -> str:
    chunks: list[str] = []
    for element in page_layout:
        if isinstance(element, LTTextContainer):
            chunks.append(element.get_text())
    return "".join(chunks)


def _passages_from_page_text(page: int, page_text: str) -> list[Passage]:
    normalized = _normalize_page_text(page_text)
    if not normalized.strip():
        return []
    passages: list[Passage] = []
    offset = 0
    for block in re.split(r"\n\s*\n", normalized):
        block = block.strip()
        if not block:
            continue
        # Locate the block within the normalized page text for page-local spans.
        idx = normalized.find(block, offset)
        if idx < 0:
            idx = offset
        start = idx
        end = start + len(block)
        passages.append(Passage(page=page, char_start=start, char_end=end, text=block))
        offset = end
    return passages


def _normalize_page_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE_RE.sub(" ", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


class _HtmlPageSplitter(HTMLParser):
    """Collect visible text, starting a new page on CSS page-break styles."""

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
            "tr",
            "br",
            "hr",
            "blockquote",
            "pre",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._pages: list[list[str]] = [[]]
        self._skip_depth = 0
        self._in_table_row = False
        self._row_cells: list[str] = []
        self._current_cell: list[str] = []
        self._hidden_depth = 0

    def split(self, html: str) -> list[str]:
        self.feed(html)
        self.close()
        return [_normalize_page_text("".join(parts)) for parts in self._pages if "".join(parts).strip()]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if lower in self.SKIP_TAGS or lower == "ix:header" or lower.endswith(":header"):
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        style = attr_map.get("style", "")
        if _is_hidden(attr_map, style):
            self._hidden_depth += 1
            return
        if self._hidden_depth:
            return
        if _PAGE_BREAK_RE.search(style):
            self._new_page()
        if lower == "br":
            self._emit("\n")
        elif lower == "tr":
            self._in_table_row = True
            self._row_cells = []
            self._current_cell = []
        elif lower in {"td", "th"} and self._in_table_row:
            self._current_cell = []
        elif lower in self.BLOCK_TAGS:
            self._emit("\n")

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in self.SKIP_TAGS or lower == "ix:header" or lower.endswith(":header"):
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if self._hidden_depth and _is_hidden_end(lower):
            self._hidden_depth -= 1
            return
        if self._hidden_depth:
            return
        if lower in {"td", "th"} and self._in_table_row:
            self._row_cells.append("".join(self._current_cell).strip())
            self._current_cell = []
        elif lower == "tr" and self._in_table_row:
            cells = [c for c in self._row_cells if c]
            if cells:
                self._emit(" | ".join(cells) + "\n")
            self._in_table_row = False
            self._row_cells = []
        elif lower in self.BLOCK_TAGS:
            self._emit("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._hidden_depth:
            return
        if self._in_table_row and self._current_cell is not None:
            # Inside a cell (or between cells — ignore interstitial whitespace).
            if self._current_cell is not None:
                self._current_cell.append(data)
            return
        self._emit(data)

    def _emit(self, text: str) -> None:
        if not text:
            return
        self._pages[-1].append(text)

    def _new_page(self) -> None:
        if self._pages[-1]:
            self._pages.append([])


def _is_hidden(attrs: dict[str, str], style: str) -> bool:
    if attrs.get("hidden") is not None and attrs.get("hidden") != "false":
        return True
    aria = attrs.get("aria-hidden", "").lower()
    if aria == "true":
        return True
    lowered = style.lower()
    return "display:none" in lowered.replace(" ", "") or "visibility:hidden" in lowered.replace(" ", "")


def _is_hidden_end(tag: str) -> bool:
    # Approximate: any end tag may close a hidden element we entered.
    return tag in {
        "div",
        "span",
        "section",
        "p",
        "table",
        "tr",
        "td",
        "th",
        "ul",
        "ol",
        "li",
        "header",
        "footer",
        "aside",
        "nav",
    }
