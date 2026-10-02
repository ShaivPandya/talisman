"""Add normalized passage hash for DR-08 dedup (LON-13).

Revision ID: 0003_passage_hash
Revises: 0002_core
Create Date: 2026-10-02 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_passage_hash"
down_revision: str | None = "0002_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_text",
        sa.Column(
            "text_hash",
            sa.Text(),
            sa.Computed("md5(lower(btrim(regexp_replace(text, '\\s+', ' ', 'g'))))", persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_document_text_text_hash", "document_text", ["text_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_document_text_text_hash", table_name="document_text")
    op.drop_column("document_text", "text_hash")
