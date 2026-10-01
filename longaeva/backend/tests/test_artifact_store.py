"""Local artifact store tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from longaeva_app.hashing import sha256_hex
from longaeva_app.storage.local import ArtifactStoreError, LocalArtifactStore


def test_put_original_content_addressed(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    data = b"hello-visa"
    key, digest = store.put_original(data)
    assert digest == sha256_hex(data)
    assert key == f"originals/{digest[:2]}/{digest}"
    assert store.read_bytes(key) == data
    # Idempotent on same bytes
    key2, digest2 = store.put_original(data)
    assert (key2, digest2) == (key, digest)


def test_write_once_rejects_overwrite(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    key = store.write_once("runs/abc/outputs.json", b'{"ok":true}')
    assert key == "runs/abc/outputs.json"
    with pytest.raises(ArtifactStoreError):
        store.write_once("runs/abc/outputs.json", b'{"ok":false}')


def test_rejects_absolute_and_traversal_keys(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    with pytest.raises(ArtifactStoreError):
        store.resolve_key("/tmp/evil")
    with pytest.raises(ArtifactStoreError):
        store.resolve_key("../outside")
    with pytest.raises(ArtifactStoreError):
        store.write_once("originals/not-allowed.bin", b"x")
