"""source provenance, evidence assignment, denominators, and capture bounds."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from longaeva_app.collect.text import _HtmlPageSplitter, extract_pdf_passages
from longaeva_app.config import Settings
from longaeva_app.db.models import ExtractionCall, Observation, ParameterSet
from longaeva_app.evaluation.extraction_capture import capture_extractions
from longaeva_app.evaluation.extraction_scoring import (
    FIXTURE_DIR,
    EvalPassage,
    GoldLabel,
    corpus_hash,
    load_corpus,
    load_review,
    report_markdown,
    score_extractions,
)
from longaeva_app.extract.providers import ProviderError, ProviderResult, StubProvider
from longaeva_app.hashing import sha256_hex


def _sample() -> tuple[list[GoldLabel], list[EvalPassage]]:
    gold, passages = load_corpus(FIXTURE_DIR / "gold.jsonl", FIXTURE_DIR / "passages.jsonl")
    return [next(g for g in gold if g.id == "visa-lag-01")], [next(p for p in passages if p.id == "visa-lag")]


def _cached(passage: EvalPassage, predictions: list[dict[str, Any]]) -> dict[str, Any]:
    return {"calls": [{"passage_id": passage.id, "status": "succeeded", "parsed": {"observations": predictions}}]}


def _review(gold: list[GoldLabel]) -> dict[str, Any]:
    return {
        "status": "reviewed",
        "reviewer": "user",
        "author": "Codex (AI assistant)",
        "selected_label_ids": [g.id for g in gold[:10]],
        "decisions": [{"label_id": g.id, "decision": "accept"} for g in gold[:10]],
    }


def test_corpus_has_every_family_category_and_original_source_span() -> None:
    gold, passages = load_corpus(FIXTURE_DIR / "gold.jsonl", FIXTURE_DIR / "passages.jsonl")
    assert len(gold) >= 40 and len(passages) <= 20
    assert {p.source.company for p in passages} == {"visa", "booking", "census", "united", "costco", "paypal"}
    assert {"numeric", "qualitative", "contradiction", "period", "unit", "geography"} <= {
        c for g in gold for c in g.categories
    }
    root = FIXTURE_DIR.parents[2]
    source_pages: dict[str, list[str]] = {}
    for p in passages:
        raw = (root / p.source.path).read_bytes()
        if p.source.path.endswith(".gz"):
            raw = gzip.decompress(raw)
        assert sha256_hex(raw) == p.source.content_sha256
        if p.source.path not in source_pages:
            source_pages[p.source.path] = (
                _HtmlPageSplitter().split(raw.decode())
                if p.source.path.endswith(".gz")
                else [q.text for q in extract_pdf_passages(raw)]
            )
        assert source_pages[p.source.path][p.page - 1][p.char_start : p.char_end] == p.text
    review = load_review(FIXTURE_DIR / "review.json", FIXTURE_DIR / "gold.jsonl")
    assert len(review["selected_label_ids"]) == 10
    assert len(set(review["selected_label_ids"])) == 10
    costco = next(g for g in gold if g.id == "costco-comparables-01")
    assert str(costco.expected.period_start) == "2025-05-12"  # 16 weeks, not the previous 12-week fixture


def test_value_period_and_aliases_do_not_hide_errors() -> None:
    gold, passages = _sample()
    expected = gold[0].expected.model_dump(mode="json")
    prediction = {
        **expected,
        "value": 7,
        "period_start": "2024-04-01",
        "period_end": "2024-06-30",
        "activity_type": "payments_volume_growth",
        "basis": "constant_dollar",
    }
    report = score_extractions(gold, passages, _cached(passages[0], [prediction]), {})
    assert report["coverage"]["matched_labels"] == 1
    assert report["errors"]["value_range"]["errors"] == 1
    assert report["errors"]["period"]["errors"] == 1
    assert report["errors"]["activity_scope"]["errors"] == report["errors"]["unit_basis"]["errors"] == 0
    assert report["errors"]["omission"]["errors"] == 0


def test_duplicate_unsupported_and_invalid_quote_are_distinct() -> None:
    gold, passages = _sample()
    good = gold[0].expected.model_dump(mode="json")
    unsupported = {**good, "quote": "Invented result not in this document", "activity_type": "invented"}
    report = score_extractions(gold, passages, _cached(passages[0], [good, good, unsupported]), {})
    assert report["coverage"]["correct_labels"] == 1
    assert report["errors"]["duplicate"] == {"errors": 1, "denominator": 3, "rate": 1 / 3}
    assert report["errors"]["unsupported"]["errors"] == 1
    assert report["errors"]["invalid_quote"]["errors"] == 1


def test_global_assignment_does_not_omit_narrow_quote_after_broad_quote() -> None:
    all_gold, all_passages = load_corpus(FIXTURE_DIR / "gold.jsonl", FIXTURE_DIR / "passages.jsonl")
    gold = [g for g in all_gold if g.id in {"visa-lag-01", "visa-lag-02"}]
    p = next(p for p in all_passages if p.id == "visa-lag")
    broad = {**gold[0].expected.model_dump(mode="json"), "quote": p.text}
    narrow = gold[0].expected.model_dump(mode="json")
    report = score_extractions(gold, [p], _cached(p, [broad, narrow]), {})
    assert report["coverage"]["matched_labels"] == 2
    assert report["errors"]["omission"]["errors"] == 0
    assert report["errors"]["period"]["errors"] == 1
    assert report["errors"]["value_range"]["errors"] == 1


def test_ranges_qualitative_nulls_and_wrong_fields() -> None:
    all_gold, all_passages = load_corpus(FIXTURE_DIR / "gold.jsonl", FIXTURE_DIR / "passages.jsonl")
    g = next(g for g in all_gold if g.id == "booking-outlook-01")
    p = next(p for p in all_passages if p.id == g.passage_id)
    actual = {
        **g.expected.model_dump(mode="json"),
        "statement_type": "measured",
        "range_high": 9,
        "unit": "usd",
        "geography": "Europe",
        "activity_type": "gross_bookings",
    }
    report = score_extractions([g], [p], _cached(p, [actual]), {})
    assert report["disagreements"][0]["errors"] == [
        "value_range",
        "statement_type",
        "activity_scope",
        "unit_basis",
        "geography",
    ]
    g = next(g for g in all_gold if g.id == "visa-stable-01")
    p = next(p for p in all_passages if p.id == g.passage_id)
    actual = {**g.expected.model_dump(mode="json"), "quote": g.expected.quote.replace(" ", "\n")}
    report = score_extractions([g], [p], _cached(p, [actual]), {})
    assert report["coverage"]["correct_labels"] == 1
    assert report["errors"]["invalid_quote"]["errors"] == 0


@pytest.mark.parametrize(
    "calls",
    [
        [],
        [{"passage_id": "visa-lag", "status": "provider_error"}],
        [{"passage_id": "visa-lag", "status": "succeeded", "parsed": {"observations": [{"confidence": 0.9}]}}],
    ],
)
def test_failed_missing_and_malformed_outputs_never_become_zero_errors(calls: list[dict[str, Any]]) -> None:
    gold, passages = _sample()
    report = score_extractions(gold, passages, {"calls": calls}, {})
    assert report["coverage"]["unavailable_labels"] == 1
    assert report["coverage"]["scored_labels"] == 0
    assert report["errors"]["value_range"]["rate"] is None
    assert len(report["failures"]) == 1
    assert "not scored" in report_markdown(report)


def test_omissions_disputes_empty_outputs_and_determinism() -> None:
    gold, passages = _sample()
    cached = _cached(passages[0], [])
    a = score_extractions(gold, passages, cached, {})
    assert a["errors"]["omission"] == {"errors": 1, "denominator": 1, "rate": 1}
    assert a == score_extractions(gold, passages, cached, {})
    gold[0].disputed = True
    b = score_extractions(gold, passages, cached, {})
    assert b["coverage"]["disputed_labels"] == 1
    assert b["errors"]["omission"]["denominator"] == 0
    empty = score_extractions([], [], {"calls": []}, {})
    assert all(r["rate"] is None for r in empty["errors"].values())
    with pytest.raises(ValueError, match="different corpus"):
        score_extractions(gold, passages, {"corpus_hash": "wrong", "calls": []}, {})


def test_disputed_anchor_does_not_hide_an_unsupported_activity() -> None:
    gold, passages = _sample()
    gold[0].disputed = True
    good = gold[0].expected.model_dump(mode="json")
    unsupported = {**good, "activity_type": "invented"}
    report = score_extractions(gold, passages, _cached(passages[0], [good, unsupported]), {})
    assert report["errors"]["omission"]["denominator"] == 0
    assert report["errors"]["unsupported"] == {"errors": 1, "denominator": 1, "rate": 1}


@pytest.mark.db
def test_capture_resumes_after_interruption_without_repeating_failed_calls(db_session: Session, tmp_path: Path) -> None:
    class InterruptedProvider(StubProvider):
        def complete(self, *, system: str, user: str) -> ProviderResult:
            self.calls += 1
            if self.calls == 1:
                raise ProviderError("Temporary provider failure", attempts=2, status_code=503)
            raise RuntimeError("Simulated interruption")

    gold, passages = load_corpus(FIXTURE_DIR / "gold.jsonl", FIXTURE_DIR / "passages.jsonl")
    passages = passages[:2]
    reviewed = _review(gold)
    settings = Settings(llm_provider="stub")
    output = tmp_path / "cached.json"
    interrupted = InterruptedProvider()
    with pytest.raises(RuntimeError, match="Simulated interruption"):
        capture_extractions(
            db_session,
            gold=gold,
            passages=passages,
            review=reviewed,
            provider=interrupted,
            settings=settings,
            output=output,
        )
    first = json.loads(output.read_text())
    assert len(first["calls"]) == 1
    assert first["calls"][0]["error"] == "Temporary provider failure"
    assert first["calls"][0]["attempts"] == 2
    resumed = StubProvider()
    result = capture_extractions(
        db_session,
        gold=gold,
        passages=passages,
        review=reviewed,
        provider=resumed,
        settings=settings,
        output=output,
    )
    assert resumed.calls == 1
    assert result["calls"][0] == first["calls"][0]
    assert db_session.scalar(select(func.count()).select_from(ExtractionCall)) == 2
    report = score_extractions(gold, passages, result, reviewed)
    assert report["failures"][0]["error"] == "Temporary provider failure"
    assert "Temporary provider failure" in report_markdown(report)
    before = output.read_bytes()
    capture_extractions(
        db_session,
        gold=gold,
        passages=passages,
        review=reviewed,
        provider=resumed,
        settings=settings,
        output=output,
    )
    assert resumed.calls == 1 and output.read_bytes() == before
    result["calls"][1]["prompt_hash"] = "wrong"
    output.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="Checkpoint prompt mismatch"):
        capture_extractions(
            db_session,
            gold=gold,
            passages=passages,
            review=reviewed,
            provider=resumed,
            settings=settings,
            output=output,
        )
    assert resumed.calls == 1


@pytest.mark.db
def test_capture_is_bounded_cached_and_does_not_create_observations(db_session: Session, tmp_path: Path) -> None:
    gold, passages = load_corpus(FIXTURE_DIR / "gold.jsonl", FIXTURE_DIR / "passages.jsonl")
    reviewed = _review(gold)
    stub = StubProvider(responses=['{"observations": []}'])
    settings = Settings(llm_provider="stub")
    output = tmp_path / "cached.json"
    with pytest.raises(ValueError, match="completed 10-label"):
        capture_extractions(
            db_session, gold=gold, passages=passages, review={}, provider=stub, settings=settings, output=output
        )
    assert stub.calls == 0
    with pytest.raises(ValueError, match="20 unique"):
        capture_extractions(
            db_session,
            gold=gold,
            passages=passages + passages[:2],
            review=reviewed,
            provider=stub,
            settings=settings,
            output=output,
        )
    assert stub.calls == 0
    before = [db_session.scalar(select(func.count()).select_from(m)) for m in (Observation, ParameterSet)]
    first = capture_extractions(
        db_session, gold=gold, passages=passages[:1], review=reviewed, provider=stub, settings=settings, output=output
    )
    assert first["corpus_hash"] == corpus_hash(gold, passages[:1])
    assert stub.calls == 1
    second = capture_extractions(
        db_session,
        gold=gold,
        passages=passages[:1],
        review=reviewed,
        provider=stub,
        settings=settings,
        output=tmp_path / "again.json",
    )
    assert stub.calls == 1
    assert second["calls"][0]["cache_hit"] is True
    assert first["calls"][0]["parsed"] == second["calls"][0]["parsed"] == {"observations": []}
    assert db_session.scalar(select(func.count()).select_from(ExtractionCall)) == 1
    assert before == [db_session.scalar(select(func.count()).select_from(m)) for m in (Observation, ParameterSet)]
