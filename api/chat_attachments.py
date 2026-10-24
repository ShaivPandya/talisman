"""Chat attachments: uploads are checked once, stored apart from the messages that cite them.

A message row keeps only a small descriptor (id, name, type, size). The bytes live in state storage
(local disk or GCS) under ``chat_attachments/<id>/`` and are read just before a provider call, so they
never enter request bodies, job payloads, trajectories or the message table.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from api.agent_models import MAX_ATTACHMENTS_PER_MESSAGE, AgentChatRequest
from api.exceptions import ValidationError
from api.state_storage import (
    delete_file,
    exists_text,
    list_keys,
    object_updated,
    read_bytes,
    read_text,
    use_gcs_state,
    write_bytes,
    write_text,
)
from paths import PROJECT_ROOT

logger = logging.getLogger("api.chat_attachments")

AttachmentKind = Literal["pdf", "image", "csv"]

ATTACHMENT_PREFIX = "chat_attachments"
# Only used by the local storage backend. ``tmp/`` is gitignored.
ATTACHMENT_DIR = PROJECT_ROOT / "tmp" / ATTACHMENT_PREFIX

MIB = 1024 * 1024
MAX_UPLOAD_BYTES: dict[str, int] = {"pdf": 20 * MIB, "image": 5 * MIB, "csv": 2 * MIB}
# PDFs and images travel base64-encoded, and providers cap a request near 32 MB.
MAX_REQUEST_BINARY_BYTES = 20 * MIB
CSV_TEXT_CHARS = 100_000
PDF_TEXT_CHARS = 120_000
PDF_TEXT_MAX_PAGES = 150
# An upload that no stored message cites is deleted after this long. It outlasts a draft or a queued
# message waiting in a browser; 0 turns the sweep off.
ORPHAN_TTL_ENV = "CHAT_ATTACHMENT_ORPHAN_TTL_HOURS"
DEFAULT_ORPHAN_TTL_HOURS = 24 * 7
SWEEP_BATCH_LIMIT = 500
SUPPORTED_TYPES_HINT = "Attach a PDF, a PNG, JPEG or WebP image, or a CSV file."

_ID_RX = re.compile(r"^[0-9a-f]{32}$")
_META_NAME = "meta.json"
_DATA_NAME = "data.bin"
_PNG = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class Attachment:
    id: str
    name: str
    mime_type: str
    kind: AttachmentKind
    size: int
    sha256: str

    def descriptor(self) -> dict[str, Any]:
        """What a message row and the client see: metadata only."""
        return asdict(self)

    @property
    def is_binary(self) -> bool:
        return self.kind != "csv"


def _paths(attachment_id: str, name: str) -> tuple[Path, str]:
    key = f"{ATTACHMENT_PREFIX}/{attachment_id}/{name}"
    return ATTACHMENT_DIR / attachment_id / name, key


def _safe_name(raw: str | None, kind: AttachmentKind, mime_type: str) -> str:
    name = re.split(r"[\\/]", str(raw or ""))[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip().strip(".")
    if not name:
        extension = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(
            mime_type, "csv"
        )
        name = f"attachment.{extension}"
    return name[:120]


def sniff_attachment(data: bytes, *, filename: str = "", content_type: str = "") -> tuple[AttachmentKind, str]:
    """The attachment's kind and MIME type, from its bytes rather than the name the browser sent."""
    if not data:
        raise ValidationError("The file is empty.")
    if data.startswith(b"%PDF-"):
        return "pdf", "application/pdf"
    if data.startswith(_PNG):
        return "image", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "image/webp"
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if (filename.lower().endswith(".csv") or declared in {"text/csv", "application/csv"}) and b"\x00" not in data[
        :8192
    ]:
        return "csv", "text/csv"
    raise ValidationError(f"Unsupported file type. {SUPPORTED_TYPES_HINT}")


def store_attachment(data: bytes, *, filename: str = "", content_type: str = "") -> Attachment:
    """Validate and store one upload. Raises ``ValidationError`` (422) for a file chat cannot use."""
    kind, mime_type = sniff_attachment(data, filename=filename, content_type=content_type)
    limit = MAX_UPLOAD_BYTES[kind]
    if len(data) > limit:
        label = {"pdf": "PDF", "image": "image", "csv": "CSV file"}[kind]
        raise ValidationError(f"That {label} is larger than the {limit // MIB} MiB limit.")
    attachment = Attachment(
        id=uuid.uuid4().hex,
        name=_safe_name(filename, kind, mime_type),
        mime_type=mime_type,
        kind=kind,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    data_path, data_key = _paths(attachment.id, _DATA_NAME)
    write_bytes(data_path, data_key, data, content_type=mime_type)
    meta_path, meta_key = _paths(attachment.id, _META_NAME)
    try:
        write_text(
            meta_path,
            meta_key,
            json.dumps({**attachment.descriptor(), "created_at": datetime.now(UTC).isoformat()}),
            content_type="application/json",
        )
    except Exception:
        # Without its metadata the file can never be cited, so do not leave the bytes behind.
        try:
            delete_file(data_path, data_key)
        except Exception:
            logger.warning("Could not remove the bytes of a failed upload %s", attachment.id, exc_info=True)
        raise
    return attachment


def load_attachment(attachment_id: object) -> Attachment | None:
    """The stored attachment with this id, or None when the id is malformed or names nothing."""
    if not isinstance(attachment_id, str) or not _ID_RX.match(attachment_id):
        return None
    meta_path, meta_key = _paths(attachment_id, _META_NAME)
    try:
        if not exists_text(meta_path, meta_key):
            return None
        meta = json.loads(read_text(meta_path, meta_key))
        return Attachment(
            id=attachment_id,
            name=str(meta["name"]),
            mime_type=str(meta["mime_type"]),
            kind=meta["kind"],
            size=int(meta["size"]),
            sha256=str(meta["sha256"]),
        )
    except Exception:
        logger.warning("Could not read attachment %s", attachment_id, exc_info=True)
        return None


def read_attachment_bytes(attachment: Attachment) -> bytes:
    path, key = _paths(attachment.id, _DATA_NAME)
    return read_bytes(path, key)


def resolve_attachments(ids: Iterable[str]) -> list[Attachment]:
    """The attachments a new message cites. Unknown ids and oversized combinations are rejected."""
    found: list[Attachment] = []
    for attachment_id in dict.fromkeys(ids):
        attachment = load_attachment(attachment_id)
        if attachment is None:
            raise ValidationError("An attached file is no longer available. Attach it again.")
        found.append(attachment)
    if len(found) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise ValidationError(f"Attach at most {MAX_ATTACHMENTS_PER_MESSAGE} files to one message.")
    if sum(a.size for a in found if a.is_binary) > MAX_REQUEST_BINARY_BYTES:
        raise ValidationError(
            f"The attached PDFs and images are larger than {MAX_REQUEST_BINARY_BYTES // MIB} MiB together."
        )
    return found


def orphan_ttl_seconds() -> int:
    raw = (os.getenv(ORPHAN_TTL_ENV) or "").strip()
    try:
        hours = int(raw) if raw else DEFAULT_ORPHAN_TTL_HOURS
    except ValueError:
        hours = DEFAULT_ORPHAN_TTL_HOURS
    return max(0, hours) * 3600


def _stored_ids() -> list[str]:
    if use_gcs_state():
        keys = list_keys(f"{ATTACHMENT_PREFIX}/")
        found = (key.split("/") for key in keys)
        return sorted({parts[1] for parts in found if len(parts) == 3 and _ID_RX.match(parts[1])})
    if not ATTACHMENT_DIR.is_dir():
        return []
    return sorted(path.name for path in ATTACHMENT_DIR.iterdir() if path.is_dir() and _ID_RX.match(path.name))


def _uploaded_at(attachment_id: str) -> datetime | None:
    """When the upload happened: from its metadata, or from the bytes when the metadata never landed."""
    meta_path, meta_key = _paths(attachment_id, _META_NAME)
    try:
        if exists_text(meta_path, meta_key):
            created = json.loads(read_text(meta_path, meta_key)).get("created_at")
            if created:
                return datetime.fromisoformat(created)
    except Exception:
        logger.debug("Could not read the upload time of attachment %s", attachment_id, exc_info=True)
    data_path, data_key = _paths(attachment_id, _DATA_NAME)
    return object_updated(data_path, data_key)


def _remove(attachment_id: str) -> bool:
    removed = False
    for name in (_META_NAME, _DATA_NAME):  # metadata first: without it the file can no longer be cited
        path, key = _paths(attachment_id, name)
        try:
            removed = delete_file(path, key) or removed
        except Exception:
            logger.warning("Could not delete %s of attachment %s", name, attachment_id, exc_info=True)
            return False
    if not use_gcs_state():
        try:
            (ATTACHMENT_DIR / attachment_id).rmdir()
        except OSError:
            pass
    return removed


def sweep_orphaned_attachments(
    *, max_age_seconds: int | None = None, limit: int = SWEEP_BATCH_LIMIT, now: datetime | None = None
) -> int:
    """Delete uploads that no stored message cites and that are older than the retention period.

    Uploads abandoned in the composer, and files of deleted conversations, end up here. Returns how many
    were removed, at most ``limit`` per call. If the messages cannot be read, nothing is deleted and the
    error is raised.
    """
    ttl = orphan_ttl_seconds() if max_age_seconds is None else max_age_seconds
    if ttl <= 0:
        return 0
    from api import memory_db

    in_use = memory_db.attachment_ids_in_use()
    now = now or datetime.now(UTC)
    removed = 0
    for attachment_id in _stored_ids():
        if removed >= limit:
            break
        if attachment_id in in_use:
            continue
        uploaded = _uploaded_at(attachment_id)
        if uploaded is not None and (now - uploaded).total_seconds() <= ttl:
            continue
        removed += _remove(attachment_id)
    return removed


def attachments_from_descriptors(descriptors: object) -> list[Attachment]:
    """Re-open the attachments a stored message cites. Ones that are gone are skipped."""
    if not isinstance(descriptors, Sequence) or isinstance(descriptors, (str, bytes)):
        return []
    found = (load_attachment(d.get("id")) for d in descriptors if isinstance(d, Mapping))
    return [a for a in found if a is not None]


def turn_attachments(req: AgentChatRequest, reused_user: Mapping[str, Any] | None = None) -> list[Attachment]:
    """The files a turn's user message carries, read from storage once per request.

    A regenerated answer replies to a stored question, so it carries that question's own files.
    """
    if reused_user is not None:
        return attachments_from_descriptors(reused_user.get("attachments"))
    if req._attachments is None:
        req._attachments = resolve_attachments(req.attachment_ids)
    return list(req._attachments)


# ---------------------------------------------------------------------------
# Content blocks. ``raw_conversation`` holds Anthropic-shaped blocks; the OpenAI, Gemini and
# text-only conversions below translate them, so the conversation is built once per turn.
# ---------------------------------------------------------------------------


def csv_text(data: bytes, name: str) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    total_rows = text.count("\n") + 1
    if len(text) > CSV_TEXT_CHARS:
        text = text[: text.rfind("\n", 0, CSV_TEXT_CHARS) if "\n" in text[:CSV_TEXT_CHARS] else CSV_TEXT_CHARS]
        shown = text.count("\n") + 1
        text += f"\n[Truncated: showing the first {shown} of {total_rows} rows]"
    return f'<attachment name="{name}" type="text/csv">\n{text}\n</attachment>'


def omitted_note(attachment: Attachment, reason: str) -> dict[str, Any]:
    return {"type": "text", "text": f'[Attached {attachment.kind} "{attachment.name}" {reason}]'}


def attachment_block(attachment: Attachment, *, binary_left: int) -> tuple[dict[str, Any], int]:
    """One content block for an attachment, and the binary budget it used."""
    if attachment.is_binary and attachment.size > binary_left:
        return omitted_note(
            attachment, "is not included: too much attached material for one request. Attach it again to ask about it."
        ), 0
    try:
        data = read_attachment_bytes(attachment)
    except Exception:
        logger.warning("Attachment %s could not be read", attachment.id, exc_info=True)
        return omitted_note(attachment, "is no longer available."), 0
    if attachment.kind == "csv":
        return {"type": "text", "text": csv_text(data, attachment.name)}, 0
    source = {"type": "base64", "media_type": attachment.mime_type, "data": base64.b64encode(data).decode("ascii")}
    if attachment.kind == "pdf":
        return {"type": "document", "source": source, "title": attachment.name}, attachment.size
    return {"type": "image", "source": source}, attachment.size


def user_content(
    text: str, attachments: Sequence[Attachment], *, binary_left: int
) -> tuple[str | list[dict[str, Any]], int]:
    """A user turn's content: attachments first, then the text. Plain text when nothing is attached."""
    if not attachments:
        return text, 0
    blocks: list[dict[str, Any]] = []
    used = 0
    for attachment in attachments:
        block, size = attachment_block(attachment, binary_left=binary_left - used)
        blocks.append(block)
        used += size
    blocks.append({"type": "text", "text": text})
    return blocks, used


# ---------------------------------------------------------------------------
# Provider conversions for list-valued content.
# ---------------------------------------------------------------------------


def _data_url(source: Mapping[str, Any]) -> str:
    return f"data:{source.get('media_type')};base64,{source.get('data')}"


def openai_content(content: Sequence[Any], role: object) -> list[Any]:
    text_type = "output_text" if role == "assistant" else "input_text"
    out: list[Any] = []
    for block in content:
        kind = block.get("type") if isinstance(block, Mapping) else None
        if kind == "text":
            out.append({"type": text_type, "text": block.get("text", "")})
        elif kind == "document":
            out.append(
                {
                    "type": "input_file",
                    "filename": block.get("title") or "document.pdf",
                    "file_data": _data_url(block["source"]),
                }
            )
        elif kind == "image":
            out.append({"type": "input_image", "image_url": _data_url(block["source"])})
        else:
            out.append(block)
    return out


def gemini_parts(content: Sequence[Any]) -> list[Any]:
    out: list[Any] = []
    for block in content:
        kind = block.get("type") if isinstance(block, Mapping) else None
        if kind == "text":
            out.append({"text": block.get("text", "")})
        elif kind in {"document", "image"}:
            source = block["source"]
            out.append({"inline_data": {"mime_type": source.get("media_type"), "data": source.get("data")}})
        else:
            out.append(block)
    return out


@lru_cache(maxsize=4)
def _pdf_text_for_digest(digest: str, data: bytes) -> str:
    try:
        from pdfminer.high_level import extract_text

        text = extract_text(io.BytesIO(data), maxpages=PDF_TEXT_MAX_PAGES)
    except Exception:
        logger.warning("PDF text extraction failed", exc_info=True)
        return ""
    return text.strip()[:PDF_TEXT_CHARS]


def text_content(block: Mapping[str, Any]) -> str:
    """Text a model that cannot read files gets in place of an attachment block."""
    kind = block.get("type")
    if kind in {"text", "input_text", "output_text"}:
        return str(block.get("text") or "")
    if kind == "document":
        title = block.get("title") or "document"
        try:
            data = base64.b64decode(block["source"]["data"])
        except Exception:
            data = b""
        text = _pdf_text_for_digest(hashlib.sha256(data).hexdigest(), data) if data else ""
        if text:
            return f'<attachment name="{title}" type="application/pdf">\n{text}\n</attachment>'
        return f'[Attached PDF "{title}": its text could not be read]'
    if kind == "image":
        return "[Attached image omitted: this model cannot read images]"
    return ""
