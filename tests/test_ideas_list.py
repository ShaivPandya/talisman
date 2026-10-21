"""Ideas list regressions; SQL tests use an opt-in, disposable local Postgres schema."""

from __future__ import annotations

import io
import os
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from ontology.runtime_read_service import OntologyRuntimeReadService, _EmptyObjectService
from scripts.benchmark_ideas_list import (
    INDEX_MIGRATION,
    INSERT_OBJECT,
    MIGRATIONS,
    CountedConnection,
    apply_migration,
    disposable_ideas_database,
    local_database_url,
    object_values,
    read_service,
    seed_ideas,
)


def test_list_projects_preloaded_children_without_queries():
    objects = Mock()
    objects.query_objects.side_effect = AssertionError("per-evaluation query")
    repo = Mock()
    repo.fetch_ideas_list.return_value = [
        {
            "idea": {"object_uid": "investment_idea:test", "properties_json": {"ticker": "TEST"}},
            "evaluation": {
                "object_uid": "idea_evaluation:new",
                "properties_json": {"factor_scores": {"stale": {}}, "missing_information": []},
                "_meta": {"temporal": {"version_id": "v1"}},
            },
            "factor_rows": [
                {"properties_json": {"factor_name": "value", "score": 0, "missing": False, "weight": None}}
            ],
            "missing_rows": [{"properties_json": {"field": "earnings", "severity": "high", "status": "open"}}],
        }
    ]
    reads = OntologyRuntimeReadService(object_service=objects, read_model_repository=repo)
    ideas = reads.ideas_list(status="watching", include_archived=True, limit=17)
    repo.fetch_ideas_list.assert_called_once_with(status="watching", include_archived=True, limit=17)
    evaluation = ideas[0]["latest_evaluation"]
    assert evaluation["id"] == "idea_evaluation:new"
    assert evaluation["_meta"]["temporal"]["version_id"] == "v1"
    assert evaluation["factor_scores"] == {"value": {"score": 0, "missing": False}}
    assert evaluation["missing_information"] == [
        {"field": "earnings", "severity": "high", "status": "open", "reason": None}
    ]


def test_list_preserves_inline_fields_when_no_child_objects_exist():
    props = {"factor_scores": {"value": {"score": 42}}, "missing_information": [{"field": "sales"}]}
    repo = SimpleNamespace(
        fetch_ideas_list=lambda **kwargs: [
            {"idea": {}, "evaluation": {"properties_json": props}, "factor_rows": [], "missing_rows": []},
            {"idea": {}, "evaluation": None, "factor_rows": [], "missing_rows": []},
        ]
    )
    ideas = OntologyRuntimeReadService(object_service=_EmptyObjectService(), read_model_repository=repo).ideas_list()
    assert ideas[0]["latest_evaluation"] == props
    assert ideas[1]["latest_evaluation"] is None


def test_empty_test_backend_does_not_open_postgres():
    assert OntologyRuntimeReadService(object_service=_EmptyObjectService()).ideas_list() == []


def test_index_migration_emits_concurrent_ddl_outside_transaction():
    output = io.StringIO()
    context = MigrationContext.configure(url="postgresql://", opts={"as_sql": True, "output_buffer": output})
    migration = runpy.run_path(str(MIGRATIONS / INDEX_MIGRATION))
    with context.begin_transaction(), Operations.context(context):
        migration["upgrade"]()
        migration["downgrade"]()
    sql = output.getvalue()
    assert sql.count("CREATE INDEX CONCURRENTLY") == 2
    assert sql.count("DROP INDEX CONCURRENTLY") == 2
    assert sql.index("COMMIT;") < sql.index("CREATE INDEX CONCURRENTLY") < sql.index("BEGIN;", sql.index("COMMIT;"))


@pytest.fixture(scope="module")
def ideas_database():
    if not os.getenv("TEST_POSTGRES_URL"):
        pytest.skip("TEST_POSTGRES_URL must name a disposable local Postgres 16 database")
    with disposable_ideas_database(local_database_url()) as dsn:
        with psycopg.connect(dsn, autocommit=True) as conn:
            seed_ideas(conn)
        yield dsn


@pytest.fixture
def pg_reads(ideas_database):
    with psycopg.connect(ideas_database, autocommit=True, row_factory=dict_row) as conn:
        with conn.transaction(force_rollback=True):
            counted = CountedConnection(conn)
            yield conn, counted, read_service(counted)


@pytest.mark.parametrize("count", [1, 50, 200])
def test_get_ideas_uses_one_query_and_returns_newest_evaluation(pg_reads, monkeypatch, count):
    from api.routers import ideas as router

    _conn, counted, reads = pg_reads
    monkeypatch.setattr(router, "OntologyRuntimeReadService", lambda: reads)
    app = FastAPI()
    app.include_router(router.router)
    with TestClient(app) as client:
        response = client.get("/ideas", params={"limit": count})
    assert response.status_code == 200
    result = response.json()
    assert result["count"] == count
    assert len(counted.calls) == 1
    for idea in result["ideas"]:
        assert idea["asset"] == "equity"
        assert idea["latest_evaluation"]["score"] == 19
        assert idea["latest_evaluation"]["factor_scores"]["value"]["score"] == 19
        assert idea["latest_evaluation"]["missing_information"][0]["field"] == "earnings"


def test_latest_uses_timestamp_order_and_excludes_noncurrent_versions(pg_reads):
    conn, _counted, reads = pg_reads
    idea_id = "investment_idea:0000"
    for uid, evaluated_at, temporal in (
        ("a_offset", "2026-04-02T00:30:00+02:00", {}),
        ("z_latest", "2026-04-01T23:00:00+00:00", {}),
        ("expired", "2099-01-01T00:00:00Z", {"valid_to": "2026-01-02T00:00:00Z"}),
        ("future", "2099-01-01T00:00:00Z", {"valid_from": "2099-01-01T00:00:00Z"}),
        ("superseded", "2099-01-01T00:00:00Z", {"tx_to": "2026-02-01T00:00:00Z"}),
        ("malformed", "not a timestamp", {}),
        ("missing", None, {}),
    ):
        conn.execute(
            INSERT_OBJECT,
            object_values(
                "IdeaEvaluation",
                f"idea_evaluation:{uid}",
                {"idea_id": idea_id, "evaluated_at": evaluated_at},
                **temporal,
            ),
        )
    assert reads.ideas_list(limit=1)[0]["latest_evaluation"]["id"] == "idea_evaluation:z_latest"
    conn.execute(
        INSERT_OBJECT,
        object_values(
            "IdeaEvaluation", "idea_evaluation:b_tie", {"idea_id": idea_id, "evaluated_at": "2026-04-01T23:00:00Z"}
        ),
    )
    assert reads.ideas_list(limit=1)[0]["latest_evaluation"]["id"] == "idea_evaluation:b_tie"


def test_projection_matches_existing_detail_projection_with_child_limits(pg_reads):
    conn, counted, reads = pg_reads
    uid = "idea_evaluation:0000:0019"
    for number in range(105):
        conn.execute(
            INSERT_OBJECT,
            object_values(
                "FactorScore",
                f"factor_score:extra:{number:03}",
                {"parent_uid": uid, "factor_name": str(number), "score": number},
            ),
        )
        conn.execute(
            INSERT_OBJECT,
            object_values(
                "MissingInformationRequirement",
                f"missing_information:extra:{number:03}",
                {"parent_uid": uid, "field": str(number)},
            ),
        )
    conn.execute(
        INSERT_OBJECT,
        object_values(
            "FactorScore",
            "factor_score:expired",
            {"parent_uid": uid, "factor_name": "expired"},
            valid_to="2026-01-02T00:00:00Z",
        ),
    )
    expected = reads.get(uid)
    counted.calls.clear()
    actual = reads.ideas_list(limit=1)[0]["latest_evaluation"]
    assert actual == expected
    assert len(actual["factor_scores"]) == 100
    assert len(actual["missing_information"]) == 100
    assert len(counted.calls) == 1


def test_filters_limits_and_no_evaluation(pg_reads):
    conn, counted, reads = pg_reads
    conn.execute(
        "UPDATE ontology_object_versions SET properties_json = properties_json || '{\"status\":\"archived\"}'::jsonb WHERE object_uid = 'investment_idea:0000'"
    )
    assert reads.ideas_list(limit=1) == []  # Existing filtering happens after the page limit.
    assert len(reads.ideas_list(limit=1, include_archived=True)) == 1
    assert reads.ideas_list(status="archived") == []
    assert len(reads.ideas_list(status="archived", include_archived=True)) == 1
    assert reads.ideas_list(status="missing") == []
    assert reads.ideas_list(limit=0) == []
    conn.execute(
        "UPDATE ontology_object_versions SET valid_to = '2026-01-02' WHERE properties_json->>'idea_id' = 'investment_idea:0001'"
    )
    ideas = reads.ideas_list(status="watching", limit=1)
    assert ideas[0]["id"] == "investment_idea:0001"
    assert ideas[0]["latest_evaluation"] is None
    conn.execute("DELETE FROM ontology_object_versions WHERE object_type = 'InvestmentIdea'")
    counted.calls.clear()
    assert reads.ideas_list() == []
    assert len(counted.calls) == 1


def test_indexes_can_upgrade_and_downgrade(ideas_database):
    with disposable_ideas_database(local_database_url(), indexes=False) as dsn:
        apply_migration(dsn, INDEX_MIGRATION)
        with psycopg.connect(dsn, autocommit=True) as conn:
            indexes = conn.execute(
                "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relnamespace = current_schema()::regnamespace AND c.relname LIKE 'idx_idea_%'"
            ).fetchall()
            assert indexes == [(True,), (True,)]
        apply_migration(dsn, INDEX_MIGRATION, "downgrade")
        with psycopg.connect(dsn, autocommit=True) as conn:
            assert conn.execute(
                "SELECT count(*) FROM pg_class WHERE relnamespace = current_schema()::regnamespace AND relname LIKE 'idx_idea_%'"
            ).fetchone() == (0,)
