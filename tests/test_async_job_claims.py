"""Single-owner execution, with optional real Postgres races.

TEST_ASYNC_POSTGRES_URL must point at a disposable database. Tests create an
isolated schema and run the claim migration against existing queued rows.
"""

from __future__ import annotations

import os
import runpy
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from api import async_job_runner as runner
from api import job_queue, job_worker_loop, postgres
from api.job_registry import JobSpec


@pytest.fixture(scope="module")
def async_database():
    import psycopg
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from psycopg.conninfo import make_conninfo

    url = os.getenv("TEST_ASYNC_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_ASYNC_POSTGRES_URL must point at a disposable Postgres database")
    schema = f"tl185_{uuid.uuid4().hex}"
    engine = sa.create_engine(
        sa.engine.make_url(url).set(drivername="postgresql+psycopg"),
        connect_args={"options": f"-csearch_path={schema},public"},
    )
    migration = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "migrations/versions/20261021_0002_async_job_claims.py")
    )
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema)))
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    """CREATE TABLE async_jobs (
                        job_id text PRIMARY KEY, job_type text NOT NULL, status text NOT NULL,
                        payload_json jsonb NOT NULL DEFAULT '{}', result_json jsonb, error text,
                        cache_key text, queue_name text, rq_job_id text, progress_json jsonb,
                        cloud_run_job_name text, created_at timestamptz NOT NULL,
                        started_at timestamptz, completed_at timestamptz, updated_at timestamptz NOT NULL,
                        result_expires_at timestamptz
                    )"""
                )
                conn.exec_driver_sql(
                    """CREATE UNIQUE INDEX uq_async_jobs_active_dedupe ON async_jobs (job_type, cache_key)
                    WHERE status IN ('queued', 'running') AND cache_key IS NOT NULL"""
                )
                conn.exec_driver_sql(
                    """INSERT INTO async_jobs (job_id, job_type, status, created_at, updated_at)
                    VALUES ('before-migration', 'analyzer', 'queued', now(), now())"""
                )
                with Operations.context(MigrationContext.configure(conn)):
                    migration["upgrade"]()
                    row = conn.exec_driver_sql("SELECT claimed_by, attempt FROM async_jobs").one()
                    assert row == (None, 0)
                    migration["downgrade"]()
                    assert {column["name"] for column in sa.inspect(conn).get_columns("async_jobs")} >= {
                        "job_id",
                        "status",
                    }
                    assert "attempt" not in {column["name"] for column in sa.inspect(conn).get_columns("async_jobs")}
                    migration["upgrade"]()
            yield make_conninfo(url, options=f"-csearch_path={schema},public")
        finally:
            postgres.close_pools()
            engine.dispose()
            admin.execute(psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(psycopg.sql.Identifier(schema)))


@pytest.fixture(params=["memory", "postgres"])
def job_store(request, monkeypatch):
    postgres.close_pools()
    job_queue.clear_memory_jobs()
    monkeypatch.setattr(runner, "_emit_job_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "init_sentry", lambda **kwargs: None)
    monkeypatch.setattr(runner, "capture_exception", lambda *args, **kwargs: None)
    monkeypatch.setattr("api.logging_config.configure_logging", lambda **kwargs: None)
    monkeypatch.setenv("ASYNC_JOB_BACKEND", "local")
    if request.param == "postgres":
        import pgvector.psycopg

        monkeypatch.setenv("DATABASE_URL", request.getfixturevalue("async_database"))
        monkeypatch.setenv("ASYNC_JOB_BACKEND", "postgres")
        monkeypatch.setenv("POSTGRES_POOL_MIN_SIZE", "2")
        monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "2")
        # The job table uses no vectors; still exercise the real shared pool.
        monkeypatch.setattr(pgvector.psycopg, "register_vector", lambda conn: None)
        with postgres.connect() as conn:
            conn.execute("TRUNCATE async_jobs")
            conn.commit()
    yield request.param
    postgres.close_pools()
    job_queue.clear_memory_jobs()


def _enqueue(job_type="analyzer"):
    row, _ = job_queue.create_or_reuse_job(job_type, queue_name=job_type, reuse_completed=False)
    return row


@pytest.mark.parametrize("job_type", ["analyzer", "ontology"])
@pytest.mark.parametrize("first", ["warm", "cloud_run"])
def test_warm_worker_and_cloud_run_execute_and_complete_once(job_store, monkeypatch, job_type, first):
    row = _enqueue(job_type)
    entered = threading.Event()
    release = threading.Event()
    calls = []
    completed = []
    original_complete = runner.complete_job

    def compute(_req):
        calls.append(row["job_id"])
        entered.set()
        assert release.wait(5)
        return {"winner": first}

    def complete(job_id, result, **kwargs):
        completed.append(job_id)
        original_complete(job_id, result, **kwargs)

    monkeypatch.setattr(runner, "get_job_spec", lambda kind: JobSpec(kind, None, "test.compute", None))
    monkeypatch.setattr(runner, "import_string", lambda path: compute)
    monkeypatch.setattr(runner, "complete_job", complete)

    def warm():
        return job_worker_loop.run_once(job_type=job_type, queue_name=job_type)

    def cloud():
        return runner.main(["run", row["job_id"]])

    with ThreadPoolExecutor(2) as executor:
        winner = executor.submit(warm if first == "warm" else cloud)
        try:
            assert entered.wait(5)
            loser = executor.submit(cloud if first == "warm" else warm)
            # A loser must exit while the owner is still computing.
            assert loser.result(timeout=3) == (0 if first == "warm" else False)
        finally:
            release.set()
        assert winner.result(timeout=5) == (True if first == "warm" else 0)

    stored = job_queue.get_job(row["job_id"])
    assert stored["status"] == "completed"
    assert stored["result_json"] == {"winner": first}
    assert stored["attempt"] == 1
    assert stored["claimed_by"]
    assert calls == completed == [row["job_id"]]
    # A later Cloud Run task retry must also be a successful no-op.
    assert cloud() == 0
    assert calls == completed == [row["job_id"]]


def test_simultaneous_claims_have_one_owner(job_store):
    row = _enqueue()
    barrier = threading.Barrier(8)

    def claim(index):
        barrier.wait(timeout=5)
        if index % 2:
            return job_queue.claim_queued_job("analyzer", queue_name="analyzer")
        return job_queue.claim_job(row["job_id"])

    with ThreadPoolExecutor(8) as executor:
        claimed = [value for value in executor.map(claim, range(8)) if value is not None]
    assert len(claimed) == 1
    assert claimed[0]["job_id"] == row["job_id"]
    assert claimed[0]["attempt"] == 1
    assert claimed[0]["claimed_by"]
    assert claimed[0]["started_at"] is not None
    assert job_queue.get_job(row["job_id"])["claimed_by"] == claimed[0]["claimed_by"]


@pytest.mark.parametrize("status", ["running", "completed", "failed", "cancelled"])
def test_claim_never_reopens_an_owned_or_terminal_job(job_store, status):
    row = _enqueue()
    owner = job_queue.claim_job(row["job_id"])
    if status == "completed":
        job_queue.complete_job(row["job_id"], {"original": True})
    elif status == "failed":
        job_queue.fail_job(row["job_id"], "original failure")
    elif status == "cancelled":
        job_queue.cancel_job(row["job_id"])
    before = job_queue.get_job(row["job_id"])
    assert job_queue.claim_job(row["job_id"]) is None
    assert job_queue.claim_queued_job("analyzer", queue_name="analyzer") is None
    assert runner.main(["run", row["job_id"]]) == 0
    assert job_queue.get_job(row["job_id"]) == before
    assert before["claimed_by"] == owner["claimed_by"]


def test_cancel_after_claim_does_not_compute(job_store, monkeypatch):
    row = _enqueue()
    claimed = job_queue.claim_job(row["job_id"])
    job_queue.cancel_job(row["job_id"])
    monkeypatch.setattr(runner, "import_string", lambda path: pytest.fail("cancelled job computed"))
    assert runner.execute_claimed(claimed) is None
    assert job_queue.get_job(row["job_id"])["status"] == "cancelled"


def test_claim_missing_job_is_a_successful_noop(job_store):
    assert job_queue.claim_job("missing") is None
    assert runner.main(["run", "missing"]) == 0


@pytest.mark.parametrize("dispatch", ["inline", "local"])
def test_inline_and_local_dispatch_claim_before_compute(job_store, monkeypatch, dispatch):
    done = threading.Event()
    observed = []

    def compute(_req, *, job_id):
        observed.append(job_queue.get_job(job_id))
        done.set()
        return {"ok": True}

    monkeypatch.setenv("ASYNC_DISPATCH_BACKEND_ANALYZER", dispatch)
    monkeypatch.setattr(runner, "get_job_spec", lambda kind: JobSpec(kind, None, "test.compute", None, queue_name=kind))
    monkeypatch.setattr(runner, "import_string", lambda path: compute)
    if dispatch == "local":
        # Join the real local thread before the fixture restores the database.
        original_thread = threading.Thread
        threads = []

        def thread(*args, **kwargs):
            created = original_thread(*args, **kwargs)
            threads.append(created)
            return created

        monkeypatch.setattr(runner.threading, "Thread", thread)
    row, _ = runner.enqueue_registered_job("analyzer", {})
    assert done.wait(5)
    if dispatch == "local":
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive()
    assert len(observed) == 1
    assert observed[0]["status"] == "running"
    assert observed[0]["attempt"] == 1
    assert observed[0]["claimed_by"]
    assert job_queue.get_job(row["job_id"])["status"] == "completed"
