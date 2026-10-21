"""Record the owner and attempt of each async job claim.

Revision ID: 20261021_0002
Revises: 20261021_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_0002"
down_revision: str | None = "20261021_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("async_jobs", sa.Column("claimed_by", sa.Text))
    op.add_column("async_jobs", sa.Column("attempt", sa.Integer, nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("async_jobs", "attempt")
    op.drop_column("async_jobs", "claimed_by")
