"""Pin run interventions and record paired baseline runs.

Revision ID: 0006_scenario_pairs
Revises: 0005_extraction_review
Create Date: 2026-10-04 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_scenario_pairs"
down_revision: str | None = "0005_extraction_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SHA-256 of canonical JSON ``[]``. Must match ``EMPTY_INTERVENTIONS_HASH``.
_EMPTY_INTERVENTIONS_HASH = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"


def upgrade() -> None:
    op.add_column(
        "run",
        sa.Column(
            "interventions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "run",
        sa.Column(
            "interventions_hash",
            sa.Text(),
            server_default=sa.text(f"'{_EMPTY_INTERVENTIONS_HASH}'"),
            nullable=False,
        ),
    )
    op.add_column("run", sa.Column("baseline_run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_run_baseline_run_id", "run", ["baseline_run_id"], unique=False)
    op.create_foreign_key(
        "fk_run_baseline_run_id_run",
        "run",
        "run",
        ["baseline_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_run_baseline_run_id_run", "run", type_="foreignkey")
    op.drop_index("ix_run_baseline_run_id", table_name="run")
    op.drop_column("run", "baseline_run_id")
    op.drop_column("run", "interventions_hash")
    op.drop_column("run", "interventions")
