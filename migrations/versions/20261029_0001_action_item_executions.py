"""Persist bounded action-item executions and checkpoints."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261029_0001"
down_revision = "20261024_tl215"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.create_table(
        "action_item_executions",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("item_id", sa.Text, nullable=False),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("state_json", postgresql.JSONB, nullable=False),
        sa.UniqueConstraint("owner_id", "item_id", name="uq_action_item_execution_owner_item"),
    )
    op.create_index("action_item_executions_owner_created", "action_item_executions", ["owner_id", "created_at"])
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'talisman_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON action_item_executions TO talisman_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'talisman_worker') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON action_item_executions TO talisman_worker;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_table("action_item_executions")
