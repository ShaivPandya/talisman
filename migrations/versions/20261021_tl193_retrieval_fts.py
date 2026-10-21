"""Index retrieval chunks for full-text search without an embedding model.

Revision ID: 20261021_tl193
Revises: 20261021_0195
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261021_tl193"
down_revision: str | None = "20261021_0195"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep metadata in the same indexed vector as the chunk. Triggers also cover
    # the offline SQLite importer and direct document metadata updates.
    op.execute("ALTER TABLE retrieval_chunks ALTER COLUMN embedding DROP NOT NULL")
    op.execute("ALTER TABLE retrieval_chunks ADD COLUMN search_vector tsvector")
    op.execute("""
        CREATE FUNCTION retrieval_search_vector(ticker text, doc_type text, heading text, content text)
        RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT setweight(to_tsvector('simple', coalesce(ticker, '') || ' ' || coalesce(doc_type, '')), 'A')
                || setweight(to_tsvector('english', coalesce(heading, '')), 'B')
                || setweight(to_tsvector('english', coalesce(content, '')), 'D')
        $$
    """)
    op.execute("""
        CREATE FUNCTION retrieval_chunks_set_search_vector()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            parent_ticker text;
            parent_doc_type text;
        BEGIN
            -- Serialize against concurrent parent metadata changes so a new
            -- chunk cannot retain a vector built from old ticker/type values.
            SELECT ticker, doc_type INTO parent_ticker, parent_doc_type
            FROM retrieval_documents WHERE doc_id = NEW.doc_id FOR SHARE;
            NEW.search_vector := retrieval_search_vector(parent_ticker, parent_doc_type, NEW.heading, NEW.content);
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER retrieval_chunks_search_vector
        BEFORE INSERT OR UPDATE OF doc_id, heading, content ON retrieval_chunks
        FOR EACH ROW EXECUTE FUNCTION retrieval_chunks_set_search_vector()
    """)
    op.execute("""
        CREATE FUNCTION retrieval_documents_refresh_search_vectors()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE retrieval_chunks
            SET search_vector = retrieval_search_vector(NEW.ticker, NEW.doc_type, heading, content)
            WHERE doc_id = NEW.doc_id;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER retrieval_documents_search_vectors
        AFTER UPDATE OF ticker, doc_type ON retrieval_documents
        FOR EACH ROW
        WHEN (OLD.ticker IS DISTINCT FROM NEW.ticker OR OLD.doc_type IS DISTINCT FROM NEW.doc_type)
        EXECUTE FUNCTION retrieval_documents_refresh_search_vectors()
    """)
    op.execute("""
        UPDATE retrieval_chunks c
        SET search_vector = retrieval_search_vector(d.ticker, d.doc_type, c.heading, c.content)
        FROM retrieval_documents d WHERE d.doc_id = c.doc_id
    """)
    op.execute("ALTER TABLE retrieval_chunks ALTER COLUMN search_vector SET NOT NULL")
    op.execute("CREATE INDEX idx_retrieval_chunks_search_vector ON retrieval_chunks USING gin (search_vector)")


def downgrade() -> None:
    # Restore the old invariant before removing anything. A rollback after new
    # text-only writes requires real embeddings, never fabricated vectors or
    # deleting the user's chunks. Alembic rolls back this migration on failure.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM retrieval_chunks WHERE embedding IS NULL) THEN
                RAISE EXCEPTION 'Backfill missing retrieval embeddings before downgrading TL-193';
            END IF;
        END $$
    """)
    op.execute("ALTER TABLE retrieval_chunks ALTER COLUMN embedding SET NOT NULL")
    op.execute("DROP TRIGGER retrieval_documents_search_vectors ON retrieval_documents")
    op.execute("DROP TRIGGER retrieval_chunks_search_vector ON retrieval_chunks")
    op.execute("DROP FUNCTION retrieval_documents_refresh_search_vectors()")
    op.execute("DROP FUNCTION retrieval_chunks_set_search_vector()")
    op.execute("DROP INDEX idx_retrieval_chunks_search_vector")
    op.execute("ALTER TABLE retrieval_chunks DROP COLUMN search_vector")
    op.execute("DROP FUNCTION retrieval_search_vector(text, text, text, text)")
