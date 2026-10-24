"""Record which message a conversation's rolling summary covers, so branches can tell whether to use it.

Revision ID: 20261023_tl224
Revises: 20261023_tl220
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261023_tl224"
down_revision: str | None = "20261023_tl220"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversation_sessions", sa.Column("rolling_summary_through_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_sessions", "rolling_summary_through_id")
