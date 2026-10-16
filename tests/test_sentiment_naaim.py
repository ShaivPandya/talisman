from __future__ import annotations

import io

import pandas as pd
import pytest
import requests

from macro.sentiment import sentiment


def response(url: str, content: bytes):
    result = requests.Response()
    result.status_code = 200
    result.url = url
    result._content = content
    return result


@pytest.mark.parametrize("historical_link", [b"", b'<a href="/delayed.xlsx">Historical data</a>'])
def test_naaim_reports_subscription_requirement_instead_of_using_delayed_public_data(monkeypatch, historical_link):
    page = response(
        sentiment.NAAIM_PAGE_URL,
        b'<a href="https://index.naaim.org/">Login &amp; Access</a>'
        b"<p>The public data is provided with a three-month delay. A subscription provides current data.</p>"
        + historical_link,
    )
    monkeypatch.setattr(sentiment, "requests_get", lambda *args, **kwargs: page)

    with pytest.raises(ValueError, match="requires member or API access.*three-month delay"):
        sentiment.get_naaim()


def test_naaim_resolves_excel_links_relative_to_redirected_page(monkeypatch):
    workbook = io.BytesIO()
    pd.DataFrame({"Date": ["2026-07-29"], "NAAIM Exposure": [75.5]}).to_excel(workbook, index=False)
    urls = []

    def fetch(url, **kwargs):
        urls.append(url)
        if len(urls) == 1:
            return response(
                "https://naaim.org/programs/naaim-exposure-index/",
                b'<a href="../../files/exposure.xlsx">Historical data</a>',
            )
        return response(url, workbook.getvalue())

    monkeypatch.setattr(sentiment, "requests_get", fetch)

    assert sentiment.get_naaim() == [{"date": "2026-07-29", "exposure": 75.5}]
    assert urls[-1] == "https://naaim.org/files/exposure.xlsx"


def test_naaim_missing_link_without_access_notice_remains_a_scraper_error(monkeypatch):
    monkeypatch.setattr(
        sentiment,
        "requests_get",
        lambda *args, **kwargs: response(sentiment.NAAIM_PAGE_URL, b"<p>Temporarily unavailable</p>"),
    )

    with pytest.raises(ValueError, match="Could not find NAAIM Excel download link"):
        sentiment.get_naaim()
