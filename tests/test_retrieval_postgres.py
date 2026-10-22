"""Real full-text ranking, migrations and writes on disposable Postgres.

TEST_POSTGRES_URL opts in. Every test uses its own schema and the real pool.
"""

import os
import runpy
import uuid
from pathlib import Path

import psycopg
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg.conninfo import make_conninfo

from api import postgres, retrieval

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
FTS_MIGRATION = "20261021_tl193_retrieval_fts.py"


def migrate(url, filename, direction="upgrade"):
    engine = sa.create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(url))
    try:
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            runpy.run_path(str(MIGRATIONS / filename))[direction]()
    finally:
        engine.dispose()


@pytest.fixture
def pg_retrieval(monkeypatch):
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL must point at disposable Postgres + pgvector")
    schema = f"tl193_test_{uuid.uuid4().hex}"
    dsn = make_conninfo(url, options=f"-csearch_path={schema},public")
    postgres.close_pools()
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema)))
        try:
            migrate(dsn, "20260429_0001_gcp_state_schema.py")
            migrate(dsn, "20260505_0007_ontology_native_retrieval.py")
            # Rows predate the new column; the best matches are beyond row 1000.
            with psycopg.connect(dsn) as conn:
                conn.execute("""
                    INSERT INTO retrieval_documents (doc_id, doc_type, ticker, content, created_at, updated_at)
                    VALUES ('legacy', 'thesis', 'NVDA', 'Legacy document', now(), now())
                """)
                conn.execute("""
                    INSERT INTO retrieval_chunks (chunk_id, doc_id, chunk_index, content, heading, embedding)
                    SELECT 'legacy-' || i, 'legacy', i,
                           CASE WHEN i >= 1200 THEN 'zephyr catalyst' ELSE 'Ordinary portfolio allocation' END,
                           CASE WHEN i = 1202 THEN 'zephyr catalyst' ELSE NULL END,
                           array_fill(1::real, ARRAY[384])::vector
                    FROM generate_series(1, 1202) i
                """)
            migrate(dsn, FTS_MIGRATION)
            monkeypatch.setenv("DATABASE_URL", dsn)
            monkeypatch.setenv("STATE_DB_BACKEND", "postgres")
            monkeypatch.setenv("POSTGRES_POOL_MIN_SIZE", "1")
            monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "1")
            monkeypatch.setattr(retrieval, "_embed", lambda _: pytest.fail("embedding model was loaded"))
            yield dsn
        finally:
            postgres.close_pools()
            admin.execute(psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(psycopg.sql.Identifier(schema)))


def test_backfill_ranks_entire_corpus_and_breaks_ties(pg_retrieval):
    hits = retrieval.search("Tell me about zephyr catalysts", top_k=3)
    assert [h["chunk_id"] for h in hits] == ["legacy-1202", "legacy-1200", "legacy-1201"]
    assert hits[0]["relevance_score"] > hits[1]["relevance_score"]
    assert all(h["retrieval_mode"] == "full_text" and "fallback_reason" not in h for h in hits)
    assert len(retrieval.search("zephyr", top_k=1)) == 1
    assert retrieval.search("unfindableword") == []
    assert retrieval.search("& | ! : * ' \" \\ ()") == []
    assert retrieval.search("the and of") == []


def test_index_reindex_filters_staleness_and_citations(pg_retrieval):
    metadata = dict(
        doc_id="new",
        ticker="ON",
        source_path="research/new.md",
        object_uid="object-1",
        source_record_id="source-1",
        citation_span_start=7,
        citation_span_end=42,
        permission_scope="owner",
        freshness_as_of="2026-10-21T12:00:00+00:00",
    )
    retrieval.index_document("thesis", "## Quartz\nQuartz margin outlook", **metadata)
    hit = retrieval.search("quartz", tickers=["on"], doc_types=["thesis"])[0]
    assert hit["doc_id"] == "new"
    assert hit["object_uid"] == "object-1"
    assert hit["source_record_id"] == "source-1"
    assert hit["citation_span"] == {"start": 7, "end": 42}
    assert hit["permission_scope"] == "owner"
    assert hit["source_path"] == "research/new.md"
    assert hit["content_hash"] and hit["source_registry"]
    assert retrieval.search("ON")[0]["doc_id"] == "new"  # English stop-word ticker
    assert retrieval.search("quartz", doc_types=["conversation_summary"]) == []
    assert retrieval.search("quartz", tickers=["NVDA"]) == []
    with postgres.connect(read_only=True) as conn:
        assert (
            conn.execute("SELECT embedding FROM retrieval_chunks WHERE doc_id = 'new'").fetchone()["embedding"] is None
        )
    retrieval.index_document("conversation_summary", "Cobalt margins", **metadata)
    assert retrieval.search("quartz") == []
    assert retrieval.search("cobalt", doc_types=["conversation_summary"])[0]["doc_id"] == "new"
    assert retrieval._pg_search([1.0] * 384, doc_types=None, tickers=["ON"], top_k=5) == []
    retrieval.index_document("conversation_summary", "Cobalt margins", is_stale=True, **metadata)
    assert retrieval.search("cobalt") == []
    assert retrieval.delete_document("new")
    assert retrieval.search("ON") == []


def test_database_updates_keep_vectors_current(pg_retrieval):
    with postgres.connect() as conn:
        conn.execute("UPDATE retrieval_documents SET ticker = 'IT', doc_type = 'weekly_report' WHERE doc_id = 'legacy'")
        conn.execute(
            "UPDATE retrieval_chunks SET content = 'cobalt catalysts', heading = NULL WHERE chunk_index >= 1200"
        )
        conn.commit()
    assert retrieval.search("NVDA") == []
    assert retrieval.search("zephyr") == []
    assert retrieval.search("IT")[0]["ticker"] == "IT"
    assert retrieval.search("weekly_report")[0]["doc_type"] == "weekly_report"
    assert len(retrieval.search("cobalt", tickers=["IT"])) == 3


def test_migration_downgrade_preserves_data_and_can_upgrade_again(pg_retrieval):
    migrate(pg_retrieval, FTS_MIGRATION, "downgrade")
    migrate(pg_retrieval, FTS_MIGRATION)
    assert len(retrieval.search("zephyr")) == 3
    retrieval.index_document("thesis", "New unembedded document", doc_id="unembedded")
    with pytest.raises(sa.exc.DatabaseError, match="Backfill missing retrieval embeddings"):
        migrate(pg_retrieval, FTS_MIGRATION, "downgrade")
    assert retrieval.search("unembedded")[0]["doc_id"] == "unembedded"


def test_full_text_index_is_used(pg_retrieval):
    with postgres.connect() as conn:
        conn.execute("ANALYZE retrieval_chunks")
        plan = conn.execute("""
            EXPLAIN (ANALYZE, FORMAT JSON)
            SELECT chunk_id FROM retrieval_chunks
            WHERE search_vector @@ plainto_tsquery('english', 'zephyr')
        """).fetchone()["QUERY PLAN"]
    assert "idx_retrieval_chunks_search_vector" in str(plan)
