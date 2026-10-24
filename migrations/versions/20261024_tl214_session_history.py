"""Persist History pins and remove legacy sessions that contain no messages.

Revision ID: 20261024_tl214
Revises: 20261023_tl224
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261024_tl214"
down_revision: str | None = "20261023_tl224"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    op.add_column("conversation_sessions", sa.Column("pinned_at", sa.Text(), nullable=True))
    op.execute(
        "CREATE INDEX idx_sessions_history ON conversation_sessions "
        "(COALESCE(pinned_at, '') DESC, COALESCE(ended_at, started_at, '') DESC, session_id DESC) "
        "WHERE message_count > 0"
    )
    # A queued turn may have allocated a session before writing its first message.
    # Preserve it even when the denormalized message_count is zero.
    active_jobs = ""
    if sa.inspect(conn).has_table("async_jobs"):
        job_session = (
            "json_extract(j.payload_json, '$.session_id')"
            if conn.dialect.name == "sqlite"
            else "j.payload_json->>'session_id'"
        )
        active_jobs = (
            " AND NOT EXISTS (SELECT 1 FROM async_jobs j WHERE j.job_type = 'agent_chat_turn' "
            f"AND j.status IN ('queued', 'running') AND {job_session} = conversation_sessions.session_id)"
        )
    op.execute(
        "DELETE FROM conversation_sessions WHERE NOT EXISTS "
        "(SELECT 1 FROM conversation_messages m WHERE m.session_id = conversation_sessions.session_id)" + active_jobs
    )


def downgrade() -> None:
    # Empty sessions had no conversation content to restore.
    op.drop_index("idx_sessions_history", table_name="conversation_sessions")
    op.drop_column("conversation_sessions", "pinned_at")
