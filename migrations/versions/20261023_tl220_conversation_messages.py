"""Replace duplicated chat transcript blobs with individually addressable messages.

Revision ID: 20261023_tl220
Revises: 20261021_tl193
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from api.conversation_messages import (
    CREATE_MESSAGES,
    CREATE_TURN_INDEX,
    MESSAGE_COLUMNS,
    legacy_messages,
    message_record,
    record_message,
)

revision: str = "20261023_tl220"
down_revision: str | None = "20261021_tl193"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    op.execute(CREATE_MESSAGES)
    op.execute(CREATE_TURN_INDEX)
    table = sa.table("conversation_messages", *(sa.column(name) for name in MESSAGE_COLUMNS))
    # Process one conversation at a time: never hold the entire message corpus in memory.
    for session in conn.execute(
        sa.text("SELECT session_id, transcript, server_messages FROM conversation_sessions")
    ).mappings():
        parent = None
        messages = legacy_messages(dict(session))
        for position, message in enumerate(messages):
            record = message_record(session["session_id"], message, position, parent, legacy=True)
            conn.execute(table.insert().values(**record))
            parent = record["id"]
        conn.execute(
            sa.text("UPDATE conversation_sessions SET message_count = :count WHERE session_id = :sid"),
            {"count": len(messages), "sid": session["session_id"]},
        )
    op.drop_column("conversation_sessions", "server_messages")
    op.drop_column("conversation_sessions", "transcript")


def downgrade() -> None:
    conn = op.get_bind()
    for column in ("transcript", "server_messages"):
        op.add_column("conversation_sessions", sa.Column(column, sa.Text, nullable=False, server_default="[]"))
    for session in conn.execute(sa.text("SELECT session_id FROM conversation_sessions")).mappings():
        rows = conn.execute(
            sa.text("SELECT * FROM conversation_messages WHERE session_id = :sid ORDER BY position"),
            {"sid": session["session_id"]},
        ).mappings()
        transcript = json.dumps([record_message(row) for row in rows])
        conn.execute(
            sa.text(
                "UPDATE conversation_sessions SET transcript = :text, server_messages = :text WHERE session_id = :sid"
            ),
            {"text": transcript, "sid": session["session_id"]},
        )
    op.drop_table("conversation_messages")
