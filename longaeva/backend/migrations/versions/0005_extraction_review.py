"""Extraction call cache and versioned review decisions.

Revision ID: 0005_extraction_review
Revises: 0004_run_replay
Create Date: 2026-10-04 08:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_extraction_review"
down_revision: str | None = "0004_run_replay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("review_decision", sa.Column("version", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE review_decision AS rd
        SET version = ranked.rn
        FROM (
            SELECT id, row_number() OVER (
                PARTITION BY observation_id ORDER BY decided_at, id
            ) AS rn
            FROM review_decision
        ) AS ranked
        WHERE rd.id = ranked.id
        """
    )
    op.alter_column("review_decision", "version", existing_type=sa.Integer(), nullable=False)
    op.create_unique_constraint(
        "uq_review_decision_observation_version",
        "review_decision",
        ["observation_id", "version"],
    )

    op.create_table(
        "extraction_call",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("prompt_hash", sa.Text(), nullable=False),
        sa.Column("document_text_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("parsed", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "item_errors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded', 'invalid_response', 'provider_error')",
            name=op.f("ck_extraction_call_status"),
        ),
        sa.ForeignKeyConstraint(
            ["document_text_id"],
            ["document_text.id"],
            name=op.f("fk_extraction_call_document_text_id_document_text"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f("fk_extraction_call_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction_call")),
    )
    op.create_index(
        "uq_extraction_call_succeeded",
        "extraction_call",
        ["provider", "model", "prompt_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'succeeded'"),
    )
    op.create_index(
        "ix_extraction_call_document_text_id",
        "extraction_call",
        ["document_text_id"],
        unique=False,
    )
    op.create_index("ix_extraction_call_job_id", "extraction_call", ["job_id"], unique=False)
    op.create_index(
        "ix_extraction_call_status_created_at",
        "extraction_call",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_extraction_call_status_created_at", table_name="extraction_call")
    op.drop_index("ix_extraction_call_job_id", table_name="extraction_call")
    op.drop_index("ix_extraction_call_document_text_id", table_name="extraction_call")
    op.drop_index("uq_extraction_call_succeeded", table_name="extraction_call")
    op.drop_table("extraction_call")
    op.drop_constraint(
        "uq_review_decision_observation_version",
        "review_decision",
        type_="unique",
    )
    op.drop_column("review_decision", "version")
