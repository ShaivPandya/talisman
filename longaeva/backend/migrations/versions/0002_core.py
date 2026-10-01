"""Core domain schema: sources, observations, parameters, scenarios, runs, forecasts.

Revision ID: 0002_core
Revises: 0001_job_queue
Create Date: 2026-10-01 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_core"
down_revision: str | None = "0001_job_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("publication_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieval_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("original_path", sa.Text(), nullable=False),
        sa.Column("license_note", sa.Text(), nullable=True),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("publication_ts < retrieval_ts", name=op.f("ck_source_publication_before_retrieval")),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["source.id"],
            name=op.f("fk_source_supersedes_id_source"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source")),
        sa.UniqueConstraint("content_hash", name=op.f("uq_source_content_hash")),
    )
    op.create_index("ix_source_company_publication_ts", "source", ["company", "publication_ts"], unique=False)
    op.create_index("ix_source_publication_ts", "source", ["publication_ts"], unique=False)

    op.create_table(
        "source_retrieval",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name=op.f("fk_source_retrieval_source_id_source"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_retrieval")),
    )
    op.create_index(
        "ix_source_retrieval_source_id_retrieved_at",
        "source_retrieval",
        ["source_id", "retrieved_at"],
        unique=False,
    )

    op.create_table(
        "document_text",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=True,
        ),
        sa.CheckConstraint("char_end >= char_start", name=op.f("ck_document_text_char_span_order")),
        sa.CheckConstraint("page >= 0", name=op.f("ck_document_text_page_nonneg")),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name=op.f("fk_document_text_source_id_source"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_text")),
        sa.UniqueConstraint("source_id", "page", "char_start", name=op.f("uq_document_text_source_page_start")),
    )
    op.create_index("ix_document_text_tsv", "document_text", ["tsv"], unique=False, postgresql_using="gin")

    op.create_table(
        "observation",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_text_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("span_page", sa.Integer(), nullable=True),
        sa.Column("span_char_start", sa.Integer(), nullable=True),
        sa.Column("span_char_end", sa.Integer(), nullable=True),
        sa.Column("statement_type", sa.Text(), nullable=False),
        sa.Column("activity_type", sa.Text(), nullable=True),
        sa.Column("geography", sa.Text(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("range_low", sa.Float(), nullable=True),
        sa.Column("range_high", sa.Float(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=True),
        sa.Column("source_family", sa.Text(), nullable=True),
        sa.Column("extractor_id", sa.Text(), nullable=True),
        sa.Column("extractor_version", sa.Text(), nullable=True),
        sa.Column("review_status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "statement_type IN ('measured', 'guidance', 'qualitative', 'analyst_assumption', 'intervention')",
            name=op.f("ck_observation_statement_type"),
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected', 'corrected')",
            name=op.f("ck_observation_review_status"),
        ),
        sa.CheckConstraint(
            "(statement_type IN ('analyst_assumption', 'intervention')) OR (source_id IS NOT NULL)",
            name=op.f("ck_observation_source_required_unless_assumption"),
        ),
        sa.CheckConstraint(
            "(statement_type = 'qualitative') OR (value IS NOT NULL) OR (range_low IS NOT NULL)",
            name=op.f("ck_observation_value_or_range_unless_qualitative"),
        ),
        sa.CheckConstraint(
            "(range_low IS NULL) OR (range_high IS NULL) OR (range_low <= range_high)",
            name=op.f("ck_observation_range_order"),
        ),
        sa.ForeignKeyConstraint(
            ["document_text_id"],
            ["document_text.id"],
            name=op.f("fk_observation_document_text_id_document_text"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name=op.f("fk_observation_source_id_source"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_observation")),
    )
    op.create_index(
        "ix_observation_company_period",
        "observation",
        ["company", "period_start", "period_end"],
        unique=False,
    )
    op.create_index("ix_observation_source_id", "observation", ["source_id"], unique=False)
    op.create_index("ix_observation_review_status", "observation", ["review_status"], unique=False)

    op.create_table(
        "review_decision",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("corrected_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=False),
        sa.CheckConstraint("decision IN ('accept', 'reject', 'correct')", name=op.f("ck_review_decision_decision")),
        sa.CheckConstraint(
            "(decision <> 'correct') OR (corrected_payload IS NOT NULL)",
            name=op.f("ck_review_decision_corrected_payload_required"),
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["observation.id"],
            name=op.f("fk_review_decision_observation_id_observation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_decision")),
    )
    op.create_index("ix_review_decision_observation_id", "review_decision", ["observation_id"], unique=False)

    op.create_table(
        "mapping_rule",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("rule_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("input_type", sa.Text(), nullable=False),
        sa.Column("target_parameter", sa.Text(), nullable=False),
        sa.Column(
            "transform",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mapping_rule")),
        sa.UniqueConstraint("rule_key", "version", name=op.f("uq_mapping_rule_key_version")),
    )

    op.create_table(
        "parameter_set",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("cutoff_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "values",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "ranges",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "evidence_links",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "assumption_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["parameter_set.id"],
            name=op.f("fk_parameter_set_parent_id_parameter_set"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parameter_set")),
        sa.UniqueConstraint("content_hash", name=op.f("uq_parameter_set_content_hash")),
    )
    op.create_index(
        "ix_parameter_set_company_cutoff_ts",
        "parameter_set",
        ["company", "cutoff_ts"],
        unique=False,
    )

    op.create_table(
        "parameter_update",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parameter_set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_parameter", sa.Text(), nullable=False),
        sa.Column("before_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("size", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["parameter_set_id"],
            ["parameter_set.id"],
            name=op.f("fk_parameter_update_parameter_set_id_parameter_set"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["mapping_rule.id"],
            name=op.f("fk_parameter_update_rule_id_mapping_rule"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parameter_update")),
    )
    op.create_index("ix_parameter_update_parameter_set_id", "parameter_update", ["parameter_set_id"], unique=False)

    op.create_table(
        "parameter_update_observation",
        sa.Column("parameter_update_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["observation.id"],
            name=op.f("fk_parameter_update_observation_observation_id_observation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parameter_update_id"],
            ["parameter_update.id"],
            name=op.f("fk_parameter_update_observation_parameter_update_id_parameter_update"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "parameter_update_id",
            "observation_id",
            name=op.f("pk_parameter_update_observation"),
        ),
    )

    op.create_table(
        "scenario",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parameter_set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "interventions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("pair_group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["parameter_set_id"],
            ["parameter_set.id"],
            name=op.f("fk_scenario_parameter_set_id_parameter_set"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario")),
    )
    op.create_index("ix_scenario_parameter_set_id", "scenario", ["parameter_set_id"], unique=False)

    op.create_table(
        "run",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cutoff_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_manifest_hash", sa.Text(), nullable=False),
        sa.Column("parameter_set_hash", sa.Text(), nullable=False),
        sa.Column("code_version", sa.Text(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("n_paths", sa.Integer(), nullable=False),
        sa.Column(
            "switches",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "lib_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("outputs_path", sa.Text(), nullable=True),
        sa.Column("outputs_hash", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_run_status"),
        ),
        sa.CheckConstraint("n_paths >= 1", name=op.f("ck_run_n_paths_positive")),
        sa.CheckConstraint("seed >= 0", name=op.f("ck_run_seed_nonneg")),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f("fk_run_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenario.id"],
            name=op.f("fk_run_scenario_id_scenario"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run")),
    )
    op.create_index("ix_run_scenario_id", "run", ["scenario_id"], unique=False)
    op.create_index("ix_run_status_created_at", "run", ["status", "created_at"], unique=False)

    op.create_table(
        "forecast",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("origin_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_period_start", sa.Date(), nullable=False),
        sa.Column("target_period_end", sa.Date(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column(
            "quantiles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('retrospective', 'prospective')", name=op.f("ck_forecast_kind")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["run.id"],
            name=op.f("fk_forecast_run_id_run"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecast")),
    )
    op.create_index("ix_forecast_kind_origin_ts", "forecast", ["kind", "origin_ts"], unique=False)
    op.create_index("ix_forecast_run_id", "forecast", ["run_id"], unique=False)

    op.create_table(
        "evaluation_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("suite_version", sa.Text(), nullable=False),
        sa.Column("origin_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_variant", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_result")),
    )
    op.create_index(
        "ix_evaluation_result_suite_origin",
        "evaluation_result",
        ["suite_version", "origin_ts"],
        unique=False,
    )
    op.create_index("ix_evaluation_result_config_hash", "evaluation_result", ["config_hash"], unique=False)

    op.execute(
        """
        CREATE OR REPLACE FUNCTION forbid_forecast_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'forecast rows are immutable'
                USING ERRCODE = 'restrict_violation';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_forecast_immutable
        BEFORE UPDATE OR DELETE ON forecast
        FOR EACH ROW
        EXECUTE FUNCTION forbid_forecast_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_forecast_immutable ON forecast")
    op.execute("DROP FUNCTION IF EXISTS forbid_forecast_mutation()")

    op.drop_index("ix_evaluation_result_config_hash", table_name="evaluation_result")
    op.drop_index("ix_evaluation_result_suite_origin", table_name="evaluation_result")
    op.drop_table("evaluation_result")

    op.drop_index("ix_forecast_run_id", table_name="forecast")
    op.drop_index("ix_forecast_kind_origin_ts", table_name="forecast")
    op.drop_table("forecast")

    op.drop_index("ix_run_status_created_at", table_name="run")
    op.drop_index("ix_run_scenario_id", table_name="run")
    op.drop_table("run")

    op.drop_index("ix_scenario_parameter_set_id", table_name="scenario")
    op.drop_table("scenario")

    op.drop_table("parameter_update_observation")

    op.drop_index("ix_parameter_update_parameter_set_id", table_name="parameter_update")
    op.drop_table("parameter_update")

    op.drop_index("ix_parameter_set_company_cutoff_ts", table_name="parameter_set")
    op.drop_table("parameter_set")

    op.drop_table("mapping_rule")

    op.drop_index("ix_review_decision_observation_id", table_name="review_decision")
    op.drop_table("review_decision")

    op.drop_index("ix_observation_review_status", table_name="observation")
    op.drop_index("ix_observation_source_id", table_name="observation")
    op.drop_index("ix_observation_company_period", table_name="observation")
    op.drop_table("observation")

    op.drop_index("ix_document_text_tsv", table_name="document_text")
    op.drop_table("document_text")

    op.drop_index("ix_source_retrieval_source_id_retrieved_at", table_name="source_retrieval")
    op.drop_table("source_retrieval")

    op.drop_index("ix_source_publication_ts", table_name="source")
    op.drop_index("ix_source_company_publication_ts", table_name="source")
    op.drop_table("source")
