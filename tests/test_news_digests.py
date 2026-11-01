from __future__ import annotations

import pytest

from portfolio import news_digests
from tests.test_ontology_command_service import (
    NormalizingTemporalRepo,
    OntologyCommandService,
    OntologyObjectService,
    _isolate_news_digest_store,
)

PIPELINE_DIGEST = """# Newsletter Digest — October 10, 2026

**3 items** at confidence ≥ 0.60 from **3 newsletters** · **2 multi-signal**

## Top 10 Stories

1. **FSB: only four jurisdictions have a credible backstop for failing banks** — (FT Markets Afternoon Briefing)
2. Apple cuts iPhone 18 Pro orders on soft demand *(Nikkei Asia My News)*

**Signal density.** Nothing unusual today.

---

## Central Bank Liquidity & Policy

- **FSB: only four jurisdictions have a credible backstop for failing banks** `[MULTI-SIGNAL]` — (FT Markets Afternoon Briefing) — [ft.com](https://www.ft.com/content/abc)
  - `liquidity_path, leading_credit, disequilibrium` · confidence 0.70 · also: Reuters Global Investor
  - Most countries are unprepared for bank failures, the watchdog warns.
- **Ed Harrison: the pace, not the level, is what breaks things** — (Bloomberg (Ed Harrison)) — [body content]
  - *tags:* `yield_curve` `regime_shift` · *confidence:* 0.65
  - The speed of the move in long yields matters more than where they settle.

## Leading Indicators: Consumer

- **Apple cuts iPhone 18 Pro orders on soft demand** `[MULTI-SIGNAL]` — (Nikkei Asia My News) — https://asia.nikkei.com/apple
  - `leading_retail · industry_demand_signal` · confidence 0.80
  - Suppliers blame the premium price hike.

## Second-Order Implications

### Central Bank Liquidity & Policy

- **FSB: only four jurisdictions have a credible backstop for failing banks** `[MULTI-SIGNAL]` — Bank funding spreads widen first where there is no backstop.
- **Ed Harrison: the pace, not the level, is what breaks things**
  - Fast repricing forces de-risking before fundamentals change.

### Leading Indicators: Consumer

- **Apple cuts iPhone 18 Pro orders on soft demand** `[MULTI-SIGNAL]` — Memory costs are now destroying handset demand.
"""


def _stories_by_headline(parsed):
    return {story["headline"]: story for story in parsed["stories"]}


def test_parse_pipeline_digest_extracts_structured_stories():
    parsed = news_digests.parse_digest_markdown(PIPELINE_DIGEST, filename="10102026_digest.md")

    assert parsed["title"] == "Newsletter Digest — October 10, 2026"
    assert parsed["generated_date"] == "2026-10-10"
    assert [section["name"] for section in parsed["sections"]] == [
        "Central Bank Liquidity & Policy",
        "Leading Indicators: Consumer",
    ]
    assert parsed["story_count"] == 3
    assert parsed["multi_signal_count"] == 2

    stories = _stories_by_headline(parsed)
    fsb = stories["FSB: only four jurisdictions have a credible backstop for failing banks"]
    assert fsb["source"] == "FT Markets Afternoon Briefing"
    assert fsb["url"] == "https://www.ft.com/content/abc"
    assert fsb["multi_signal"] is True
    assert fsb["tags"] == ["liquidity_path", "leading_credit", "disequilibrium"]
    assert fsb["confidence"] == pytest.approx(0.70)
    assert fsb["also_sources"] == ["Reuters Global Investor"]
    assert fsb["notes"] == ["Most countries are unprepared for bank failures, the watchdog warns."]
    assert fsb["top_rank"] == 1
    assert fsb["implication"] == "Bank funding spreads widen first where there is no backstop."

    harrison = stories["Ed Harrison: the pace, not the level, is what breaks things"]
    assert harrison["source"] == "Bloomberg (Ed Harrison)"
    assert harrison["url"] is None
    assert harrison["multi_signal"] is False
    assert harrison["tags"] == ["yield_curve", "regime_shift"]
    assert harrison["confidence"] == pytest.approx(0.65)
    assert harrison["top_rank"] is None
    assert harrison["implication"] == "Fast repricing forces de-risking before fundamentals change."

    apple = stories["Apple cuts iPhone 18 Pro orders on soft demand"]
    assert apple["url"] == "https://asia.nikkei.com/apple"
    assert apple["tags"] == ["leading_retail", "industry_demand_signal"]
    assert apple["top_rank"] == 2

    assert [(item["rank"], item["story_id"]) for item in parsed["top_stories"]] == [
        (1, fsb["id"]),
        (2, apple["id"]),
    ]


def test_parse_legacy_digest_still_yields_plain_stories():
    legacy = """# Newsletter Digest - May 1, 2026

## liquidity_path

- [MULTI-SIGNAL] Japan launches FX intervention - (Bloomberg) - [body content]
  - *Coordinated dollar-selling intervention.*
"""
    parsed = news_digests.parse_digest_markdown(legacy, filename="05012026_digest.md")

    (story,) = parsed["stories"]
    assert story["headline"] == "Japan launches FX intervention"
    assert story["source"] == "Bloomberg"
    assert story["multi_signal"] is True
    assert story["notes"] == ["Coordinated dollar-selling intervention."]
    assert story["confidence"] is None


def test_report_context_keeps_top_and_multi_signal_stories_first(monkeypatch, tmp_path):
    digests = _isolate_news_digest_store(monkeypatch, tmp_path)
    monkeypatch.setattr("ontology.domain_write_service.assert_domain_table_write_allowed", lambda _name: None)
    digests.save_digest(PIPELINE_DIGEST, filename="10102026_digest.md")

    from datetime import UTC, datetime

    context = digests.get_report_context(days=3, now=datetime(2026, 10, 11, tzinfo=UTC), max_stories=2)

    kept = [story for section in context["digests"][0]["sections"] for story in section["stories"]]
    assert [story["headline"] for story in kept] == [
        "FSB: only four jurisdictions have a credible backstop for failing banks",
        "Apple cuts iPhone 18 Pro orders on soft demand",
    ]
    assert kept[0]["source"] == "FT Markets Afternoon Briefing"
    assert all(str(story["id"]).startswith("story-") for story in kept)
    assert kept[0]["top_rank"] == 1
    assert kept[0]["implication"] == "Bank funding spreads widen first where there is no backstop."


@pytest.fixture
def sync_store(monkeypatch, tmp_path):
    digests = _isolate_news_digest_store(monkeypatch, tmp_path)
    monkeypatch.setattr("api.routers.portfolio_news._index_digest_best_effort", lambda _detail: None)
    monkeypatch.setattr("api.routers.portfolio_news._delete_digest_index_best_effort", lambda _digest_id: None)
    repo = NormalizingTemporalRepo()
    monkeypatch.setattr(
        "ontology.command_service.OntologyCommandService",
        lambda: OntologyCommandService(OntologyObjectService(repository=repo)),  # type: ignore[arg-type]
    )
    monkeypatch.setenv("NEWS_DIGEST_SYNC_SECRET", "digest-secret")
    return digests


def _upload(client, secret="digest-secret", content=PIPELINE_DIGEST):
    return client.post(
        "/api/news-digest-sync",
        headers={"X-News-Digest-Sync-Secret": secret},
        files={"file": ("10102026_digest.md", content.encode("utf-8"), "text/markdown")},
    )


def test_sync_publishes_digest_immediately_and_is_idempotent(client, sync_store):
    first = _upload(client)
    second = _upload(client)

    assert first.status_code == 200, first.text
    assert first.json()["status"] == "published"
    assert first.json()["story_count"] == 3
    assert second.json() == {**first.json(), "status": "unchanged"}
    listed = sync_store.list_digests()
    assert listed["counts"] == {"digests": 1, "stories": 3}


def test_sync_lists_and_deletes_digests(client, sync_store):
    digest_id = _upload(client).json()["id"]
    headers = {"X-News-Digest-Sync-Secret": "digest-secret"}

    listed = client.get("/api/news-digest-sync", headers=headers)
    deleted = client.delete(f"/api/news-digest-sync/{digest_id}", headers=headers)

    assert [item["id"] for item in listed.json()["items"]] == [digest_id]
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"status": "applied", "id": digest_id}
    assert sync_store.list_digest_summaries() == []


def test_sync_rejects_wrong_or_missing_secret(client, sync_store):
    assert _upload(client, secret="wrong").status_code == 401
    assert client.get("/api/news-digest-sync").status_code == 401
    assert sync_store.list_digest_summaries() == []


def test_sync_is_unavailable_without_configured_secret(client, sync_store, monkeypatch):
    monkeypatch.delenv("NEWS_DIGEST_SYNC_SECRET")

    response = client.get("/api/news-digest-sync", headers={"X-News-Digest-Sync-Secret": "digest-secret"})

    assert response.status_code == 503
