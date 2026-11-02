"""Real ontology transactions, concurrent edits, and full-text indexing on disposable Postgres."""

import json
import os
import runpy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg.conninfo import make_conninfo

from api import postgres, research, retrieval
from api import research_processing as processing
from api import research_store as store
from tests.test_chat_attachments import make_pdf
from tests.test_research import ACTOR, FACT, model


@pytest.fixture
def pg_research(monkeypatch, tmp_path):
    url = os.environ.get("TEST_RESEARCH_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_RESEARCH_POSTGRES_URL must point to a disposable Postgres + pgvector database")
    schema = "research_test_" + uuid4().hex
    dsn = make_conninfo(url, options=f"-csearch_path={schema},public")
    postgres.close_pools()
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema)))
        engine = sa.create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn))
        try:
            with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
                for name in (
                    "20260429_0001_gcp_state_schema.py",
                    "20260503_0009_unified_provenance.py",
                    "20260503_0011_temporal_ontology.py",
                    "20260505_0007_ontology_native_retrieval.py",
                    "20261021_tl193_retrieval_fts.py",
                ):
                    runpy.run_path(str(Path("migrations/versions") / name))["upgrade"]()
                # The broader governance migration adds this lineage field alongside unrelated tables.
                conn.exec_driver_sql("ALTER TABLE provenance_links ADD COLUMN lineage_root_id text")
            monkeypatch.setenv("DATABASE_URL", dsn)
            monkeypatch.setenv("STATE_DB_BACKEND", "postgres")
            monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "2")
            monkeypatch.setattr(store, "PROJECT_ROOT", tmp_path)
            import paths

            monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
            monkeypatch.setattr(
                research, "enqueue_registered_job", lambda *a, **kw: ({"job_id": uuid4().hex}, "created")
            )
            monkeypatch.setattr(research, "get_job", lambda _: {"status": "running"})
            monkeypatch.setattr(processing, "selected_provider_for_tier", lambda _: "anthropic")
            monkeypatch.setattr(processing, "model_for_tier", lambda *a, **kw: "test-model")
            yield dsn
        finally:
            postgres.close_pools()
            engine.dispose()
            admin.execute(psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(psycopg.sql.Identifier(schema)))


def test_concurrent_upload_deduplication_and_metadata_updates(pg_research):
    data = make_pdf(FACT)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: store.create(data, "report.pdf", None, 1, ACTOR), range(8)))
    assert sum(created for _, created in outcomes) == 1
    report_id = outcomes[0][0]["id"]
    assert len(store.all_reports()) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: store.mutate(report_id, lambda s: s.update({f"marker_{i}": i})), range(8)))
    state = store.get(report_id)
    assert all(state[f"marker_{i}"] == i for i in range(8))
    with psycopg.connect(pg_research) as conn:
        count = conn.execute(
            "SELECT count(*) FROM ontology_object_versions WHERE object_uid=%s AND tx_to IS NULL",
            (store.uid(report_id),),
        ).fetchone()[0]
    assert count == 1


def test_conversion_index_search_citations_delete_and_transaction_rollback(pg_research, monkeypatch):
    model(monkeypatch)
    result = research.upload(make_pdf(FACT), "random.pdf", None, ACTOR)
    state = store.get(result["report"]["id"])
    req = processing.ResearchJobRequest(report_id=state["id"], token=state["token"], actor=ACTOR)
    assert processing.run_research_job(req, job_id=state["job_id"])["status"] == "ready"
    research.run_index_job(req)
    hits = research.search_research("oil growth forecast")["results"]
    assert hits and any(h["doc_type"] == "research_source" for h in hits)
    assert any("#page=1" in h["citation_url"] for h in hits)
    assert research.list_reports(query="Redistribution")["total"] == 1
    original = store.get(state["id"])
    with pytest.raises(RuntimeError), store.locked(state["id"]) as service:
        altered = {**original, "title": "Must roll back"}
        store._write(service, altered, ACTOR)
        raise RuntimeError("rollback")
    assert store.get(state["id"])["title"] == original["title"]
    research.delete(state["id"], ACTOR)
    assert not research.search_research("oil growth forecast")["results"]
    assert not retrieval.search("oil", doc_types=["research", "research_source"])
    assert store.all_reports() == []
