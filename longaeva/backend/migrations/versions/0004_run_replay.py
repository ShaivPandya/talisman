"""Run replay columns, succeeded-output CHECK, forecast uniqueness (LON-23).

Revision ID: 0004_run_replay
Revises: 0003_passage_hash
Create Date: 2026-10-03 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_run_replay"
down_revision: str | None = "0003_passage_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run",
        sa.Column("origin_label", sa.Text(), server_default=sa.text("''"), nullable=False),
    )
    op.add_column(
        "run",
        sa.Column("n_quarters", sa.Integer(), server_default=sa.text("4"), nullable=False),
    )
    op.add_column(
        "run",
        sa.Column(
            "starting_state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "run",
        sa.Column("starting_state_hash", sa.Text(), server_default=sa.text("''"), nullable=False),
    )
    op.add_column(
        "run",
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        "ck_run_n_quarters_range",
        "run",
        "n_quarters >= 1 AND n_quarters <= 8",
    )
    op.create_check_constraint(
        "ck_run_succeeded_has_outputs",
        "run",
        "status <> 'succeeded' OR (outputs_hash IS NOT NULL AND outputs_path IS NOT NULL AND summary IS NOT NULL)",
    )
    op.create_unique_constraint(
        "uq_forecast_run_metric_period",
        "forecast",
        ["run_id", "metric", "target_period_start"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_forecast_run_metric_period", "forecast", type_="unique")
    op.drop_constraint("ck_run_succeeded_has_outputs", "run", type_="check")
    op.drop_constraint("ck_run_n_quarters_range", "run", type_="check")
    op.drop_column("run", "summary")
    op.drop_column("run", "starting_state_hash")
    op.drop_column("run", "starting_state")
    op.drop_column("run", "n_quarters")
    op.drop_column("run", "origin_label")
