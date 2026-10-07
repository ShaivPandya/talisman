"""Offline, evidence-anchored evaluation of original extraction responses (LON-18)."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from scipy.optimize import linear_sum_assignment

from longaeva_app.extract.llm import locate_quote
from longaeva_app.extract.schemas import ExtractedObservation, ExtractionResponse
from longaeva_app.hashing import content_hash, sha256_hex

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "data/fixtures/extraction_eval"
SUITE_VERSION = "lon18-v1"
NUMERIC_TOLERANCE = 1e-6
FIELD_GROUPS = {
    "value_range": ("value", "range_low", "range_high"),
    "statement_type": ("statement_type",),
    "activity_scope": ("activity_type",),
    "unit_basis": ("unit", "basis"),
    "period": ("period_start", "period_end"),
    "geography": ("geography",),
}
ERROR_TYPES = ("omission", "unsupported", "duplicate", "invalid_quote", *FIELD_GROUPS)


class Span(BaseModel):
    char_start: int
    char_end: int


class SourceReference(BaseModel):
    company: str
    family: str
    url: str
    path: str
    content_sha256: str
    publication_ts: str
    doc_type: str


class EvalPassage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source: SourceReference
    page: int
    char_start: int
    char_end: int
    text: str
    text_sha256: str
    period_start: str
    period_end: str
    exclusion_rationale: str | None = None


class GoldLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    passage_id: str
    expected: ExtractedObservation
    span: Span
    anchor_span: Span
    categories: list[str]
    rationale: str
    accepted: dict[str, list[str]]
    disputed: bool = False


def load_corpus(gold_path: Path, passages_path: Path) -> tuple[list[GoldLabel], list[EvalPassage]]:
    gold = [GoldLabel.model_validate(json.loads(line)) for line in gold_path.read_text().splitlines() if line.strip()]
    passages = [
        EvalPassage.model_validate(json.loads(line)) for line in passages_path.read_text().splitlines() if line.strip()
    ]
    if len({p.id for p in passages}) != len(passages) or len({g.id for g in gold}) != len(gold):
        raise ValueError("Duplicate passage or label ID")
    by_id = {p.id: p for p in passages}
    for p in passages:
        if p.text_sha256 != sha256_hex(p.text) or p.char_end - p.char_start != len(p.text):
            raise ValueError(f"Passage text/span hash mismatch: {p.id}")
    for g in gold:
        label_passage = by_id.get(g.passage_id)
        if label_passage is None:
            raise ValueError(f"Unknown passage: {g.passage_id}")
        if not (0 <= g.span.char_start < g.span.char_end <= len(label_passage.text)):
            raise ValueError(f"Invalid gold span: {g.id}")
        if label_passage.text[g.span.char_start : g.span.char_end] != g.expected.quote:
            raise ValueError(f"Gold quote is not at its recorded span: {g.id}")
        if not (g.span.char_start <= g.anchor_span.char_start < g.anchor_span.char_end <= g.span.char_end):
            raise ValueError(f"Invalid anchor span: {g.id}")
        for field in ("value", "range_low", "range_high"):
            value = getattr(g.expected, field)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"Non-finite gold value: {g.id}")
        if set(g.accepted) - set(ExtractedObservation.model_fields):
            raise ValueError(f"Unknown alias field: {g.id}")
    return gold, passages


def load_review(path: Path, gold_path: Path) -> dict[str, Any]:
    review: dict[str, Any] = json.loads(path.read_text())
    if review.get("gold_sha256") != sha256_hex(gold_path.read_bytes()):
        raise ValueError("Review belongs to a different gold file")
    return review


def require_reviewed(review: dict[str, Any], gold: list[GoldLabel]) -> None:
    selected = review.get("selected_label_ids", [])
    decisions = review.get("decisions", [])
    if (
        review.get("status") != "reviewed"
        or len(selected) != 10
        or len(set(selected)) != 10
        or not set(selected).issubset({g.id for g in gold})
        or {d.get("label_id") for d in decisions if d.get("decision") in {"accept", "correct"}} != set(selected)
        or not review.get("reviewer")
    ):
        raise ValueError("Capture requires the user's completed 10-label review")


def corpus_hash(gold: list[GoldLabel], passages: list[EvalPassage]) -> str:
    return content_hash(
        {"gold": [g.model_dump(mode="json") for g in gold], "passages": [p.model_dump() for p in passages]}
    )


def _equal(g: GoldLabel, field: str, actual: Any) -> bool:
    expected = getattr(g.expected, field)
    if expected is None or actual is None:
        return expected is actual
    if field in {"value", "range_low", "range_high"}:
        return math.isfinite(float(actual)) and math.isclose(
            float(expected), float(actual), rel_tol=0, abs_tol=NUMERIC_TOLERANCE
        )
    # No automatic unit conversion, sign changes, fiscal-period shifting, or fuzzy aliases.
    return str(actual) in {str(expected), *g.accepted.get(field, [])}


def field_errors(g: GoldLabel, prediction: ExtractedObservation) -> list[str]:
    return [
        name for name, fields in FIELD_GROUPS.items() if any(not _equal(g, f, getattr(prediction, f)) for f in fields)
    ]


def _quote_spans(text: str, quote: str) -> list[tuple[int, int]]:
    spans = []
    offset = 0
    while offset < len(text):
        found = locate_quote(text[offset:], quote)
        if found is None:
            break
        start, end = found[0] + offset, found[1] + offset
        spans.append((start, end))
        offset = start + 1
    return spans


def _anchored(g: GoldLabel, spans: list[tuple[int, int]]) -> bool:
    return any(start <= g.anchor_span.char_start and end >= g.anchor_span.char_end for start, end in spans)


def _rates(errors: dict[str, int], denominators: dict[str, int]) -> dict[str, dict[str, int | float | None]]:
    return {
        k: {
            "errors": errors.get(k, 0),
            "denominator": denominators.get(k, 0),
            "rate": errors.get(k, 0) / denominators[k] if denominators.get(k, 0) else None,
        }
        for k in ERROR_TYPES
    }


def score_extractions(
    gold: list[GoldLabel],
    passages: list[EvalPassage],
    cached: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    """Score parsed provider responses, never corrected observation rows. No I/O."""
    digest = corpus_hash(gold, passages)
    if cached.get("corpus_hash") not in {None, digest}:
        raise ValueError("Cached outputs belong to a different corpus")
    calls = cached.get("calls", [])
    if not isinstance(calls, list):
        raise ValueError("Expected a list of cached calls")
    by_call: dict[str, dict[str, Any]] = {}
    for call in calls:
        if call["passage_id"] in by_call or call["passage_id"] not in {p.id for p in passages}:
            raise ValueError("Duplicate or unknown cached passage ID")
        by_call[call["passage_id"]] = call
    labels: dict[str, list[GoldLabel]] = defaultdict(list)
    for g in gold:
        labels[g.passage_id].append(g)
    errors: dict[str, int] = defaultdict(int)
    denominators: dict[str, int] = defaultdict(int)
    group_errors: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    group_denoms: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    details: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    counts = dict(
        total_passages=len(passages),
        succeeded_passages=0,
        failed_passages=0,
        missing_passages=0,
        total_labels=len(gold),
        disputed_labels=sum(g.disputed for g in gold),
        scored_labels=0,
        unavailable_labels=0,
        matched_labels=0,
        correct_labels=0,
        predictions=0,
    )

    def add_error(name: str, keys: list[str]) -> None:
        errors[name] += 1
        for key in keys:
            group_errors[key][name] += 1

    def add_denom(name: str, keys: list[str]) -> None:
        denominators[name] += 1
        for key in keys:
            group_denoms[key][name] += 1

    for p in passages:
        family = f"family:{p.source.family}"
        call = by_call.get(p.id)
        eligible = sorted((g for g in labels[p.id] if not g.disputed), key=lambda g: g.id)
        all_categories = sorted({c for g in labels[p.id] for c in g.categories})
        passage_keys = [family, *(f"category:{c}" for c in all_categories)]
        status = str(call.get("status")) if call else "missing"
        parsed = None
        if status == "succeeded" and call:
            try:
                parsed = ExtractionResponse.model_validate(call.get("parsed"))
            except ValidationError:
                status = "invalid_response"
        if parsed is None:
            counts["missing_passages" if status == "missing" else "failed_passages"] += 1
            counts["unavailable_labels"] += len(eligible)
            failures.append(
                {
                    "passage_id": p.id,
                    "family": p.source.family,
                    "status": status,
                    "error": call.get("error") if call else None,
                }
            )
            continue
        counts["succeeded_passages"] += 1
        counts["scored_labels"] += len(eligible)
        predictions = parsed.observations
        counts["predictions"] += len(predictions)
        spans = [_quote_spans(p.text, pred.quote) for pred in predictions]
        # Evidence and activity identify the fact. Field comparisons only break ties
        # when a broad quote supports multiple facts; every disagreement is still scored.
        candidates: dict[tuple[int, int], int] = {}
        for gi, g in enumerate(eligible):
            for pi, pred in enumerate(predictions):
                if _anchored(g, spans[pi]):
                    candidates[(gi, pi)] = 100 * int(not _equal(g, "activity_type", pred.activity_type)) + len(
                        field_errors(g, pred)
                    )
        used_g: set[int] = set()
        used_p: set[int] = set()
        matched: dict[int, int] = {}
        if eligible and predictions:
            # Dummy columns allow omissions. Matching an anchored observation is
            # always cheaper; optimize the complete assignment, avoiding greedy
            # omissions when one broad quote can match several facts.
            order = sorted(
                range(len(predictions)), key=lambda i: (content_hash(predictions[i].model_dump(mode="json")), i)
            )
            matrix = [
                [candidates.get((gi, pi), 100_000) for pi in order] + [10_000] * len(eligible)
                for gi in range(len(eligible))
            ]
            gold_indices, prediction_indices = linear_sum_assignment(matrix)
            for gi_raw, column_raw in zip(gold_indices, prediction_indices, strict=True):
                gi, column = int(gi_raw), int(column_raw)
                if column < len(order) and (gi, order[column]) in candidates:
                    pi = order[column]
                    used_g.add(gi)
                    used_p.add(pi)
                    matched[gi] = pi
        for gi, g in enumerate(eligible):
            keys = [family, *(f"category:{c}" for c in g.categories)]
            add_denom("omission", keys)
            matched_pi = matched.get(gi)
            problems = ["omission"] if matched_pi is None else field_errors(g, predictions[matched_pi])
            if matched_pi is not None:
                counts["matched_labels"] += 1
                counts["correct_labels"] += not problems
                for name in FIELD_GROUPS:
                    add_denom(name, keys)
            for problem in problems:
                add_error(problem, keys)
            if problems:
                details.append(
                    {
                        "label_id": g.id,
                        "passage_id": p.id,
                        "company": p.source.company,
                        "family": p.source.family,
                        "categories": g.categories,
                        "errors": problems,
                        "expected": g.expected.model_dump(mode="json"),
                        "actual": predictions[matched_pi].model_dump(mode="json") if matched_pi is not None else None,
                        "source_url": p.source.url,
                        "page": p.page,
                        "rationale": g.rationale,
                    }
                )
        for pi, pred in enumerate(predictions):
            # An explicitly disputed label is neither right nor wrong; keep its count visible.
            disputed_only = (
                pi not in used_p
                and any(
                    _anchored(g, spans[pi]) and _equal(g, "activity_type", pred.activity_type)
                    for g in labels[p.id]
                    if g.disputed
                )
                and not any(
                    _anchored(g, spans[pi]) and _equal(g, "activity_type", pred.activity_type) for g in eligible
                )
            )
            if disputed_only:
                continue
            for name in ("unsupported", "duplicate", "invalid_quote"):
                add_denom(name, passage_keys)
            if pi in used_p:
                continue
            problems = []
            if not spans[pi]:
                problems.append("invalid_quote")
            same_fact = any(
                _anchored(g, spans[pi]) and _equal(g, "activity_type", pred.activity_type) for g in eligible
            )
            problems.append("duplicate" if same_fact else "unsupported")
            for problem in problems:
                add_error(problem, passage_keys)
            details.append(
                {
                    "label_id": None,
                    "passage_id": p.id,
                    "company": p.source.company,
                    "family": p.source.family,
                    "categories": all_categories,
                    "errors": problems,
                    "expected": None,
                    "actual": pred.model_dump(mode="json"),
                    "source_url": p.source.url,
                    "page": p.page,
                    "rationale": "Unmatched original prediction.",
                }
            )
    groups = sorted(
        set(group_denoms)
        | {f"family:{p.source.family}" for p in passages}
        | {f"category:{c}" for g in gold for c in g.categories}
    )
    report = {
        "suite_version": SUITE_VERSION,
        "corpus_hash": digest,
        "provider": cached.get("provider", "openai"),
        "model": cached.get("model", "gpt-5.4"),
        "prompt_version": cached.get("prompt_version", "lon16-v1"),
        "numeric_tolerance": NUMERIC_TOLERANCE,
        "coverage": counts,
        "review": {
            "status": review.get("status", "pending"),
            "author": review.get("author", "Codex (AI assistant)"),
            "reviewer": review.get("reviewer"),
            "reviewed_labels": len(review.get("decisions", [])),
            "selected_label_ids": review.get("selected_label_ids", []),
            "decisions": review.get("decisions", []),
        },
        "errors": _rates(errors, denominators),
        "by_family": {
            k.removeprefix("family:"): _rates(group_errors[k], group_denoms[k])
            for k in groups
            if k.startswith("family:")
        },
        "by_category": {
            k.removeprefix("category:"): _rates(group_errors[k], group_denoms[k])
            for k in groups
            if k.startswith("category:")
        },
        "failures": failures,
        "disagreements": details,
        "calls": [{k: v for k, v in call.items() if k not in {"parsed", "response_text"}} for call in calls],
        "limitations": [
            "Assistant-curated sample; human review covers the selected ten labels, not the entire corpus.",
            "Short purposively selected passages are not a random sample of filing extraction quality.",
            "Contradictions include revisions and opposing or apparently conflicting figures resolved by scope or period.",
            "Rates for semantic fields use matched labels; omissions use labels in successful passages. Unavailable labels remain in coverage.",
            "Prediction errors by category inherit all tags of the passage; categories overlap and must not be summed.",
            "Fiscal-period defaults, uncertainty margins, and semantic aliases follow the documented labeling guide.",
            "These extraction errors are separate from forecast errors and do not establish predictive performance.",
        ],
    }
    report["content_hash"] = content_hash(report)
    return report


def report_markdown(report: dict[str, Any]) -> str:
    c = report["coverage"]
    lines = [
        "# Extraction error sample (LON-18)",
        "",
        f"Provider: {report['provider']} / {report['model']}; prompt: {report['prompt_version']}.",
        f"Review: {report['review']['status']}; {report['review']['reviewed_labels']} of {c['total_labels']} labels reviewed by the user.",
        f"Passages: {c['succeeded_passages']} succeeded, {c['failed_passages']} failed, {c['missing_passages']} missing of {c['total_passages']}.",
        f"Labels: {c['correct_labels']} exact matches, {c['matched_labels']} matched, {c['scored_labels']} scorable; {c['unavailable_labels']} unavailable, {c['disputed_labels']} disputed.",
        "",
    ]
    for title, rows in [
        ("Overall", report["errors"]),
        *[(f"Family: {k}", v) for k, v in report["by_family"].items()],
        *[(f"Category: {k}", v) for k, v in report["by_category"].items()],
    ]:
        lines += [f"## {title}", "", "| Error | Count | Denominator | Rate |", "| --- | ---: | ---: | ---: |"]
        for name, row in rows.items():
            rate = f"{100 * row['rate']:.1f}%" if row["rate"] is not None else "not scored"
            lines.append(f"| {name} | {row['errors']} | {row['denominator']} | {rate} |")
        lines.append("")
    lines += [
        "## Call failures and missing outputs",
        "",
        *[
            f"- {f['passage_id']}: {f['status']}" + (f" — {f['error']}" if f.get("error") else "")
            for f in report["failures"]
        ],
        "",
        "## Disagreements",
        "",
    ]
    for d in report["disagreements"]:
        lines += [
            f"### {d['label_id'] or d['passage_id']}: {', '.join(d['errors'])}",
            "",
            f"[Original source, page {d['page']}]({d['source_url']})",
            "",
            "```json",
            json.dumps({"expected": d["expected"], "actual": d["actual"]}, indent=2, ensure_ascii=False),
            "```",
            "",
            d["rationale"],
            "",
        ]
    lines += [
        "## Limitations",
        "",
        *[f"- {s}" for s in report["limitations"]],
        "",
        f"Corpus hash: `{report['corpus_hash']}`",
        f"Report hash: `{report['content_hash']}`",
        "",
    ]
    return "\n".join(lines)


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    output.with_suffix(".md").write_text(report_markdown(report))
