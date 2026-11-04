"""Keep user-owned screener results independently of expiring async jobs."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_0001"
down_revision = "20261031_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "screener_runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("screen", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("snapshot_json", sa.Text, nullable=False),
    )
    op.create_index("screener_runs_owner_screen_created", "screener_runs", ["owner_id", "screen", "created_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'talisman_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON screener_runs TO talisman_app;
                END IF;
            END $$;
        """)


def downgrade() -> None:
    op.drop_table("screener_runs")
