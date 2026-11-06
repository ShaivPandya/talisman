"""Persist user-owned Graph Fundamentals layouts."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_0001"
down_revision = "20261104_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_fundamental_charts",
        sa.Column("chart_id", sa.Text, primary_key=True),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("state_json", sa.Text, nullable=False),
    )
    op.create_index("graph_charts_owner_updated", "graph_fundamental_charts", ["owner_id", "updated_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'talisman_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON graph_fundamental_charts TO talisman_app;
            END IF;
        END $$;""")


def downgrade() -> None:
    op.drop_table("graph_fundamental_charts")
