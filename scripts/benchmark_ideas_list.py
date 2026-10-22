"""Compare GET /ideas data reads against a Git baseline in disposable Postgres schemas.

Run with TEST_POSTGRES_URL pointing at a local Postgres 16 database, for example:
    python -m scripts.benchmark_ideas_list --baseline-ref 8653b613 --output outputs/tl195.json

Only synthetic data is used. Each schema is removed on exit. This measures SQL
and route projection, excluding authentication, HTTP transport and pool checkout.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import runpy
import statistics
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psycopg
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
INDEX_MIGRATION = "20261021_0195_ideas_list_indexes.py"


def local_database_url() -> str:
    dsn = (os.getenv("TEST_POSTGRES_URL") or "").strip()
    if not dsn:
        raise ValueError("Set TEST_POSTGRES_URL to a disposable local Postgres 16 database.")
    config = conninfo_to_dict(dsn)
    if config.get("host") not in {"localhost", "127.0.0.1", "::1"} or not config.get("dbname"):
        raise ValueError("TEST_POSTGRES_URL must name a local disposable database.")
    return dsn


def apply_migration(dsn: str, filename: str, direction: str = "upgrade") -> None:
    engine = sa.create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn))
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            with context.begin_transaction(), Operations.context(context):
                runpy.run_path(str(MIGRATIONS / filename))[direction]()
    finally:
        engine.dispose()


@contextmanager
def disposable_ideas_database(dsn: str, *, indexes: bool = True) -> Iterator[str]:
    schema = f"tl195_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        # Install the shared extension outside our disposable search_path.
        admin.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        admin.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema)))
        scoped = make_conninfo(dsn, options=f"-csearch_path={schema},public", application_name=schema)
        try:
            apply_migration(scoped, "20260503_0011_temporal_ontology.py")
            if indexes:
                apply_migration(scoped, INDEX_MIGRATION)
            yield scoped
        finally:
            admin.execute(psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(psycopg.sql.Identifier(schema)))


INSERT_OBJECT = """
    INSERT INTO ontology_object_versions (
        version_id, object_uid, object_type, business_key, schema_name,
        schema_version, properties_json, valid_from, tx_from, valid_to, tx_to
    ) VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s)
"""


def object_values(
    kind: str,
    uid: str,
    props: dict[str, Any],
    *,
    valid_from: str = "2026-01-01T00:00:00+00:00",
    valid_to: str | None = None,
    tx_to: str | None = None,
) -> tuple[Any, ...]:
    return (
        uuid.uuid5(uuid.NAMESPACE_URL, f"tl195:{uid}:{valid_from}:{tx_to}"),
        uid,
        kind,
        uid,
        kind,
        Jsonb(props),
        valid_from,
        "2026-01-01T00:00:00+00:00",
        valid_to,
        tx_to,
    )


def seed_ideas(conn: Any, *, count: int = 200, evaluations: int = 20) -> None:
    rows = []
    for idea_number in range(count):
        idea_uid = f"investment_idea:{idea_number:04}"
        ticker = f"TEST{idea_number:04}"
        rows.append(object_values("InvestmentIdea", idea_uid, {"ticker": ticker, "status": "watching"}))
        for evaluation_number in range(evaluations):
            evaluation_uid = f"idea_evaluation:{idea_number:04}:{evaluation_number:04}"
            evaluated_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=evaluation_number)
            rows.append(
                object_values(
                    "IdeaEvaluation",
                    evaluation_uid,
                    {
                        "idea_id": idea_uid,
                        "evaluated_at": evaluated_at.isoformat(),
                        "ticker": ticker,
                        "score": evaluation_number,
                        "factor_scores": {},
                        "missing_information": [],
                    },
                )
            )
            for factor in ("value", "quality"):
                rows.append(
                    object_values(
                        "FactorScore",
                        f"factor_score:{evaluation_uid}:{factor}",
                        {"parent_uid": evaluation_uid, "factor_name": factor, "score": evaluation_number},
                    )
                )
            rows.append(
                object_values(
                    "MissingInformationRequirement",
                    f"missing_information:{evaluation_uid}",
                    {"parent_uid": evaluation_uid, "field": "earnings", "status": "missing"},
                )
            )
    with conn.cursor() as cur:
        cur.executemany(INSERT_OBJECT, rows)
    conn.execute("ANALYZE ontology_object_versions")


class CountedConnection:
    """Use the same warm connection for both paths and count real SQL statements."""

    def __init__(self, conn: Any):
        self.conn = conn
        self.calls: list[tuple[str, Any]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self.conn.execute(sql, params)


def read_service(conn: CountedConnection):
    from ontology.object_service import OntologyObjectService
    from ontology.read_model import TemporalReadModelRepository
    from ontology.runtime_read_service import OntologyRuntimeReadService
    from ontology.temporal_repository import TemporalOntologyRepository

    return OntologyRuntimeReadService(
        object_service=OntologyObjectService(TemporalOntologyRepository(connection_factory=lambda: conn)),
        read_model_repository=TemporalReadModelRepository(connection_factory=lambda: conn),
    )


def baseline_route(ref: str, router: Any):
    source = subprocess.check_output(["git", "show", f"{ref}:api/routers/ideas.py"], text=True)
    function = next(
        node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "list_ideas"
    )
    function.decorator_list = []
    namespace = dict(vars(router))
    exec(compile(ast.Module(body=[function], type_ignores=[]), f"{ref}:ideas.py", "exec"), namespace)
    return namespace["list_ideas"], namespace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dsn = local_database_url()
    os.environ.update(PYTHON_DOTENV_DISABLED="1", STATE_DB_BACKEND="postgres", DATABASE_URL=dsn)
    from api.routers import ideas as router

    old_route, namespace = baseline_route(args.baseline_ref, router)
    results: dict[str, Any] = {"baseline_ref": args.baseline_ref, "samples": args.samples, "cases": []}
    with disposable_ideas_database(dsn, indexes=False) as before, disposable_ideas_database(dsn) as after:
        with (
            psycopg.connect(before, autocommit=True, row_factory=dict_row) as before_conn,
            psycopg.connect(after, autocommit=True, row_factory=dict_row) as after_conn,
        ):
            seed_ideas(before_conn)
            seed_ideas(after_conn)
            results["postgres"] = after_conn.execute("SHOW server_version").fetchone()["server_version"]
            connections = {"before": CountedConnection(before_conn), "after": CountedConnection(after_conn)}
            services = {name: read_service(conn) for name, conn in connections.items()}
            for count in (1, 50, 200):
                observations: dict[str, list[float]] = {"before": [], "after": []}
                query_counts = {}
                for sample in range(args.samples + args.warmup):
                    for name in ("before", "after") if sample % 2 == 0 else ("after", "before"):
                        conn = connections[name]
                        conn.calls.clear()
                        factory = lambda service=services[name]: service  # noqa: E731
                        with patch.object(router, "OntologyRuntimeReadService", factory):
                            namespace["OntologyRuntimeReadService"] = factory
                            started = time.perf_counter()
                            response = (old_route if name == "before" else router.list_ideas)(limit=count)
                            elapsed = (time.perf_counter() - started) * 1000
                        assert response["count"] == count
                        expected_score = 0 if name == "before" else 19
                        assert all(idea["latest_evaluation"]["score"] == expected_score for idea in response["ideas"])
                        query_counts[name] = len(conn.calls)
                        if sample >= args.warmup:
                            observations[name].append(elapsed)
                results["cases"].append(
                    {
                        "ideas": count,
                        **{
                            name: {
                                "queries": query_counts[name],
                                "median_ms": round(statistics.median(samples), 3),
                                "p95_ms": round(sorted(samples)[math.ceil(len(samples) * 0.95) - 1], 3),
                            }
                            for name, samples in observations.items()
                        },
                    }
                )
                print(json.dumps(results["cases"][-1]), flush=True)
            sql, params = connections["after"].calls[0]
            results["after_explain"] = after_conn.execute(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params
            ).fetchone()["QUERY PLAN"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
