"""Persist company research runs and shared budgets.

Revision ID: 20261017_0001
Revises: 20260607_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261017_0001"
down_revision: str | None = "20260607_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.create_table(
        "company_research_runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("state_json", postgresql.JSONB, nullable=False),
    )
    op.create_index("research_runs_ticker", "company_research_runs", ["ticker", "created_at"])


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_index("research_runs_ticker", table_name="company_research_runs")
    op.drop_table("company_research_runs")
