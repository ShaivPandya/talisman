"""User-curated market/news digest storage and parsing.

Raw markdown uploads are the source of truth. Parsed sections and stories are
derived metadata used by the UI and report prompts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from api.state_storage import delete_file, exists_text, read_text, write_text
from paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

DIGESTS_DIR = PROJECT_ROOT / "data_cache" / "news_digests"
DIGESTS_GCS_PREFIX = "live/news_digests"
MANIFEST_PATH = DIGESTS_DIR / "manifest.json"
MANIFEST_GCS_KEY = f"{DIGESTS_GCS_PREFIX}/manifest.json"
FILES_DIR = DIGESTS_DIR / "files"
FILES_GCS_PREFIX = f"{DIGESTS_GCS_PREFIX}/files"

_DEFAULT_TITLE = "Untitled Digest"
_MAX_TITLE_LEN = 180
_MAX_SLUG_LEN = 90
_DIGEST_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]{1,90}$")


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _iso_now() -> str:
    return _now_utc().isoformat().replace("+00:00", "Z")


def _safe_title(value: str | None, fallback: str = _DEFAULT_TITLE) -> str:
    title = re.sub(r"\s+", " ", (value or "").strip())
    if not title:
        title = fallback
    return title[:_MAX_TITLE_LEN]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "digest")[:_MAX_SLUG_LEN].strip("-") or "digest"


def validate_digest_id(digest_id: str) -> str:
    value = str(digest_id or "").strip()
    if not _DIGEST_ID_RE.match(value):
        raise ValueError("Invalid news digest id")
    try:
        date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError("Invalid news digest id") from exc
    return value


def _is_manifest_digest_id(digest_id: str) -> bool:
    try:
        validate_digest_id(digest_id)
        return True
    except ValueError:
        return False


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except Exception:
        return None


def _extract_filename_date(filename: str | None) -> date | None:
    name = Path(filename or "").name

    # Common digest export shape: 05012026_digest.md (MMDDYYYY).
    match = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{4})(?!\d)", name)
    if match:
        month, day, year = match.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            pass

    # Also accept YYYYMMDD, YYYY-MM-DD, or YYYY_MM_DD.
    match = re.search(r"(?<!\d)(\d{4})[-_]?(\d{2})[-_]?(\d{2})(?!\d)", name)
    if match:
        year, month, day = match.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            pass

    return None


def _extract_generated_date(markdown: str, filename: str | None, uploaded_at: datetime | None) -> date:
    match = re.search(r"\bGenerated:\s*(\d{4}-\d{2}-\d{2})\b", markdown, flags=re.IGNORECASE)
    if match:
        parsed = _parse_date(match.group(1))
        if parsed:
            return parsed

    filename_date = _extract_filename_date(filename)
    if filename_date:
        return filename_date

    return (uploaded_at or _now_utc()).date()


def _extract_title(markdown: str, filename: str | None) -> str:
    for line in markdown.splitlines():
        match = re.match(r"^\s*#\s+(.+?)\s*#*\s*$", line)
        if match:
            return _safe_title(match.group(1))

    stem = Path(filename or "").stem.replace("_", " ").replace("-", " ").strip()
    return _safe_title(stem, fallback=_DEFAULT_TITLE)


def _strip_bullet(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(\s*)[-*]\s+(.+?)\s*$", line)
    if not match:
        return None
    indent = len(match.group(1).replace("\t", "    "))
    return indent, match.group(2).strip()


_MULTI_SIGNAL_RE = re.compile(r"`?\[MULTI-SIGNAL\]`?", flags=re.IGNORECASE)
_BOLD_LEAD_RE = re.compile(r"^\*\*(.+?)\*\*")
_SOURCE_RE = re.compile(r"\s[—–-]\s*\*?\((.+?)\)\*?(?=\s*(?:[—–-]|$))")
_TRAILING_SOURCE_RE = re.compile(r"\s\*?\(([^()]+(?:\([^()]*\))?)\)\*?\s*$")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
_RAW_URL_RE = re.compile(r"(?<![(\w])(https?://[^\s)>]+)")
_CONFIDENCE_RE = re.compile(r"confidence:?\**\s*([01](?:\.\d+)?)", flags=re.IGNORECASE)
_ALSO_RE = re.compile(r"\balso:\s*(.+)$", flags=re.IGNORECASE)
_NUMBERED_RE = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+?)\s*$")
_TOP_SECTION_RE = re.compile(r"^top\s+\d+\b", flags=re.IGNORECASE)
_IMPLICATIONS_SECTION_RE = re.compile(r"^second[- ]order", flags=re.IGNORECASE)


def _plain_text(value: str) -> str:
    text = _MULTI_SIGNAL_RE.sub("", value)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"(?<!\w)\*(?!\s)([^*]+?)\*(?!\w)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _headline_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _plain_text(value).lower())


def _split_headline(text: str) -> tuple[str, str]:
    """Split a story line into its headline and the remainder after it."""
    body = _MULTI_SIGNAL_RE.sub("", text).strip()
    bold = _BOLD_LEAD_RE.match(body)
    if bold:
        return _plain_text(bold.group(1)), body[bold.end() :]
    source = _SOURCE_RE.search(body) or _TRAILING_SOURCE_RE.search(body)
    if source:
        return _plain_text(body[: source.start()]), body[source.start() :]
    return _plain_text(body), ""


def _parse_story_line(text: str) -> dict[str, Any]:
    headline, rest = _split_headline(text)
    source_match = _SOURCE_RE.search(rest) or _TRAILING_SOURCE_RE.search(rest)
    url_match = _MARKDOWN_LINK_RE.search(rest) or _RAW_URL_RE.search(rest)
    return {
        "headline": headline or _plain_text(text),
        "source": source_match.group(1).strip() if source_match else None,
        "url": url_match.group(1) if url_match else None,
        "multi_signal": bool(_MULTI_SIGNAL_RE.search(text)),
    }


def _parse_meta_note(text: str) -> dict[str, Any] | None:
    """Parse the tags/confidence line written under each story, if this is one."""
    confidence = _CONFIDENCE_RE.search(text)
    tag_chunks = re.findall(r"`([^`]+)`", text)
    if not confidence or not tag_chunks:
        return None
    tags = [
        tag.strip()
        for chunk in tag_chunks
        for tag in re.split(r"[,·]", chunk)
        if re.fullmatch(r"[a-z][a-z0-9_]*", tag.strip())
    ]
    also = _ALSO_RE.search(text)
    return {
        "tags": list(dict.fromkeys(tags)),
        "confidence": float(confidence.group(1)),
        "also_sources": [item.strip() for item in also.group(1).split(",") if item.strip()] if also else [],
    }


def _implication_text(text: str) -> str:
    _, rest = _split_headline(text)
    if not rest:
        return ""
    return _plain_text(re.sub(r"^\s*[—–-]\s*", "", rest))


def parse_digest_markdown(
    markdown: str,
    *,
    filename: str | None = None,
    uploaded_at: datetime | None = None,
) -> dict[str, Any]:
    """Parse digest markdown into stable metadata and story sections.

    Story sections are ``##`` headings with one top-level bullet per story. A
    "Top N" section ranks stories by headline, and a "Second-Order
    Implications" section attaches an implication to each story by headline;
    neither adds stories of its own.
    """
    title = _extract_title(markdown, filename)
    generated = _extract_generated_date(markdown, filename, uploaded_at)

    sections: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None
    current_story: dict[str, Any] | None = None
    section_kind = "stories"
    top_lines: list[tuple[int, str]] = []
    implication_lines: list[tuple[str, list[str]]] = []
    story_index = 0

    def ensure_section() -> dict[str, Any]:
        nonlocal current_section
        if current_section is None:
            current_section = {"name": "Uncategorized", "stories": []}
            sections.append(current_section)
        return current_section

    for raw_line in markdown.replace("\r\n", "\n").split("\n"):
        h2 = re.match(r"^\s*##\s+(.+?)\s*#*\s*$", raw_line)
        if h2:
            name = _safe_title(h2.group(1), fallback="Untitled Section")
            current_story = None
            if _TOP_SECTION_RE.match(name):
                section_kind = "top"
            elif _IMPLICATIONS_SECTION_RE.match(name):
                section_kind = "implications"
            else:
                section_kind = "stories"
                current_section = {"name": name, "stories": []}
                sections.append(current_section)
            continue

        if section_kind == "top":
            numbered = _NUMBERED_RE.match(raw_line)
            if numbered:
                top_lines.append((int(numbered.group(1)), numbered.group(2)))
            continue

        bullet = _strip_bullet(raw_line)
        if bullet is None:
            continue
        indent, text = bullet

        if section_kind == "implications":
            if indent <= 1:
                implication_lines.append((text, []))
            elif implication_lines:
                implication_lines[-1][1].append(text)
            continue

        if indent <= 1:
            section = ensure_section()
            story_index += 1
            current_story = {
                "id": f"story-{story_index}",
                "section": section["name"],
                **_parse_story_line(text),
                "tags": [],
                "confidence": None,
                "also_sources": [],
                "notes": [],
                "top_rank": None,
                "implication": None,
            }
            section["stories"].append(current_story)
        elif current_story is not None:
            meta = _parse_meta_note(text) if current_story["confidence"] is None else None
            if meta:
                current_story.update(meta)
            else:
                current_story["notes"].append(_plain_text(text))

    sections = [section for section in sections if section.get("stories")]
    stories = [story for section in sections for story in section.get("stories", [])]

    by_key: dict[str, dict[str, Any]] = {}
    for story in stories:
        by_key.setdefault(_headline_key(story["headline"]), story)

    def find_story(text: str) -> dict[str, Any] | None:
        headline, _ = _split_headline(text)
        key = _headline_key(headline)
        if not key:
            return None
        if key in by_key:
            return by_key[key]
        prefix = key[:60]
        matches = [story for story_key, story in by_key.items() if story_key.startswith(prefix)]
        return matches[0] if len(matches) == 1 else None

    top_stories: list[dict[str, Any]] = []
    for rank, text in top_lines:
        story = find_story(text)
        if story is not None and story["top_rank"] is None:
            story["top_rank"] = rank
        top_stories.append(
            {
                "rank": rank,
                "headline": story["headline"] if story else _split_headline(text)[0],
                "story_id": story["id"] if story else None,
                "source": story["source"] if story else None,
            }
        )

    for text, sub_notes in implication_lines:
        story = find_story(text)
        implication = _implication_text(text) or _plain_text(" ".join(sub_notes))
        if story is not None and implication:
            story["implication"] = implication

    return {
        "title": title,
        "slug": slugify(title),
        "generated_date": generated.isoformat(),
        "sections": sections,
        "stories": stories,
        "top_stories": top_stories,
        "story_count": len(stories),
        "section_count": len(sections),
        "multi_signal_count": sum(1 for story in stories if story["multi_signal"]),
    }


def _digest_id(generated_date: str, slug: str) -> str:
    return f"{generated_date}-{slugify(slug)}"


def _digest_local_path(digest_id: str) -> Path:
    return FILES_DIR / f"{digest_id}.md"


def _safe_digest_local_path(digest_id: str) -> Path:
    normalized = validate_digest_id(digest_id)
    base = FILES_DIR.resolve(strict=False)
    path = (FILES_DIR / f"{normalized}.md").resolve(strict=False)
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ValueError("Digest path escapes storage directory") from exc
    return path


def _digest_gcs_key(digest_id: str) -> str:
    return f"{FILES_GCS_PREFIX}/{digest_id}.md"


def _empty_manifest() -> dict[str, Any]:
    return {"version": 1, "digests": []}


def _load_manifest() -> dict[str, Any]:
    if not exists_text(MANIFEST_PATH, MANIFEST_GCS_KEY):
        return _empty_manifest()
    try:
        data = json.loads(read_text(MANIFEST_PATH, MANIFEST_GCS_KEY, encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read news digest manifest; using empty manifest", exc_info=True)
        return _empty_manifest()
    if not isinstance(data, dict) or not isinstance(data.get("digests"), list):
        return _empty_manifest()
    return data


def _write_manifest(manifest: dict[str, Any]) -> None:
    write_text(
        MANIFEST_PATH,
        MANIFEST_GCS_KEY,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        content_type="application/json; charset=utf-8",
    )


def _summary_from_parsed(
    *,
    digest_id: str,
    filename: str,
    parsed: dict[str, Any],
    uploaded_at: str,
    updated_at: str,
    content_hash: str,
) -> dict[str, Any]:
    return {
        "id": digest_id,
        "title": parsed["title"],
        "slug": parsed["slug"],
        "filename": filename,
        "generated_date": parsed["generated_date"],
        "uploaded_at": uploaded_at,
        "updated_at": updated_at,
        "content_hash": content_hash,
        "story_count": parsed["story_count"],
        "section_count": parsed["section_count"],
        "multi_signal_count": parsed["multi_signal_count"],
        "sections": [
            {"name": section["name"], "story_count": len(section.get("stories", []))}
            for section in parsed.get("sections", [])
        ],
    }


def _sort_summaries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            str(item.get("generated_date") or ""),
            str(item.get("updated_at") or ""),
            str(item.get("title") or ""),
        ),
        reverse=True,
    )


def save_digest(markdown: str, *, filename: str | None = None) -> dict[str, Any]:
    """Store or replace a digest and return its detail payload."""
    from ontology.domain_write_service import assert_domain_table_write_allowed

    assert_domain_table_write_allowed("news_digests.save_digest")
    now = _now_utc()
    now_iso = now.isoformat().replace("+00:00", "Z")
    parsed = parse_digest_markdown(markdown, filename=filename, uploaded_at=now)
    digest_id = _digest_id(parsed["generated_date"], parsed["slug"])
    safe_filename = Path(filename or f"{digest_id}.md").name
    content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()

    manifest = _load_manifest()
    existing = next(
        (item for item in manifest["digests"] if isinstance(item, dict) and item.get("id") == digest_id),
        None,
    )
    uploaded_at = str(existing.get("uploaded_at")) if existing else now_iso

    write_text(
        _digest_local_path(digest_id),
        _digest_gcs_key(digest_id),
        markdown,
        encoding="utf-8",
        content_type="text/markdown; charset=utf-8",
        metadata={
            "digest_id": digest_id,
            "generated_date": parsed["generated_date"],
            "title": parsed["title"],
        },
    )

    summary = _summary_from_parsed(
        digest_id=digest_id,
        filename=safe_filename,
        parsed=parsed,
        uploaded_at=uploaded_at,
        updated_at=now_iso,
        content_hash=content_hash,
    )

    manifest["digests"] = [
        item for item in manifest["digests"] if not isinstance(item, dict) or item.get("id") != digest_id
    ]
    manifest["digests"].append(summary)
    manifest["digests"] = _sort_summaries(manifest["digests"])
    _write_manifest(manifest)

    return {**summary, "content": markdown, "parsed": parsed}


def list_digest_summaries() -> list[dict[str, Any]]:
    """Return stored digest summaries, newest first, without reading digest files."""
    return _sort_summaries(
        [
            item
            for item in _load_manifest().get("digests", [])
            if isinstance(item, dict) and _is_manifest_digest_id(str(item.get("id") or ""))
        ]
    )


def find_existing_digest(markdown: str, *, filename: str | None = None) -> dict[str, Any] | None:
    """Return the stored summary an upload of this exact markdown would duplicate, if any."""
    parsed = parse_digest_markdown(markdown, filename=filename)
    digest_id = _digest_id(parsed["generated_date"], parsed["slug"])
    content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    return next(
        (
            item
            for item in _load_manifest().get("digests", [])
            if isinstance(item, dict) and item.get("id") == digest_id and item.get("content_hash") == content_hash
        ),
        None,
    )


def _read_digest_content(digest_id: str) -> str:
    normalized = validate_digest_id(digest_id)
    return read_text(_safe_digest_local_path(normalized), _digest_gcs_key(normalized), encoding="utf-8")


def list_digests() -> dict[str, Any]:
    """Return digest summaries plus parsed story metadata for the library UI."""
    manifest = _load_manifest()
    summaries = _sort_summaries(
        [
            item
            for item in manifest.get("digests", [])
            if isinstance(item, dict) and _is_manifest_digest_id(str(item.get("id") or ""))
        ]
    )

    flat_stories: list[dict[str, Any]] = []
    for summary in summaries:
        digest_id = str(summary.get("id") or "")
        if not digest_id:
            continue
        try:
            content = _read_digest_content(digest_id)
            parsed = parse_digest_markdown(content, filename=str(summary.get("filename") or ""))
        except Exception:
            logger.debug("Skipping story parse for missing digest %s", digest_id, exc_info=True)
            continue
        for story in parsed.get("stories", []):
            flat_stories.append(
                {
                    **story,
                    "digest_id": digest_id,
                    "digest_title": summary.get("title"),
                    "generated_date": summary.get("generated_date"),
                }
            )

    return {
        "items": summaries,
        "stories": flat_stories,
        "counts": {
            "digests": len(summaries),
            "stories": len(flat_stories),
        },
    }


def get_digest(digest_id: str) -> dict[str, Any]:
    digest_id = validate_digest_id(digest_id)
    manifest = _load_manifest()
    summary = next((item for item in manifest.get("digests", []) if item.get("id") == digest_id), None)
    if not summary:
        raise FileNotFoundError(digest_id)

    content = _read_digest_content(digest_id)
    parsed = parse_digest_markdown(content, filename=str(summary.get("filename") or ""))
    return {**summary, "content": content, "parsed": parsed}


def delete_digest(digest_id: str) -> bool:
    from ontology.domain_write_service import assert_domain_table_write_allowed

    assert_domain_table_write_allowed("news_digests.delete_digest")
    digest_id = validate_digest_id(digest_id)
    manifest = _load_manifest()
    digests = [item for item in manifest.get("digests", []) if isinstance(item, dict)]
    if not any(item.get("id") == digest_id for item in digests):
        return False
    before = len(digests)
    manifest["digests"] = [item for item in digests if item.get("id") != digest_id]
    removed_manifest = len(manifest["digests"]) != before
    removed_file = delete_file(_safe_digest_local_path(digest_id), _digest_gcs_key(digest_id))
    if removed_manifest:
        _write_manifest(manifest)
    return removed_manifest or removed_file


def _summary_sort_key(summary: dict[str, Any]) -> tuple[str, str]:
    return (str(summary.get("generated_date") or ""), str(summary.get("updated_at") or ""))


def _truncate(text: str, max_chars: int) -> str:
    value = re.sub(r"\s+", " ", (text or "").strip())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "..."


def _story_priority(story: dict[str, Any]) -> tuple[int, int, int, float]:
    rank = story.get("top_rank")
    confidence = story.get("confidence")
    return (
        0 if rank is not None else 1,
        int(rank or 0),
        0 if story.get("multi_signal") else 1,
        -float(confidence if confidence is not None else 0.0),
    )


def get_report_context(
    *,
    days: int,
    now: datetime | None = None,
    max_digests: int = 5,
    max_stories: int = 80,
    notes_per_story: int = 2,
    max_text_chars: int = 700,
) -> dict[str, Any]:
    """Build a compact, deterministic digest context for report prompts."""
    manifest = _load_manifest()
    summaries = _sort_summaries(
        [
            item
            for item in manifest.get("digests", [])
            if isinstance(item, dict) and _is_manifest_digest_id(str(item.get("id") or ""))
        ]
    )
    if not summaries:
        return {"window_days": days, "digests": [], "counts": {"digests": 0, "stories": 0}, "fallback_used": False}

    ref = now or _now_utc()
    cutoff = (ref.date() - timedelta(days=max(0, days))).isoformat()
    recent = [item for item in summaries if str(item.get("generated_date") or "") >= cutoff]
    fallback_used = False
    if not recent:
        recent = summaries[:1]
        fallback_used = True

    selected = sorted(recent, key=_summary_sort_key, reverse=True)[:max_digests]
    remaining = max(1, max_stories)
    digest_payloads: list[dict[str, Any]] = []
    included_stories = 0

    for summary in selected:
        if remaining <= 0:
            break
        digest_id = str(summary.get("id") or "")
        if not digest_id:
            continue
        try:
            detail = get_digest(digest_id)
        except Exception:
            continue

        parsed = detail.get("parsed", {})
        # Share the story budget across the remaining digests, and within each
        # digest keep the Top N, then multi-signal, then highest-confidence stories.
        digests_left = len(selected) - selected.index(summary)
        budget = min(remaining, -(-remaining // digests_left))
        ranked = sorted(
            (story for section in parsed.get("sections", []) for story in section.get("stories", [])),
            key=_story_priority,
        )
        kept = {id(story) for story in ranked[:budget]}
        sections_payload: list[dict[str, Any]] = []
        for section in parsed.get("sections", []):
            stories_payload: list[dict[str, Any]] = []
            for story in section.get("stories", []):
                if id(story) not in kept:
                    continue
                payload: dict[str, Any] = {
                    "id": story.get("id"),
                    "headline": _truncate(str(story.get("headline") or ""), max_text_chars),
                    "notes": [
                        _truncate(str(note), max_text_chars) for note in (story.get("notes") or [])[:notes_per_story]
                    ],
                }
                for key in ("source", "confidence", "top_rank"):
                    if story.get(key) is not None:
                        payload[key] = story[key]
                if story.get("multi_signal"):
                    payload["multi_signal"] = True
                if story.get("tags"):
                    payload["tags"] = story["tags"]
                if story.get("implication"):
                    payload["implication"] = _truncate(str(story["implication"]), max_text_chars)
                stories_payload.append(payload)
                remaining -= 1
                included_stories += 1
            if stories_payload:
                sections_payload.append({"name": section.get("name"), "stories": stories_payload})

        digest_payloads.append(
            {
                "id": summary.get("id"),
                "title": summary.get("title"),
                "generated_date": summary.get("generated_date"),
                "uploaded_at": summary.get("uploaded_at"),
                "updated_at": summary.get("updated_at"),
                "story_count": summary.get("story_count"),
                "sections": sections_payload,
            }
        )

    return {
        "window_days": days,
        "cutoff_date": cutoff,
        "fallback_used": fallback_used,
        "digests": digest_payloads,
        "counts": {
            "digests": len(digest_payloads),
            "stories": included_stories,
        },
    }
