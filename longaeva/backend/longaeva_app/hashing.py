"""Canonical JSON and SHA-256 helpers for content hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize ``value`` to a deterministic JSON string (sorted keys, no whitespace)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(data: bytes | str) -> str:
    """Return the lowercase hex SHA-256 digest of ``data``."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    """SHA-256 of the canonical JSON form of ``value`` (stable across key order / round-trips)."""
    return sha256_hex(canonical_json(value))
