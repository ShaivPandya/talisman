"""Compare TL-193 full-text retrieval with an unchanged Git revision.

Only TEST_POSTGRES_URL (a disposable local database) is used. Each corpus gets
an isolated schema, removed on exit. No .env files or provider APIs are used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import runpy
import subprocess
import time
import types
import uuid
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg.conninfo import make_conninfo

from api import postgres, retrieval
from scripts.benchmark_postgres_pool import percentile, positive_int, test_database_url

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = "20261021_tl193_retrieval_fts.py"
QUERIES = (
    ("late_match", "Tell me about zephyr catalysts", None, None),
    ("sector", "Semiconductor demand outlook", None, None),
    ("macro", "Liquidity tightening", ["thesis"], None),
    ("ticker", "NVDA", None, None),
    ("filtered", "Capital allocation", ["thesis"], ["NVDA"]),
    ("absent", "unfindableword", None, None),
    ("broad", "portfolio", None, None),
)


def load_before(ref: str) -> types.ModuleType:
    source = subprocess.check_output(["git", "show", f"{ref}:api/retrieval.py"], cwd=ROOT, text=True)
    module = types.ModuleType("tl193_before_retrieval")
    module.__file__ = str(ROOT / "api" / "retrieval.py")
    exec(compile(source, module.__file__, "exec"), module.__dict__)

    # Match production's missing optional dependency, independent of the local
    # developer's installed extras. The original search()/fallback still runs.
    def missing_embedding(_query):
        raise ImportError("sentence-transformers not installed")

    module._embed_single = missing_embedding
    return module


def migrate(dsn: str, filename: str) -> None:
    engine = sa.create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn))
    try:
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            runpy.run_path(str(ROOT / "migrations" / "versions" / filename))["upgrade"]()
    finally:
        engine.dispose()


@contextmanager
def corpus(url: str, chunks: int) -> Iterator[str]:
    schema = f"tl193_bench_{uuid.uuid4().hex}"
    dsn = make_conninfo(url, options=f"-csearch_path={schema},public", application_name="tl193_benchmark")
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema)))
        try:
            for filename in ("20260429_0001_gcp_state_schema.py", "20260505_0007_ontology_native_retrieval.py"):
                migrate(dsn, filename)
            with psycopg.connect(dsn) as conn:
                conn.execute(
                    """
                    INSERT INTO retrieval_documents (doc_id, doc_type, ticker, content, created_at, updated_at)
                    SELECT 'doc-' || i, CASE WHEN i %% 2 = 0 THEN 'thesis' ELSE 'conversation_summary' END,
                           CASE WHEN i %% 100 = 0 THEN 'NVDA' ELSE 'SYM' || i END,
                           'Benchmark document', now(), now()
                    FROM generate_series(0, %s) i
                """,
                    ((chunks - 1) // 20,),
                )
                conn.execute(
                    """
                    INSERT INTO retrieval_chunks (chunk_id, doc_id, chunk_index, content, heading, embedding)
                    SELECT 'chunk-' || i, 'doc-' || ((i - 1) / 20), i,
                           CASE WHEN i = %s THEN 'Zephyr catalysts. ' ELSE '' END ||
                           CASE WHEN i %% 100 = 0 THEN 'Semiconductor demand outlook. '
                                WHEN i %% 100 = 1 THEN 'Liquidity tightening. ' ELSE '' END ||
                           repeat('Portfolio capital allocation, cash flows and risk assessment. ', 24),
                           CASE WHEN i = %s THEN 'Zephyr catalysts' ELSE 'Research notes' END,
                           array_fill(0::real, ARRAY[384])::vector
                    FROM generate_series(1, %s) i
                """,
                    (chunks, chunks, chunks),
                )
            migrate(dsn, MIGRATION)
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute("VACUUM ANALYZE retrieval_chunks")
                conn.execute("ANALYZE retrieval_documents")
            yield dsn
        finally:
            postgres.close_pools()
            admin.execute(psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(psycopg.sql.Identifier(schema)))


def run_case(module: Any, samples: int, warmup: int) -> dict[str, Any]:
    observations: dict[str, list[float]] = defaultdict(list)
    results = {}
    for index in range(warmup + samples):
        name, query, doc_types, tickers = QUERIES[index % len(QUERIES)]
        started = time.perf_counter()
        hits = module.search(query, doc_types=doc_types, tickers=tickers, top_k=5)
        elapsed = (time.perf_counter() - started) * 1000
        if index >= warmup:
            observations[name].append(elapsed)
            results[name] = [h["chunk_id"] for h in hits]
    all_samples = [elapsed for values in observations.values() for elapsed in values]
    return {
        "p50_ms": percentile(all_samples, 0.5),
        "p95_ms": percentile(all_samples, 0.95),
        "queries": {
            name: {
                "p50_ms": percentile(values, 0.5),
                "p95_ms": percentile(values, 0.95),
                "samples": len(values),
                "chunk_ids": results[name],
            }
            for name, values in observations.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-ref", required=True)
    parser.add_argument("--chunks", nargs="+", type=positive_int, default=[10_000, 100_000])
    parser.add_argument("--samples", type=positive_int, default=210)
    parser.add_argument("--warmup", type=positive_int, default=70)
    parser.add_argument("--repeats", type=positive_int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = test_database_url()
    before = load_before(args.before_ref)
    # Exclude log I/O in both cases; this conservatively understates old cost.
    logging.disable(logging.CRITICAL)
    os.environ.update(STATE_DB_BACKEND="postgres", POSTGRES_POOL_MIN_SIZE="2", POSTGRES_POOL_MAX_SIZE="2")
    report: dict[str, Any] = {
        "before_ref": args.before_ref,
        "after_ref": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "retrieval_sha256": hashlib.sha256((ROOT / "api" / "retrieval.py").read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "samples_per_case": args.samples,
        "warmup_per_case": args.warmup,
        "pool_min_max": [2, 2],
        "concurrency": 1,
        "results": [],
    }
    with psycopg.connect(url) as conn:
        report["postgres_version"] = conn.execute("SHOW server_version").fetchone()[0]
    for chunks in args.chunks:
        with corpus(url, chunks) as dsn:
            postgres.close_pools()
            os.environ["DATABASE_URL"] = dsn
            started = time.perf_counter()
            retrieval.search("zephyr")
            report.setdefault("cold_ms", {})[str(chunks)] = round((time.perf_counter() - started) * 1000, 3)
            postgres._get_pool().wait()
            for repeat in range(args.repeats):
                cases = [("before", before), ("after", retrieval)]
                if repeat % 2:
                    cases.reverse()
                for label, module in cases:
                    result = run_case(module, args.samples, args.warmup)
                    result.update(chunks=chunks, repeat=repeat + 1, case=label)
                    if label == "after" and result["queries"]["late_match"]["chunk_ids"] != [f"chunk-{chunks}"]:
                        raise AssertionError("Full-text search missed the best match beyond the old sample boundary")
                    report["results"].append(result)
                    print(f"chunks={chunks} repeat={repeat + 1} case={label} p95_ms={result['p95_ms']}", flush=True)
            # Capture the actual application plan without maintaining a second
            # copy of its SQL. The proxy only prefixes EXPLAIN for this call.
            original_connect = retrieval.connect

            @contextmanager
            def explain_connection(_connect=original_connect, _chunks=chunks, **kwargs):
                with _connect(**kwargs) as connection:

                    class Explain:
                        def execute(self, query, params):
                            plan = connection.execute(
                                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, params
                            ).fetchone()
                            report.setdefault("plans", {})[str(_chunks)] = plan["QUERY PLAN"]
                            return connection.execute(query, params)

                    yield Explain()

            retrieval.connect = explain_connection
            try:
                retrieval.search("zephyr")
            finally:
                retrieval.connect = original_connect
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
