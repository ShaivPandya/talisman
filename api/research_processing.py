"""Page-complete, multimodal research conversion with bounded repair and source checks."""

from __future__ import annotations

import io
import json
import logging
import re
import time
from collections.abc import Callable
from threading import RLock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from api import research_store as store
from api.exceptions import NotFoundError, ValidationError
from api.research_prompts import CATEGORY_GUIDANCE, CONVERSION_PROMPT, PRACTICAL_GUIDANCE, PROMPT_VERSION, SOURCE_SYSTEM
from llm_utils import call_llm_pdf_text, call_llm_text, model_for_tier, selected_provider_for_tier

logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_PAGES = 200
BATCH_PAGES = 4
_PDF_LOCK = RLock()


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Block(Schema):
    kind: Literal["heading", "text", "visual"]
    page: int = Field(ge=1)
    text: str = Field(min_length=1)
    level: int = Field(default=2, ge=1, le=6)
    caption: str = ""


class PageExtraction(Schema):
    pages_read: list[int]
    metadata_evidence: str = ""
    blocks: list[Block]
    issues: list[str]


class Metadata(Schema):
    title: str | None
    subtitle: str | None
    institution: str | None
    publication_date: str | None
    authors: list[str]
    category: Literal["equity_strategy", "credit_strategy", "economic", "industry_thematic"]
    category_uncertain: bool


class SectionOutput(Schema):
    paragraph: str
    visuals: list[str]


class Check(Schema):
    pages_checked: list[int]
    issues: list[str]


class ResearchJobRequest(BaseModel):
    report_id: str
    token: str
    actor: dict[str, Any] | None = None


def inspect_pdf(data: bytes) -> int:
    if not data or not data.startswith(b"%PDF-"):
        raise ValidationError("Upload a valid PDF, including scanned PDFs.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValidationError("Research PDFs may be at most 30 MiB.")
    import pypdfium2 as pdfium

    try:
        with _PDF_LOCK, pdfium.PdfDocument(data) as pdf:
            count = len(pdf)
            if not 1 <= count <= MAX_PAGES:
                raise ValidationError(f"Research PDFs must contain 1–{MAX_PAGES} pages. Split larger reports first.")
            return count
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(
            "This PDF cannot be read. Remove password protection or upload an undamaged PDF."
        ) from exc


def pdf_pages(data: bytes, start: int, end: int) -> bytes:
    """A bounded PDF slice preserves page images, vector charts and original text."""
    import pypdfium2 as pdfium

    with _PDF_LOCK, pdfium.PdfDocument(data) as source, pdfium.PdfDocument.new() as target:
        target.import_pages(source, pages=list(range(start - 1, end)))
        output = io.BytesIO()
        target.save(output)
        return output.getvalue()


def render_page_images(data: bytes) -> list[bytes]:
    """Explicit images make chart/OCR verification independent of provider PDF text extraction."""
    import pypdfium2 as pdfium

    images: list[bytes] = []
    with _PDF_LOCK, pdfium.PdfDocument(data) as pdf:
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                scale = min(2.0, 2400 / max(page.get_size()))
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    output = io.BytesIO()
                    image.save(output, format="JPEG", quality=90)
                    image.close()
                    images.append(output.getvalue())
                finally:
                    bitmap.close()
            finally:
                page.close()
    return images


class Converter:
    def __init__(self, provider: str, model: str):
        self.provider, self.model = provider, model
        self.started = time.monotonic()
        self.calls = 0

    def ask[T: Schema](self, instruction: str, schema: type[T], pdf: bytes | None = None) -> T:
        if self.calls >= 350 or time.monotonic() - self.started > 70 * 60:
            raise ValidationError("Processing limit reached. Split the report into smaller PDFs and retry.")
        self.calls += 1
        prompt = instruction + "\nReturn JSON matching this schema:\n" + json.dumps(schema.model_json_schema())
        kwargs: dict[str, Any] = dict(
            prompt=prompt, model=self.model, provider=self.provider, system=SOURCE_SYSTEM, max_tokens=16000
        )
        if pdf is not None:
            text, _, response = call_llm_pdf_text(
                pdf_bytes=pdf, filename="source.pdf", page_images=render_page_images(pdf), **kwargs
            )
        else:
            text, _, response = call_llm_text(enable_web_search=False, **kwargs)
        # An otherwise parseable partial response must never be accepted as complete.
        raw = response if isinstance(response, dict) else {}
        stop = raw.get("stop_reason") or getattr(response, "stop_reason", None)
        status = raw.get("status") or getattr(response, "status", None)
        if stop == "max_tokens" or status == "incomplete":
            raise ValueError("The model output was truncated.")
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        return schema.model_validate_json(clean)


def extract_batch(converter: Converter, data: bytes, start: int, end: int) -> list[PageExtraction]:
    instruction = f"""Inspect every attached page (original pages {start} through {end}).
Transcribe all substantive text accurately, using OCR where necessary. Preserve reading order in
multi-column layouts. Return ordered heading, text, and visual blocks with ORIGINAL page numbers.
Headings must use exact original wording and hierarchy (report title is metadata, substantive
sections normally begin at level 2). Exclude repeated running headers, page numbers and decorative
elements. Include unheaded opening text, notes, sources, disclosures and appendices. For every
substantive chart/table/image, create a visual block: exact caption separately, then describe all
readable important values, labels, units, trends and qualifications. Never invent unreadable values.
metadata_evidence must transcribe title/subtitle, institution, publication date, and ALL author
credits found on these pages, including credits in the back matter. Do not infer from filenames.
List any illegible or missing material in issues. pages_read must list every original page inspected."""
    try:
        result = converter.ask(instruction, PageExtraction, pdf_pages(data, start, end))
        if result.pages_read != list(range(start, end + 1)):
            raise ValueError("Not every PDF page was inspected.")
        if any(block.page < start or block.page > end for block in result.blocks):
            raise ValueError("Extraction returned a page outside its source range.")
        if [b.page for b in result.blocks] != sorted(b.page for b in result.blocks):
            raise ValueError("Extraction changed the source page order.")
        return [result]
    except (ValueError, json.JSONDecodeError):
        if start == end:
            raise
        middle = (start + end) // 2
        return extract_batch(converter, data, start, middle) + extract_batch(converter, data, middle + 1, end)


def sections_from_blocks(blocks: list[Block]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] = {"heading": "", "level": 2, "blocks": [], "pages": []}
    for block in blocks:
        if block.kind == "heading":
            if current["heading"] or current["blocks"]:
                sections.append(current)
            current = {"heading": block.text, "level": block.level, "blocks": [], "pages": [block.page]}
        else:
            current["blocks"].append(block.model_dump())
            current["pages"] = sorted(set([*current["pages"], block.page]))
    if current["heading"] or current["blocks"]:
        sections.append(current)
    for index, section in enumerate(sections):
        section["id"] = f"section-{index + 1}"
    return sections


def clean_markdown(value: str) -> str:
    # Normalize model presentation mistakes while retaining their text for the source check.
    value = re.sub(r"^\s*(?:```|~~~)[^\n]*$", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*#{1,6}\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"!\[([^\]]*)\]\([^\n)]*\)", r"\1", value)
    value = value.replace("![", "[")
    if re.search(r"<\s*/?\s*[A-Za-z][^>]*>", value):
        from bs4 import BeautifulSoup, NavigableString, Tag

        soup = BeautifulSoup(value, "html.parser")
        for element in soup.find_all(["script", "style", "iframe", "object"]):
            element.decompose()
        for element in soup.find_all("img"):
            if isinstance(element, Tag):
                element.replace_with(NavigableString(str(element.get("alt") or "")))
        value = soup.get_text(" ").strip()
    return value.strip()


def condense(converter: Converter, section: dict[str, Any], repair: list[str] | None = None) -> SectionOutput:
    blocks = section["blocks"]
    if not blocks:
        return SectionOutput(paragraph="", visuals=[])
    # Long sections are condensed in bounded pieces, then reconciled into a single paragraph.
    groups: list[list[dict[str, Any]]] = []
    group: list[dict[str, Any]] = []
    for block in blocks:
        if group and len(json.dumps([*group, block])) > 45000:
            groups.append(group)
            group = []
        group.append(block)
    if group:
        groups.append(group)
    outputs = []
    for group in groups:
        instruction = (
            CONVERSION_PROMPT
            + "\n"
            + PRACTICAL_GUIDANCE
            + "\nProduce ONLY this section's body, not its heading or metadata.\n"
        )
        instruction += "paragraph: one cohesive summary paragraph; visuals: one description per visual block, in order, including its exact caption.\n"
        instruction += "Do not add headings, HTML, images or commentary. Preserve all material sources and caveats.\n"
        instruction += json.dumps(
            {"heading": section["heading"], "source_blocks": group, "repair_findings": repair or []}
        )
        result = converter.ask(instruction, SectionOutput)
        expected = [block for block in group if block["kind"] == "visual"]
        recovered_visuals = len(result.visuals) != len(expected)
        if recovered_visuals:
            result.visuals = source_output({"blocks": group}).visuals
            section["source_retained"] = True
        if (
            any(b["kind"] == "text" for b in group)
            and not result.paragraph.strip()
            and (not result.visuals or recovered_visuals)
        ):
            # Preserve extracted source text rather than rejecting an otherwise usable report.
            result.paragraph = source_output({"blocks": group}).paragraph
            section["source_retained"] = True
        result.paragraph = clean_markdown(result.paragraph)
        result.visuals = [clean_markdown(v) for v in result.visuals]
        for index, (visual, source) in enumerate(zip(result.visuals, expected, strict=True)):
            if not visual:
                result.visuals[index] = source_output({"blocks": [source]}).visuals[0]
                section["source_retained"] = True
            elif source["caption"] and source["caption"] not in visual:
                result.visuals[index] = clean_markdown(source["caption"]) + ". " + visual
        outputs.append(result)
    if len(outputs) == 1:
        return outputs[0]
    paragraphs = [o.paragraph for o in outputs if o.paragraph]
    reconciled = converter.ask(
        CONVERSION_PROMPT + "\nReconcile these consecutive pieces of ONE section into one cohesive paragraph. "
        "Preserve every distinct argument, number, source and caveat. Return visuals=[]; they are assembled separately.\n"
        + json.dumps(paragraphs),
        SectionOutput,
    )
    return SectionOutput(
        paragraph=clean_markdown(reconciled.paragraph) or "\n\n".join(paragraphs),
        visuals=[v for o in outputs for v in o.visuals],
    )


def source_output(section: dict[str, Any]) -> SectionOutput:
    """Retain source evidence when a model cannot produce a reliable condensed section."""

    def plain(value: str) -> str:
        # Render extracted text literally, without executable HTML or Markdown images/headings.
        return re.sub(r"([\\`*_{}\[\]()#+!<>|])", r"\\\1", value).strip()

    return SectionOutput(
        paragraph="\n\n".join(plain(b["text"]) for b in section["blocks"] if b["kind"] == "text"),
        visuals=[
            plain("\n".join(filter(None, [b.get("caption"), b["text"]])))
            for b in section["blocks"]
            if b["kind"] == "visual"
        ],
    )


def best_effort_section(
    converter: Converter, section: dict[str, Any], findings: list[str] | None = None
) -> SectionOutput:
    for _ in range(2):
        try:
            return condense(converter, section, findings)
        except (store.SupersededResearch, NotFoundError):
            raise
        except Exception as exc:
            logger.warning("Retriable condensation issue in %s (%s)", section["id"], type(exc).__name__)
            findings = ["Return a complete usable section, preserving the supplied source evidence."]
    section["source_retained"] = True
    return source_output(section)


def assemble(metadata: Metadata, sections: list[dict[str, Any]]) -> str:
    if not metadata.title or not metadata.title.strip():
        raise ValueError("The original report title could not be established.")
    lines = ["# " + metadata.title.strip()]
    if metadata.subtitle:
        lines.append(metadata.subtitle)
    for label, value in (
        ("Institution", metadata.institution),
        ("Publication date", metadata.publication_date),
        ("Authors", ", ".join(metadata.authors)),
    ):
        if value:
            lines.append(f"**{label}:** {value}")
    for section in sections:
        if section["heading"]:
            lines.append("#" * section["level"] + " " + section["heading"])
        body = section["output"]
        if body["paragraph"]:
            lines.append(body["paragraph"])
        lines.extend(body["visuals"])
    return "\n\n".join(lines).strip() + "\n"


def verify(
    converter: Converter,
    data: bytes,
    count: int,
    metadata: Metadata,
    sections: list[dict[str, Any]],
    progress: Callable[[int, int], Any],
) -> list[str]:
    def check_range(start: int, end: int) -> list[str]:
        relevant = [s for s in sections if any(start <= p <= end for p in s["pages"])]
        # Include source locations but avoid sending the entire original transcript a second time.
        candidate = [{k: v for k, v in s.items() if k != "blocks"} for s in relevant]
        instruction = (
            CONVERSION_PROMPT
            + "\n"
            + PRACTICAL_GUIDANCE
            + f"""\nIndependently compare original PDF pages {start} through {end} (attached page 1 corresponds to original page {start})
against the candidate condensed sections and report metadata below. Read the actual PDF images.
Check that EVERY substantive heading, visual, argument, source/caveat and important numeric finding
on these pages is represented, in order, with no unsupported claims. Compare author credits when
present. Distinguish forecasts/scenarios from facts. Sections spanning other pages can contain facts
from those pages; do not flag them merely because they are outside this slice. Report only concrete
defects with original page and section id. Report ONLY material analytical errors: invented or
wrong figures, reversed conclusions, lost substantive research or misleading factual claims.
Do not flag unlabeled/unreadable chart values, concise standard legal boilerplate, cosmetic
differences or redundant text. These are editorial choices, not publication failures.
pages_checked must list all inspected original pages.
An empty issues list means no defects found, not a guarantee of correctness.\n"""
        )
        check = converter.ask(
            instruction + json.dumps({"metadata": metadata.model_dump(), "sections": candidate}),
            Check,
            pdf_pages(data, start, end),
        )
        if sorted(set(check.pages_checked)) != list(range(start, end + 1)):
            if start < end:
                middle = (start + end) // 2
                return check_range(start, middle) + check_range(middle + 1, end)
            raise ValueError(f"Verification did not confirm original page {start} (reported {check.pages_checked}).")
        return check.issues

    findings: list[str] = []
    for start in range(1, count + 1, BATCH_PAGES):
        end = min(count, start + BATCH_PAGES - 1)
        findings.extend(check_range(start, end))
        progress(end, count)
    return findings


def run_research_job(req: ResearchJobRequest, *, job_id: str | None = None) -> dict[str, Any]:
    from api.research import enqueue_index, get_job

    report_id, token = req.report_id, req.token

    def assert_active() -> None:
        if job_id:
            job = get_job(job_id)
            if job and job["status"] in {"failed", "cancelled"}:
                raise store.SupersededResearch("The background job is no longer active.")

    def update(**changes: Any) -> dict[str, Any]:
        assert_active()
        return store.mutate(report_id, lambda state: state.update(changes), actor=req.actor, token=token)

    def save(name: str, value: Any) -> None:
        store.save_artifact(
            report_id, token, f"{token}-{name}.json", json.dumps(value, ensure_ascii=False).encode(), "application/json"
        )

    try:
        initial = update(status="reading", job_id=job_id, error=None)
        data = store.read_blob(report_id, "original.pdf")
        count = inspect_pdf(data)
        provider = selected_provider_for_tier("mid")
        if provider == "talisman":
            raise ValidationError("Select a PDF-capable provider in AI Settings before processing research.")
        model = model_for_tier("mid", provider=provider)
        converter = Converter(provider, model)
        extracted: list[PageExtraction] = []
        for start in range(1, count + 1, BATCH_PAGES):
            end = min(count, start + BATCH_PAGES - 1)
            extracted.extend(extract_batch(converter, data, start, end))
            save("extraction", [e.model_dump() for e in extracted])
            update(progress={"done": end, "total": count})
        blocks = [b for e in extracted for b in e.blocks]
        if not blocks:
            raise ValueError("No substantive report content could be read.")
        metadata = converter.ask(
            CATEGORY_GUIDANCE
            + "\nExtract exact original metadata from the evidence. Omit absent values using null/empty authors. "
            "Publication date should retain the source's wording; never substitute upload date. "
            "Use the entire report's headings and evidence for classification.\n"
            + json.dumps(
                {
                    "metadata_evidence": [e.metadata_evidence for e in extracted],
                    "report_outline": [b.text if b.kind == "heading" else b.text[:500] for b in blocks],
                }
            ),
            Metadata,
        )

        # Missing bibliographic fields must not prevent an otherwise useful conversion.
        metadata.title = (metadata.title or "").strip() or initial.get("title") or "Untitled research report"

        def apply_metadata(state: dict[str, Any]) -> None:
            if not state.get("current_revision"):
                for key in ("title", "subtitle", "institution", "publication_date", "authors"):
                    state[key] = getattr(metadata, key)
            if state["category_source"] == "automatic":
                state.update(category=metadata.category, category_uncertain=metadata.category_uncertain)
            state.update(status="condensing", progress={"done": 0, "total": 0})

        store.mutate(report_id, apply_metadata, actor=req.actor, token=token)
        sections = sections_from_blocks(blocks)
        for index, section in enumerate(sections):
            section["output"] = best_effort_section(converter, section).model_dump()
            update(progress={"done": index + 1, "total": len(sections)})
        save("sections", sections)
        update(status="checking", progress={"done": 0, "total": count})
        extraction_notes = [issue for e in extracted for issue in e.issues]
        findings: list[str] = []
        verification_complete = False
        try:
            findings = verify(
                converter,
                data,
                count,
                metadata,
                sections,
                lambda done, total: update(progress={"done": done, "total": total}),
            )
            if findings:
                for section in sections:
                    defects = [f for f in findings if re.search(rf"\b{re.escape(section['id'])}\b", f)]
                    if defects:
                        section["output"] = best_effort_section(converter, section, defects).model_dump()
                findings = verify(
                    converter,
                    data,
                    count,
                    metadata,
                    sections,
                    lambda done, total: update(progress={"done": done, "total": total}),
                )
            verification_complete = True
        except (store.SupersededResearch, NotFoundError):
            raise
        except Exception as exc:
            logger.warning("Research verification unavailable (%s); preserving extracted source", type(exc).__name__)
            findings = ["Source comparison unavailable; extracted source retained."]
        # A persistent material defect uses source text rather than blocking the whole report.
        identified = {s["id"] for s in sections for f in findings if re.search(rf"\b{re.escape(s['id'])}\b", f)}
        unlocated = any(not any(re.search(rf"\b{re.escape(s['id'])}\b", f) for s in sections) for f in findings)
        for section in sections:
            if findings and (unlocated or section["id"] in identified):
                section["output"] = source_output(section).model_dump()
                section["source_retained"] = True
        save("sections", sections)
        save(
            "validation",
            {
                "extraction_notes": extraction_notes,
                "findings": findings,
                "verification_complete": verification_complete,
                "pages_checked": count if verification_complete else None,
                "source_retained_sections": [s["id"] for s in sections if s.get("source_retained")],
                "prompt_version": PROMPT_VERSION,
                "provider": provider,
                "model": model,
                "calls": converter.calls,
            },
        )
        markdown = assemble(metadata, sections)
        store.save_artifact(report_id, token, f"{token}.md", markdown.encode(), "text/markdown; charset=utf-8")

        def publish(state: dict[str, Any]) -> None:
            assert_active()
            for key in ("title", "subtitle", "institution", "publication_date", "authors"):
                state[key] = getattr(metadata, key)
            revision = {
                "id": token,
                "created_at": store.now(),
                "prompt_version": PROMPT_VERSION,
                "model": model,
                "provider": provider,
                "title": metadata.title,
                "metadata": metadata.model_dump(),
                "section_count": len(sections),
                "visual_count": sum(len(s["output"]["visuals"]) for s in sections),
            }
            state["revisions"].append(revision)
            state.update(current_revision=token, status="ready", issues=[], index_status="pending", index_error=None)

        result = store.mutate(report_id, publish, actor=req.actor, token=token)
        enqueue_index(result, req.actor)
        return {"report_id": report_id, "status": "ready"}
    except (store.SupersededResearch, NotFoundError):
        return {"report_id": report_id, "status": "superseded"}
    except Exception as exc:
        logger.exception("Research conversion failed: %s", report_id)
        message = (
            str(exc)
            if isinstance(exc, (ValidationError, ValueError))
            else "Research processing failed. Retry the report; the original PDF has been retained."
        )
        try:
            update(status="failed", error=message[:600])
        except (store.SupersededResearch, NotFoundError):
            pass
        raise RuntimeError(message) from exc
