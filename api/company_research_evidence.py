"""Typed research evidence, fiscal coverage checks, and lossless report tables."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any, Literal
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlsplit, urlunsplit

from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.name_documents import PRIVATE_URL


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(EvidenceModel):
    url: str
    title: str
    published_on: date | None
    passage: str
    location: str


def fiscal_label(value: Any) -> Any:
    """Accept "Q1 FY2026" for the canonical "FY2026 Q1" fiscal quarter label."""
    if isinstance(value, str):
        match = re.fullmatch(r"Q([1-4])\s+FY(20\d{2})", value.strip(), re.IGNORECASE)
        if match:
            return f"FY{match[2]} Q{match[1]}"
    return value


class Quarter(EvidenceModel):
    label: str = Field(pattern=r"^FY20\d{2} Q[1-4]$")
    ended_on: date
    reported_on: date
    source: Source

    normalize_label = field_validator("label", mode="before")(fiscal_label)


class Topic(EvidenceModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,99}$")
    title: str
    requirements: str
    sections: list[str]


class ResearchPlan(EvidenceModel):
    issuer: str
    fiscal_calendar: str
    quarters: list[Quarter]
    overview_topics: list[Topic]
    management_sections: list[str]


class Commitment(EvidenceModel):
    record_id: str
    quarter: str
    initiative: str
    claim: str
    category: str
    original_target: str
    later_evidence: str
    outcome: Literal[
        "Achieved on time",
        "Achieved late",
        "Partially achieved",
        "Missed",
        "Over budget",
        "Under budget",
        "Re-scoped",
        "Abandoned",
        "Not yet measurable",
        "Insufficient disclosure",
    ]
    variance: str
    explanation: str
    independent_verification: str
    control: str
    acknowledgement: str
    corrective_action: str
    response_time: str
    fix_result: str
    claim_sources: list[Source] = Field(min_length=1)
    outcome_sources: list[Source]

    normalize_quarter = field_validator("quarter", mode="before")(fiscal_label)


class QuarterReview(EvidenceModel):
    quarter: str
    coverage: Literal["researched", "source_unavailable"]
    search_attempts: list[str] = Field(min_length=1)
    sources: list[Source]
    gap: str | None
    records: list[Commitment]

    normalize_quarter = field_validator("quarter", mode="before")(fiscal_label)


class QuarterPacket(EvidenceModel):
    quarters: list[QuarterReview]


def merge_quarter_repair(original: QuarterPacket, repair: QuarterPacket) -> QuarterPacket:
    """Apply a partial repair by stable IDs without discarding untouched quarters."""
    before = {q.quarter: q for q in original.quarters}
    labels = [q.quarter for q in repair.quarters]
    partial_records = any(
        q.quarter in before
        and {r.record_id for r in q.records} < {r.record_id for r in before[q.quarter].records}
        and q.coverage != "source_unavailable"
        for q in repair.quarters
    )
    if len(labels) >= len(before) and not partial_records:
        return repair  # Complete replacements still undergo the ordinary full validation.
    if len(labels) != len(set(labels)) or not set(labels).issubset(before):
        raise ValueError("A partial quarter repair must identify existing quarters exactly once.")
    updates = {}
    for quarter in repair.quarters:
        old = before[quarter.quarter]
        records = {r.record_id: r for r in old.records}
        ids = [r.record_id for r in quarter.records]
        if len(ids) != len(set(ids)) or not set(ids).issubset(records):
            raise ValueError("A partial quarter repair must preserve the original record IDs.")
        if quarter.coverage == "source_unavailable":
            # An explicit unavailable-source finding is a complete quarter replacement.
            updates[quarter.quarter] = quarter
            continue
        records.update({r.record_id: r for r in quarter.records})
        sources = {s.model_dump_json(): s for s in [*old.sources, *quarter.sources]}
        updates[quarter.quarter] = quarter.model_copy(
            update={
                "records": list(records.values()),
                "sources": list(sources.values()),
                "search_attempts": list(dict.fromkeys([*old.search_attempts, *quarter.search_attempts])),
                "gap": "\n".join(dict.fromkeys(g for g in [old.gap, quarter.gap] if g)) or None,
            }
        )
    return QuarterPacket(quarters=[updates.get(q.quarter, q).model_copy(deep=True) for q in original.quarters])


class Fact(EvidenceModel):
    record_id: str
    section: str
    claim: str
    sources: list[Source] = Field(min_length=1)


class OverviewPacket(EvidenceModel):
    facts: list[Fact]
    gaps: list[str]
    searched_sources: list[Source]


def _confirmed(sources: list[Source], failed: set[str]) -> list[Source]:
    return [s for s in sources if canonical_source_url(s.url) not in failed]


def prune_overview_sources(packet: OverviewPacket, urls: set[str]) -> OverviewPacket:
    """Drop citations that failed their source check instead of discarding the whole topic."""
    failed = {canonical_source_url(url) for url in urls}
    facts, gaps = [], list(packet.gaps)
    for fact in packet.facts:
        if sources := _confirmed(fact.sources, failed):
            facts.append(fact.model_copy(update={"sources": sources}))
        else:
            cited = ", ".join(sorted({s.url for s in fact.sources})) or "no URL"
            gaps.append(f"{fact.section}: removed a claim whose only source could not be confirmed ({cited}).")
    return OverviewPacket(facts=facts, gaps=gaps, searched_sources=_confirmed(packet.searched_sources, failed))


def prune_quarter_sources(packet: QuarterPacket, urls: set[str]) -> QuarterPacket:
    """Drop unconfirmed citations; a promise without a confirmed source is removed, an outcome is unverified."""
    failed = {canonical_source_url(url) for url in urls}
    quarters = []
    for quarter in packet.quarters:
        notes, records = [], []
        for record in quarter.records:
            claim_sources = _confirmed(record.claim_sources, failed)
            if not claim_sources:
                notes.append(f"Removed the {record.initiative} commitment: its promise source could not be confirmed.")
                continue
            update: dict[str, Any] = {
                "claim_sources": claim_sources,
                "outcome_sources": _confirmed(record.outcome_sources, failed),
            }
            if (
                record.outcome_sources
                and not update["outcome_sources"]
                and record.outcome not in {"Not yet measurable", "Insufficient disclosure"}
            ):
                limitation = "The later-outcome source could not be confirmed, so the outcome is unverified."
                update.update(
                    outcome="Insufficient disclosure",
                    variance=limitation,
                    fix_result=limitation,
                    independent_verification=limitation,
                )
            records.append(record.model_copy(update=update))
        # Documents behind the retained records were reviewed even if the quarter-level citation failed.
        sources = _confirmed(quarter.sources, failed) or list(
            {s.model_dump_json(): s for r in records for s in r.claim_sources}.values()
        )
        gap = "\n".join(note for note in [quarter.gap, *notes] if note) or None
        quarters.append(quarter.model_copy(update={"records": records, "sources": sources, "gap": gap}))
    return QuarterPacket(quarters=quarters)


class Rejection(EvidenceModel):
    record_id: str
    reason: str


class CheckedCommitments(EvidenceModel):
    records: list[Commitment]
    rejected: list[Rejection]


class CheckedFacts(EvidenceModel):
    facts: list[Fact]
    rejected: list[Rejection]


class EvidenceCorrection(EvidenceModel):
    field: Literal[
        "initiative",
        "category",
        "later_evidence",
        "outcome",
        "variance",
        "explanation",
        "independent_verification",
        "control",
        "acknowledgement",
        "corrective_action",
        "response_time",
        "fix_result",
        "claim",
    ]
    value: str


class EvidenceDecision(EvidenceModel):
    record_id: str
    supported: bool
    reason: str
    # A rejection must name what is wrong with the record. A reviewer that only ran
    # out of lookups leaves this null, and the record keeps its gathered sources.
    rejection_basis: (
        Literal["contradicted_by_source", "not_supported_by_cited_passages", "impossible_dates_or_arithmetic"] | None
    ) = None
    corrections: list[EvidenceCorrection]
    replacement_sources: list[Source] | None


class EvidenceDecisions(EvidenceModel):
    decisions: list[EvidenceDecision]


def apply_decisions(
    original: list[Any],
    checked: EvidenceDecisions,
    *,
    management: bool,
    as_of: date,
    allow_unverified_outcomes: bool = False,
) -> tuple[list[Any], list[str]]:
    """Apply only explicit corrections; never regenerate or silently drop the original ledger."""
    validate_sources(checked, as_of=as_of)
    before = {r.record_id: r for r in original}
    ids = [d.record_id for d in checked.decisions]
    if len(set(ids)) != len(ids) or set(ids) != set(before):
        raise ValueError("Verification must account for every evidence record exactly once.")
    accepted: list[Any] = []
    rejected: list[str] = []
    excluded: list[EvidenceDecision] = []
    for decision in checked.decisions:
        old = before[decision.record_id]
        unchecked = False
        if not decision.supported:
            if not decision.reason.strip():
                raise ValueError("An evidence rejection needs a reason.")
            # Checkpoints from before rejection_basis existed keep their original rejection.
            if decision.rejection_basis is not None or "rejection_basis" not in decision.model_fields_set:
                rejected.append(f"{decision.record_id}: {decision.reason}")
                excluded.append(decision)
                continue
            # Not re-checked is not disproved: the record keeps its own tool-observed passages,
            # and an outcome whose chronology cannot be shown is marked unverified below.
            decision = decision.model_copy(update={"corrections": [], "replacement_sources": None})
            unchecked = True
        changes: dict[str, Any] = {c.field: c.value for c in decision.corrections}
        if len(changes) != len(decision.corrections):
            raise ValueError("Corrections must not repeat the same field.")
        if management and "claim" in changes:
            raise ValueError("Original management promises cannot be rewritten; reject unsupported originals.")
        if not management and any(key != "claim" for key in changes):
            raise ValueError("Overview corrections may only change the factual claim.")
        if decision.replacement_sources is not None:
            changes["outcome_sources" if management else "sources"] = decision.replacement_sources
        value = {**old.model_dump(), **changes}
        record = Commitment.model_validate(value) if management else Fact.model_validate(value)
        if (
            management
            and (allow_unverified_outcomes or unchecked)
            and record.outcome not in {"Not yet measurable", "Insufficient disclosure"}
        ):
            claim_dates = [s.published_on for s in record.claim_sources if s.published_on]
            outcome_dates = [s.published_on for s in record.outcome_sources if s.published_on]
            limitation = (
                "Outcome chronology is unverified because source publication dates are missing."
                if not claim_dates or not outcome_dates
                else "Outcome chronology is unverified because the outcome evidence predates the original promise."
                if min(outcome_dates) < min(claim_dates)
                else ""
            )
            if limitation:
                record.outcome = "Insufficient disclosure"
                record.variance = limitation
                record.fix_result = limitation
                record.independent_verification = limitation
                record.explanation = limitation + " " + record.explanation
                rejected.append(f"{record.record_id}: {limitation} Original commitment and sources retained.")
        accepted.append(record)
    if management:
        validate_reconciliation(
            original,
            CheckedCommitments(
                records=accepted,
                rejected=[Rejection(record_id=d.record_id, reason=d.reason) for d in excluded],
            ),
            as_of=as_of,
        )
    return accepted, rejected


class Section(EvidenceModel):
    title: str
    markdown: str
    evidence_ids: list[str]


class WrittenSections(EvidenceModel):
    sections: list[Section]


class ReportReview(EvidenceModel):
    supported: bool
    issues: list[str]


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object":
                value["additionalProperties"] = False
                value["required"] = list(value.get("properties", {}))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(schema)
    return schema


def source_urls(value: Any) -> set[str]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        urls = {value["url"]} if isinstance(value.get("url"), str) else set()
        return urls.union(*(source_urls(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(source_urls(child) for child in value))
    return set()


def is_private_source_url(url: str) -> bool:
    return bool(
        PRIVATE_URL.fullmatch(url)
        or re.fullmatch(
            r"/api/company-research/[A-Z0-9.^_-]+/runs/"
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/sources/[0-9a-f]{24}",
            url,
        )
    )


def validate_sources(value: Any, *, as_of: date) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        if "url" in value:
            parsed = urlparse(value["url"])
            if not is_private_source_url(value["url"]) and (
                parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password
            ):
                raise ValueError("Evidence contains an invalid public source URL.")
            if value.get("published_on") and date.fromisoformat(value["published_on"]) > as_of:
                raise ValueError("Evidence cites a source published after the as-of date.")
            if not str(value.get("passage", "")).strip() or not str(value.get("location", "")).strip():
                raise ValueError("Every source needs a supporting passage and its location.")
        for child in value.values():
            validate_sources(child, as_of=as_of)
    elif isinstance(value, list):
        for child in value:
            validate_sources(child, as_of=as_of)


def validate_plan(plan: ResearchPlan, *, as_of: date, management: bool, overview: bool) -> None:
    validate_sources(plan, as_of=as_of)
    if management:
        if len(plan.quarters) != 20:
            raise ValueError("Plan must identify the last 20 reported fiscal quarters.")
        ordinals = []
        for quarter in plan.quarters:
            match = re.fullmatch(r"FY(20\d{2}) Q([1-4])", quarter.label)
            if not match or not quarter.ended_on <= quarter.reported_on <= as_of:
                raise ValueError("Quarter labels or reporting dates are invalid.")
            ordinals.append(int(match[1]) * 4 + int(match[2]))
        if sorted(ordinals) != list(range(min(ordinals), min(ordinals) + 20)):
            raise ValueError("Plan must cover 20 consecutive, distinct fiscal quarters.")
        if len({q.ended_on for q in plan.quarters}) != 20:
            raise ValueError("Fiscal quarter end dates must be distinct.")
        ordered = sorted(plan.quarters, key=lambda q: q.label)
        if any(not 70 <= (b.ended_on - a.ended_on).days <= 115 for a, b in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("Fiscal quarter labels and end dates must follow the same consecutive calendar.")
        if not 1 <= len(plan.management_sections) <= 10 or len(set(plan.management_sections)) != len(
            plan.management_sections
        ):
            raise ValueError("Management report sections must be distinct and bounded.")
    if overview:
        if not 1 <= len(plan.overview_topics) <= 5:
            raise ValueError("Overview must have between one and five focused research topics.")
        keys = [topic.key for topic in plan.overview_topics]
        if len(set(keys)) != len(keys) or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,99}", key) for key in keys):
            raise ValueError("Overview research task keys must be unique and safe.")
        sections = [section for topic in plan.overview_topics for section in topic.sections]
        if not sections or len(sections) != len(set(sections)) or len(sections) > 24:
            raise ValueError("Every overview section must belong to exactly one research topic.")


def validate_quarters(packet: QuarterPacket, expected: list[str], *, as_of: date) -> None:
    validate_sources(packet, as_of=as_of)
    if sorted(q.quarter for q in packet.quarters) != sorted(expected):
        raise ValueError("Evidence must account for exactly the assigned quarters.")
    for quarter in packet.quarters:
        if quarter.coverage == "source_unavailable" and (not quarter.gap or quarter.records):
            raise ValueError("An unavailable source requires an explicit gap and cannot support commitments.")
        if quarter.coverage == "researched" and not quarter.sources:
            raise ValueError("A researched quarter must identify the documents reviewed.")
        if not quarter.records and not quarter.gap:
            raise ValueError("A quarter with no commitments needs an evidence-based explanation.")
        for record in quarter.records:
            if record.quarter != quarter.quarter:
                raise ValueError("A commitment was assigned to the wrong fiscal quarter.")
            if record.outcome not in {"Not yet measurable", "Insufficient disclosure"} and not record.outcome_sources:
                raise ValueError("A concluded outcome must have supporting later evidence.")
            record.record_id = (
                "commitment_"
                + hashlib.sha256(
                    f"{record.quarter}|{record.initiative}|{record.claim}|{record.original_target}".encode()
                ).hexdigest()[:20]
            )


def validate_reconciliation(original: list[Commitment], checked: CheckedCommitments, *, as_of: date) -> None:
    validate_sources(checked, as_of=as_of)
    before = {record.record_id: record for record in original}
    after = [record.record_id for record in checked.records] + [record.record_id for record in checked.rejected]
    if len(after) != len(set(after)) or set(after) != set(before):
        raise ValueError("Verification must account for every supplied commitment exactly once.")
    for record in checked.records:
        old = before[record.record_id]
        if (record.quarter, record.claim, record.original_target) != (old.quarter, old.claim, old.original_target):
            raise ValueError(
                "Verification must preserve original promises and deadlines; reject unsupported originals."
            )
        if record.outcome not in {"Not yet measurable", "Insufficient disclosure"} and not record.outcome_sources:
            raise ValueError("A verified outcome needs later source evidence.")
        claim_dates = [s.published_on for s in record.claim_sources if s.published_on]
        outcome_dates = [s.published_on for s in record.outcome_sources if s.published_on]
        if record.outcome not in {"Not yet measurable", "Insufficient disclosure"}:
            if not claim_dates or not outcome_dates or min(outcome_dates) < min(claim_dates):
                raise ValueError("Concluded outcomes need dated evidence no earlier than the original promise.")


def canonical_source_url(url: str) -> str:
    parsed = urlsplit(url)
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid"}
    ]
    # Escape document filenames without equating encoded path separators with literal slashes.
    path = quote(parsed.path, safe="/%:@!$&'*+,;=-._~")
    path = re.sub(r"%[0-9a-fA-F]{2}", lambda match: match[0].upper(), path)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path.rstrip("/"), urlencode(query), ""))


def _report_links(markdown: str) -> list[str]:
    return [
        child.attrGet("href")
        for block in MarkdownIt("commonmark").parse(markdown)
        for child in block.children or []
        if child.type == "link_open" and child.attrGet("href") and not child.attrGet("href").startswith("#")
    ]


def remove_unverified_report_links(written: WrittenSections, urls: set[str]) -> None:
    """De-link unsupported inline suggestions; never add them to the evidence or change claims/IDs.

    The complete section validator and factual audit must still pass afterwards.
    More complex unsupported Markdown links remain unchanged and fail closed.
    """
    allowed = {canonical_source_url(url) for url in urls}
    for section in written.sections:
        unknown = {canonical_source_url(url) for url in _report_links(section.markdown)} - allowed

        def replace(match: re.Match[str], unverified: set[str] = unknown) -> str:
            target = match["url"].strip("<>")
            # A URL-shaped label could become a GFM autolink after removing its wrapper.
            if (
                target.startswith("#")
                or canonical_source_url(target) not in unverified
                or re.search(r"https?://|www\.", match["label"])
            ):
                return match[0]
            return match["label"]

        section.markdown = re.sub(r"\[(?P<label>[^\]\n]+)\]\(\s*(?P<url>[^\s)]+)\s*\)", replace, section.markdown)


def validate_sections(written: WrittenSections, expected: list[str], evidence_ids: set[str], urls: set[str]) -> None:
    if [section.title for section in written.sections] != expected:
        raise ValueError("Report sections do not match the requested structure.")
    for section in written.sections:
        missing_ids = set(section.evidence_ids) - evidence_ids
        if not section.markdown.strip() or missing_ids:
            raise ValueError("Report references missing evidence: " + ", ".join(sorted(missing_ids)))
        links = _report_links(section.markdown)
        allowed = {canonical_source_url(url) for url in urls}
        unknown = [link for link in links if canonical_source_url(link) not in allowed]
        if unknown:
            raise ValueError(
                "Report introduced a source that was not researched: "
                + ", ".join(sorted(set(unknown)))
                + ". Remove these hyperlinks; unverified follow-up reading cannot be cited. "
                "Use only the supplied source URLs: " + ", ".join(sorted(urls))
            )
        if section.evidence_ids and not links:
            raise ValueError("Evidence-backed report sections must include source links.")


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _links(sources: list[Source]) -> str:
    return "; ".join(
        f"[{s.title.replace('[', '').replace(']', '')}]({s.url.replace('(', '%28').replace(')', '%29')})"
        + (f" ({s.published_on})" if s.published_on else "")
        for s in sources
    )


def render_tracker(quarters: list[QuarterReview], records: list[Commitment]) -> str:
    headings = [
        "Fiscal quarter",
        "Source and date",
        "Operational commitment",
        "Category",
        "Original target",
        "Later evidence",
        "Outcome",
        "Delay / variance",
        "Management explanation",
        "Independent verification",
        "Control",
        "Acknowledged variance",
        "Corrective action",
        "Response time",
        "Fix result",
        "Citations",
    ]
    lines = [
        "## Quarter-by-quarter operational commitment tracker",
        "",
        "| " + " | ".join(headings) + " |",
        "| " + " | ".join(["---"] * 16) + " |",
    ]
    for quarter in quarters:
        rows = [r for r in records if r.quarter == quarter.quarter]
        if not rows:
            values = [
                quarter.quarter,
                _links(quarter.sources),
                quarter.gap or "No verified operational commitments",
                *(["Insufficient disclosure"] * 12),
                _links(quarter.sources),
            ]
            lines.append("| " + " | ".join(_cell(v) for v in values) + " |")
        for r in rows:
            values = [
                r.quarter,
                _links(r.claim_sources),
                r.claim,
                r.category,
                r.original_target,
                r.later_evidence,
                r.outcome,
                r.variance,
                r.explanation,
                r.independent_verification,
                r.control,
                r.acknowledgement,
                r.corrective_action,
                r.response_time,
                r.fix_result,
                _links(r.claim_sources + r.outcome_sources),
            ]
            lines.append("| " + " | ".join(_cell(v) for v in values) + " |")
    return "\n".join(lines)
