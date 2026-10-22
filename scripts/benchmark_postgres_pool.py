"""Compare production pool settings against a disposable local Postgres database.

Run as ``python -m scripts.benchmark_postgres_pool --output outputs/pool.json``.
Only TEST_POSTGRES_URL is used; DATABASE_URL and .env files are never loaded.
The database must already contain the vector extension. All workload SQL reads.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import psycopg_pool
from psycopg.conninfo import conninfo_to_dict

from api import postgres


@dataclass(frozen=True)
class PoolCase:
    name: str
    minimum: int
    maximum: int
    timeout: float


CASES = (
    PoolCase("before_api", 0, 4, 30.0),
    PoolCase("before_worker", 0, 2, 5.0),
    PoolCase("after", 2, 2, 5.0),
)
COUNTERS = ("requests_num", "requests_queued", "requests_wait_ms", "requests_errors", "usage_ms", "connections_num")


@dataclass(frozen=True)
class Observation:
    checkout_ms: float | None
    operation_ms: float
    error: str | None = None


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; missing observations stay missing."""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], 3)


def test_database_url() -> str:
    dsn = (os.getenv("TEST_POSTGRES_URL") or "").strip().replace("postgresql+psycopg://", "postgresql://", 1)
    if not dsn:
        raise ValueError("Set TEST_POSTGRES_URL to a disposable local Postgres + pgvector database.")
    config = conninfo_to_dict(dsn)
    host = str(config.get("host") or "")
    if host not in {"localhost", "127.0.0.1", "::1"} and not host.startswith("/"):
        raise ValueError("TEST_POSTGRES_URL must use a local TCP host or Unix socket.")
    if not config.get("dbname"):
        raise ValueError("TEST_POSTGRES_URL must name a disposable database.")
    return dsn


def sample(hold_ms: float) -> Observation:
    started = time.perf_counter()
    checkout_ms = None
    error = None
    try:
        with postgres.connect(read_only=True) as conn:
            checkout_ms = (time.perf_counter() - started) * 1000
            conn.execute("SELECT pg_sleep(%s)", (hold_ms / 1000,)).fetchall()
    except Exception as exc:
        # Error messages can contain connection details; retain only their type.
        error = type(exc).__name__
    return Observation(checkout_ms, (time.perf_counter() - started) * 1000, error)


def run_case(
    case: PoolCase,
    *,
    dsn: str,
    concurrency: int,
    samples: int,
    warmup: int,
    hold_ms: float,
) -> dict[str, Any]:
    overrides = {
        "DATABASE_URL": dsn,
        "POSTGRES_POOL_MIN_SIZE": str(case.minimum),
        "POSTGRES_POOL_MAX_SIZE": str(case.maximum),
        "POSTGRES_POOL_TIMEOUT_SECONDS": str(case.timeout),
        "PERFORMANCE_BASELINES_ENABLED": "false",
    }
    previous = {key: os.environ.get(key) for key in overrides}
    postgres.close_pools()
    os.environ.update(overrides)
    try:
        started = time.perf_counter()
        with postgres.connect(read_only=True) as conn:
            cold_checkout_ms = (time.perf_counter() - started) * 1000
            server_version = conn.execute("SHOW server_version").fetchone()["server_version"]
        pool = postgres._get_pool()
        pool.wait(timeout=case.timeout)
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            warm = list(executor.map(lambda _: sample(hold_ms), range(max(warmup, concurrency * 20))))
            if any(value.error for value in warm):
                raise RuntimeError("Warmup failed; check the disposable database and vector extension.")
            before = pool.get_stats()
            started = time.perf_counter()
            observations = list(executor.map(lambda _: sample(hold_ms), range(samples)))
            elapsed = time.perf_counter() - started
            after = pool.get_stats()
        checkout = [value.checkout_ms for value in observations if value.checkout_ms is not None]
        errors = Counter(value.error for value in observations if value.error)
        return {
            "case": asdict(case),
            "concurrency": concurrency,
            "samples": samples,
            "hold_ms": hold_ms,
            "server_version": server_version,
            "cold_checkout_ms": round(cold_checkout_ms, 3),
            "checkout_p50_ms": percentile(checkout, 0.5),
            "checkout_p95_ms": percentile(checkout, 0.95),
            "operation_p95_ms": percentile([value.operation_ms for value in observations], 0.95),
            "successful_operations_per_second": round((samples - sum(errors.values())) / elapsed, 3),
            "errors": dict(errors),
            "pool": {key: after.get(key, 0) for key in ("pool_size", "pool_available", "pool_min", "pool_max")},
            "stats_delta": {key: after.get(key, 0) - before.get(key, 0) for key in COUNTERS},
        }
    finally:
        postgres.close_pools()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", nargs="+", type=positive_int, default=[1, 4, 8])
    parser.add_argument("--samples", type=positive_int, default=1000)
    parser.add_argument("--warmup", type=positive_int, default=100)
    parser.add_argument("--repeats", type=positive_int, default=5)
    parser.add_argument("--hold-ms", type=float, default=1.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not math.isfinite(args.hold_ms) or args.hold_ms < 0:
        parser.error("--hold-ms must be finite and nonnegative")
    try:
        dsn = test_database_url()
    except ValueError as exc:
        parser.error(str(exc))
    except psycopg.ProgrammingError:
        parser.error("TEST_POSTGRES_URL is not valid libpq connection information.")
    results = []
    for repeat in range(args.repeats):
        cases = CASES if repeat % 2 == 0 else tuple(reversed(CASES))
        concurrency_values = args.concurrency if repeat % 2 == 0 else list(reversed(args.concurrency))
        for concurrency in concurrency_values:
            for case in cases:
                result = run_case(
                    case,
                    dsn=dsn,
                    concurrency=concurrency,
                    samples=args.samples,
                    warmup=args.warmup,
                    hold_ms=args.hold_ms,
                )
                result["repeat"] = repeat + 1
                results.append(result)
                print(
                    f"repeat={repeat + 1} concurrency={concurrency} case={case.name} "
                    f"checkout_p95_ms={result['checkout_p95_ms']} errors={sum(result['errors'].values())}",
                    flush=True,
                )
    report = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "psycopg": psycopg.__version__,
        "psycopg_pool": psycopg_pool.__version__,
        "percentile_method": "nearest_rank",
        "workload": "one autocommit SELECT pg_sleep per checkout; warmup excluded",
        "results": results,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Saved {args.output}")
    else:
        print(json.dumps(report, indent=2))
    return int(any(result["errors"] for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
