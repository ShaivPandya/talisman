"""State storage client lifecycle without cloud credentials or network access."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from google.cloud import storage

from api import state_storage


def test_gcs_client_is_initialized_once_under_concurrency(monkeypatch):
    monkeypatch.setattr(state_storage, "_client", None)
    monkeypatch.setenv("GCS_STATE_BUCKET", "test-bucket")
    started = threading.Event()
    release = threading.Event()
    attempts = threading.Condition()
    callers = 0
    constructions = []
    client_lock = threading.Lock()

    class ObservedLock:
        def __enter__(self):
            nonlocal callers
            with attempts:
                callers += 1
                attempts.notify_all()
            client_lock.acquire()

        def __exit__(self, *_args):
            client_lock.release()

    client = SimpleNamespace(bucket=lambda name: name)

    def construct_client():
        constructions.append(client)
        started.set()
        assert release.wait(5)
        return client

    monkeypatch.setattr(state_storage, "_client_lock", ObservedLock())
    monkeypatch.setattr(storage, "Client", construct_client)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(state_storage._bucket) for _ in range(8)]
        try:
            assert started.wait(5)
            with attempts:
                assert attempts.wait_for(lambda: callers == 8, timeout=5)
            assert len(constructions) == 1
        finally:
            release.set()
        assert [future.result(timeout=5) for future in futures] == ["test-bucket"] * 8
    assert constructions == [client]


def test_gcs_client_initialization_failure_can_retry_and_bucket_remains_dynamic(monkeypatch):
    monkeypatch.setattr(state_storage, "_client", None)
    monkeypatch.setenv("GCS_STATE_BUCKET", "first-bucket")
    calls = 0

    def construct_client():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("credentials unavailable")
        return SimpleNamespace(bucket=lambda name: name)

    monkeypatch.setattr(storage, "Client", construct_client)
    with pytest.raises(RuntimeError, match="credentials unavailable"):
        state_storage._bucket()
    assert state_storage._client is None
    assert state_storage._bucket() == "first-bucket"
    monkeypatch.setenv("GCS_STATE_BUCKET", "second-bucket")
    assert state_storage._bucket() == "second-bucket"
    assert calls == 2


def test_local_storage_does_not_construct_cloud_client(monkeypatch, tmp_path):
    monkeypatch.setattr(state_storage, "_client", None)
    monkeypatch.setenv("STATE_STORAGE_BACKEND", "local")

    def unexpected_client():
        raise AssertionError("local storage must not initialize a cloud client")

    monkeypatch.setattr(storage, "Client", unexpected_client)
    path = tmp_path / "state.txt"
    assert state_storage.write_text(path, "unused", "local value") == str(path)
    assert state_storage.exists_text(path, "unused")
    assert state_storage.read_text(path, "unused") == "local value"
    assert state_storage.read_bytes(path, "unused") == b"local value"
    assert state_storage.object_updated(path, "unused") is not None
    assert state_storage.delete_file(path, "unused")
    assert state_storage._client is None


def test_missing_bucket_is_reported_before_client_initialization(monkeypatch):
    monkeypatch.setattr(state_storage, "_client", None)
    monkeypatch.delenv("GCS_STATE_BUCKET", raising=False)

    def unexpected_client():
        raise AssertionError("validate the bucket before initializing credentials")

    monkeypatch.setattr(storage, "Client", unexpected_client)
    with pytest.raises(state_storage.StateStorageConfigError, match="GCS_STATE_BUCKET"):
        state_storage._bucket()
