"""Mapping-rule kind and parameter-set context rows (LON-21).

Revision ID: 0007_mapping_rules
Revises: 0006_scenario_pairs
Create Date: 2026-10-04 10:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_mapping_rules"
down_revision: str | None = "0006_scenario_pairs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mapping_rule",
        sa.Column("kind", sa.Text(), server_default=sa.text("'analyst_range'"), nullable=False),
    )
    op.add_column(
        "mapping_rule",
        sa.Column("source_family", sa.Text(), server_default=sa.text("''"), nullable=False),
    )
    op.add_column(
        "mapping_rule",
        sa.Column("value_test", sa.Text(), server_default=sa.text("''"), nullable=False),
    )
    op.add_column(
        "mapping_rule",
        sa.Column("definition_hash", sa.Text(), server_default=sa.text("''"), nullable=False),
    )
    op.create_check_constraint(
        "ck_mapping_rule_kind",
        "mapping_rule",
        "kind IN ('estimated', 'analyst_range', 'context')",
    )
    op.alter_column("mapping_rule", "target_parameter", existing_type=sa.Text(), nullable=True)

    op.create_table(
        "parameter_set_context",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("parameter_set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["observation.id"],
            name=op.f("fk_parameter_set_context_observation_id_observation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parameter_set_id"],
            ["parameter_set.id"],
            name=op.f("fk_parameter_set_context_parameter_set_id_parameter_set"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["mapping_rule.id"],
            name=op.f("fk_parameter_set_context_rule_id_mapping_rule"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parameter_set_context")),
        sa.UniqueConstraint(
            "parameter_set_id",
            "observation_id",
            name=op.f("uq_parameter_set_context_set_observation"),
        ),
    )
    op.create_index(
        "ix_parameter_set_context_parameter_set_id",
        "parameter_set_context",
        ["parameter_set_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_parameter_set_context_parameter_set_id", table_name="parameter_set_context")
    op.drop_table("parameter_set_context")
    op.drop_constraint("ck_mapping_rule_kind", "mapping_rule", type_="check")
    op.drop_column("mapping_rule", "definition_hash")
    op.drop_column("mapping_rule", "value_test")
    op.drop_column("mapping_rule", "source_family")
    op.drop_column("mapping_rule", "kind")
    op.execute("UPDATE mapping_rule SET target_parameter = '' WHERE target_parameter IS NULL")
    op.alter_column("mapping_rule", "target_parameter", existing_type=sa.Text(), nullable=False)
