"""API health and job endpoints."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from longaeva_app.db.models import Job
from longaeva_app.worker.queue import claim_next_job, execute_job


@pytest.mark.db
def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["alembic_revision"] == "0003_passage_hash"


@pytest.mark.db
def test_create_and_get_job(client: TestClient) -> None:
    created = client.post("/jobs", json={"type": "ping", "payload": {"message": "api"}})
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "queued"
    assert body["type"] == "ping"

    fetched = client.get(f"/jobs/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


@pytest.mark.db
def test_reject_unknown_job_type(client: TestClient) -> None:
    response = client.post("/jobs", json={"type": "not-a-real-type", "payload": {}})
    assert response.status_code == 400


@pytest.mark.db
def test_list_failed_jobs_visible(client: TestClient, test_engine: Engine) -> None:
    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        job = Job(type="no_such_handler", payload={}, status="queued")
        session.add(job)
        session.commit()
        job_id = job.id

    claim_next_job(factory, "api-test")
    execute_job(factory, job_id, "api-test")

    response = client.get("/jobs", params={"status": "failed"})
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert str(job_id) in ids


@pytest.mark.db
def test_job_roundtrip_via_api_and_worker(client: TestClient, test_engine: Engine) -> None:
    created = client.post("/jobs", json={"type": "ping", "payload": {"message": "roundtrip"}})
    assert created.status_code == 201
    job_id = created.json()["id"]

    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    claimed = claim_next_job(factory, "api-worker")
    assert claimed is not None
    assert str(claimed) == job_id
    execute_job(factory, claimed, "api-worker")

    fetched = client.get(f"/jobs/{job_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["status"] == "succeeded"
    assert body["result"]["message"] == "roundtrip"
    assert body["finished_at"] is not None
    assert UUID(job_id)
