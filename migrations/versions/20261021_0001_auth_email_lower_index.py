"""Index case-insensitive Cloudflare auth email lookups.

Revision ID: 20261021_0001
Revises: 20261017_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_0001"
down_revision: str | None = "20261017_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_auth_users_email_lower", "auth_users", [sa.text("lower(email)")])


def downgrade() -> None:
    op.drop_index("ix_auth_users_email_lower", table_name="auth_users")
