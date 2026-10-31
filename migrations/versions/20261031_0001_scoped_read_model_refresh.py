"""Refresh only the ontology read models whose source rows changed.

Every ontology command used to rebuild all eight materialized read models,
twice per approval-gated action. Row triggers on the four source tables now
log which read models a write affects, and
``refresh_changed_ontology_read_models()`` rebuilds only those. Writes from any
process are logged, so a read model is never skipped while it has unapplied
changes. The log is append-only, so writers never wait on a refresh.

Revision ID: 20261031_0001
Revises: 20261029_0001
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20261031_0001"
down_revision: str | None = "20261029_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OBJECTS = "ontology_object_versions"
RELATIONS = "ontology_relation_versions"
SOURCE_RECORDS = "source_record_versions"
COMPUTED_SNAPSHOTS = "computed_snapshot_versions"
SOURCE_TABLES = (OBJECTS, RELATIONS, SOURCE_RECORDS, COMPUTED_SNAPSHOTS)
ANY_TYPE = "*"

# Must match the latest CREATE MATERIALIZED VIEW for each read model;
# tests/test_ontology_read_model_dependencies.py checks it against the migrations.
DECISION_LINEAGE_RELATION_TYPES = (
    "workflow_run_produces_artifact",
    "workflow_artifact_proposes_approval",
    "report_run_produces_recommendation",
    "recommendation_supported_by_source_record",
    "recommendation_uses_risk_metric",
    "recommendation_uses_scenario",
    "trade_proposal_derives_from_recommendation",
    "trade_proposal_requires_approval",
    "approval_applies_action_run",
    "action_run_produces_executed_action",
    "executed_action_mutates_object_version",
    "action_run_mutates_object_version",
    "audit_event_observes_action_run",
)
OPERATIONAL_OBJECT_TYPES = (
    "Position",
    "HedgePosition",
    "Thesis",
    "Evaluation",
    "Catalyst",
    "KillCondition",
    "ThesisClaim",
    "WorkflowRun",
    "ReportRun",
    "ActionItem",
    "WatchTrigger",
    "Approval",
    "Recommendation",
    "OptimizationAlert",
    "OptimizationActionSnapshot",
    "SourceFreshness",
    "ManagementQualityAssessment",
    "ManagementQualityScorecardRow",
    "ManagementQualityAccomplishment",
    "ManagementQualitySetback",
    "CourseOfAction",
    "CourseOfActionComparison",
    "ScenarioAssumption",
    "SimulatedOutcome",
    "CourseOfActionRationale",
    "CourseOfActionDissent",
    "MonitorHit",
    "DecisionOutcome",
    "OpportunityCandidate",
    "MonitorDefinition",
    "MissionDefinition",
)
PROVENANCE_RELATION_TYPES = (
    "provenance_used",
    "provenance_produced",
    "provenance_schema_bound",
    "provenance_executed",
    "provenance_executed_as",
    "provenance_triggered",
    "provenance_proposed",
    "provenance_resolved_by",
    "provenance_approved_execution",
    "provenance_audited_by",
    "provenance_updated",
)

# view -> source table -> type names whose writes change it (ANY_TYPE = every row).
READ_MODEL_DEPENDENCIES: dict[str, dict[str, tuple[str, ...]]] = {
    "ontology_current_position_risk_read_model": {
        OBJECTS: ("Position", "Asset", "Sector"),
        RELATIONS: ("references_asset", "belongs_to_sector"),
    },
    "ontology_current_position_signal_evidence_read_model": {
        OBJECTS: ("Signal",),
        RELATIONS: ("exposed_to_signal",),
    },
    "ontology_current_position_thesis_context_read_model": {
        OBJECTS: ("Thesis", "Evaluation", "Catalyst"),
        RELATIONS: ("has_thesis", "evaluated_by", "has_catalyst"),
    },
    # Joins both endpoints of each lineage edge to their current object version, whatever its type.
    "ontology_current_decision_lineage_read_model": {
        OBJECTS: (ANY_TYPE,),
        RELATIONS: DECISION_LINEAGE_RELATION_TYPES,
    },
    "ontology_current_source_status_read_model": {SOURCE_RECORDS: (ANY_TYPE,)},
    "ontology_current_computed_snapshot_read_model": {COMPUTED_SNAPSHOTS: (ANY_TYPE,)},
    "ontology_current_operational_object_read_model": {OBJECTS: OPERATIONAL_OBJECT_TYPES},
    "ontology_current_provenance_graph_edge_read_model": {RELATIONS: PROVENANCE_RELATION_TYPES},
}


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Ontology read models require PostgreSQL.")

    op.execute(
        """
        CREATE TABLE ontology_read_model_dependencies (
          view_name text NOT NULL,
          source_table text NOT NULL,
          type_name text NOT NULL,
          PRIMARY KEY (source_table, type_name, view_name)
        );

        CREATE TABLE ontology_read_model_changes (
          id bigserial PRIMARY KEY,
          view_name text NOT NULL,
          changed_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE INDEX idx_ontology_read_model_changes_view ON ontology_read_model_changes(view_name, id);
        """
    )
    rows = ",\n".join(
        f"({_sql_text(view)}, {_sql_text(table)}, {_sql_text(type_name)})"
        for view, tables in READ_MODEL_DEPENDENCIES.items()
        for table, type_names in tables.items()
        for type_name in type_names
    )
    op.execute(f"INSERT INTO ontology_read_model_dependencies (view_name, source_table, type_name) VALUES\n{rows}")
    # Start with every read model pending so the first refresh catches anything written before this migration.
    view_rows = ", ".join(f"({_sql_text(view)})" for view in READ_MODEL_DEPENDENCIES)
    op.execute(f"INSERT INTO ontology_read_model_changes (view_name) VALUES {view_rows}")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION ontology_read_model_log_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
          changed jsonb := to_jsonb(CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END);
          changed_type text := COALESCE(changed->>'object_type', changed->>'relation_type');
        BEGIN
          INSERT INTO ontology_read_model_changes (view_name)
          SELECT d.view_name
          FROM ontology_read_model_dependencies d
          WHERE d.source_table = TG_TABLE_NAME
            AND (d.type_name = '*' OR d.type_name = changed_type);
          RETURN NULL;
        END;
        $$;

        CREATE OR REPLACE FUNCTION refresh_changed_ontology_read_models()
        RETURNS TABLE (refreshed_view text, refresh_ms double precision)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
          pending record;
          started timestamptz;
        BEGIN
          -- Fixed order, so concurrent refreshers take view locks in the same sequence.
          FOR pending IN
            SELECT c.view_name, max(c.id) AS watermark
            FROM ontology_read_model_changes c
            JOIN pg_matviews m ON m.schemaname = 'public' AND m.matviewname = c.view_name
            GROUP BY c.view_name
            ORDER BY c.view_name
          LOOP
            started := clock_timestamp();
            EXECUTE format('REFRESH MATERIALIZED VIEW %I', pending.view_name);
            -- Rows above the watermark, or from writers not yet committed, stay for the next refresh.
            DELETE FROM ontology_read_model_changes c
            WHERE c.view_name = pending.view_name AND c.id <= pending.watermark;
            refreshed_view := pending.view_name;
            refresh_ms := extract(epoch FROM clock_timestamp() - started) * 1000;
            RETURN NEXT;
          END LOOP;
        END;
        $$;

        REVOKE ALL ON FUNCTION refresh_changed_ontology_read_models() FROM PUBLIC;
        """
    )
    for table in SOURCE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_read_model_changes
            AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION ontology_read_model_log_change()
            """
        )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'talisman_app') THEN
                GRANT EXECUTE ON FUNCTION refresh_changed_ontology_read_models() TO talisman_app;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'talisman_worker') THEN
                GRANT EXECUTE ON FUNCTION refresh_changed_ontology_read_models() TO talisman_worker;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Ontology read models require PostgreSQL.")

    for table in SOURCE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_read_model_changes ON {table}")
    op.execute("DROP FUNCTION IF EXISTS refresh_changed_ontology_read_models()")
    op.execute("DROP FUNCTION IF EXISTS ontology_read_model_log_change()")
    op.execute("DROP TABLE IF EXISTS ontology_read_model_changes")
    op.execute("DROP TABLE IF EXISTS ontology_read_model_dependencies")
