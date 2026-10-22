"""Index current idea evaluations and their children for batched list reads.

Revision ID: 20261021_0195
Revises: 20261021_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_0195"
down_revision: str | None = "20261021_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "idx_idea_evaluations_current_idea",
            "ontology_object_versions",
            [sa.text("(properties_json->>'idea_id')")],
            postgresql_where=sa.text("object_type = 'IdeaEvaluation' AND tx_to IS NULL"),
            postgresql_concurrently=True,
        )
        op.create_index(
            "idx_idea_evaluation_children_current_parent",
            "ontology_object_versions",
            [sa.text("(properties_json->>'parent_uid')"), "object_type", "business_key"],
            postgresql_where=sa.text(
                "object_type IN ('FactorScore', 'MissingInformationRequirement') AND tx_to IS NULL"
            ),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("idx_idea_evaluation_children_current_parent", postgresql_concurrently=True)
        op.drop_index("idx_idea_evaluations_current_idea", postgresql_concurrently=True)
