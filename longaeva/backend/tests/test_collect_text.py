"""Page-preserving text extraction tests."""

from __future__ import annotations

from pathlib import Path

from longaeva_app.collect.text import extract_html_passages, extract_passages, extract_pdf_passages

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
ADV2406 = PACKAGE_ROOT / "data" / "fixtures" / "census" / "sources" / "adv2406.pdf"


def test_pdf_keeps_page_numbers() -> None:
    data = ADV2406.read_bytes()
    passages = extract_pdf_passages(data)
    pages = {p.page for p in passages}
    assert pages == {1, 2, 3, 4, 5, 6, 7}
    assert all(p.char_end >= p.char_start for p in passages)
    for p in passages:
        assert p.text
        assert p.char_end - p.char_start == len(p.text)


def test_html_page_break_splitting() -> None:
    html = b"""
    <html><body>
      <div>First page paragraph one.</div>
      <div style="page-break-before: always">Second page paragraph.</div>
      <p>Second page continues.</p>
    </body></html>
    """
    passages = extract_html_passages(html)
    pages = sorted({p.page for p in passages})
    assert pages == [1, 2]
    assert any("First page" in p.text for p in passages if p.page == 1)
    assert any("Second page" in p.text for p in passages if p.page == 2)


def test_html_table_rows_pipe_separated() -> None:
    html = b"<html><body><table><tr><td>Net revenue</td><td>100</td></tr></table></body></html>"
    passages = extract_html_passages(html)
    joined = "\n".join(p.text for p in passages)
    assert "Net revenue | 100" in joined


def test_extract_passages_detects_pdf_magic() -> None:
    data = ADV2406.read_bytes()
    passages = extract_passages(data)
    assert max(p.page for p in passages) == 7
