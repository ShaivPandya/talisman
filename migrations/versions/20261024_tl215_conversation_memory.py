"""Persist per-chat memory controls and index live, editable summaries.

Revision ID: 20261024_tl215
Revises: 20261024_tl214
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261024_tl215"
down_revision: str | None = "20261024_tl214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_sessions", sa.Column("memory_enabled", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "conversation_sessions", sa.Column("memory_excluded", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("conversation_sessions", sa.Column("memory_summary", sa.Text(), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        text = "(CASE WHEN memory_summary IS NOT NULL THEN memory_summary ELSE COALESCE(memory_summary, NULLIF(summary, ''), rolling_summary, '') || ' ' || COALESCE(key_tickers, '') || ' ' || COALESCE(key_topics, '') END)"
        op.execute(
            "CREATE INDEX idx_conversation_memory_search ON conversation_sessions USING gin "
            f"((to_tsvector('english', {text}) || to_tsvector('simple', {text}))) WHERE memory_excluded = 0"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("idx_conversation_memory_search", table_name="conversation_sessions")
    for column in ("memory_summary", "memory_excluded", "memory_enabled"):
        op.drop_column("conversation_sessions", column)
