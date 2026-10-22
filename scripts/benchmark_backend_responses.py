"""Offline TL-202 benchmark: python -m scripts.benchmark_backend_responses --output outputs/tl202.json.

Use --source-ref <commit> to rerun the original implementation from Git in this
worktree. Fixtures, interpreter, authentication overrides and transport are the
same on both sides. No external providers or databases are contacted. Times
include ASGI handling/serialization, but exclude network and provider latency.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import gzip
import importlib.abc
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

SOURCE_MODULES = (
    "api.main",
    "api.macro_snapshots",
    "api.request_schema",
    "api.routers.chart",
    "api.routers.housing",
    "api.routers.labor_market",
    "api.routers.economic_growth",
)


class GitSources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, ref: str):
        commit = subprocess.check_output(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], text=True).strip()
        self.sources = {
            name: subprocess.check_output(["git", "show", f"{commit}:{name.replace('.', '/')}.py"], text=True)
            for name in SOURCE_MODULES
        }

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.sources:
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__file__ = str(Path.cwd() / (module.__name__.replace(".", "/") + ".py"))
        exec(compile(self.sources[module.__name__], module.__file__, "exec"), module.__dict__)


def summary(values):
    ordered = sorted(values)
    return {"p50_ms": round(statistics.median(values), 3), "p95_ms": round(ordered[int((len(values) - 1) * 0.95)], 3)}


async def benchmark(iterations: int, rows: int):
    # Set before importing the app; load_dotenv must not select real services.
    os.environ.update(
        ENVIRONMENT="development",
        AUTH_MODE="password",
        API_PROXY_SECRET="",
        REQUIRE_API_PROXY_SECRET="false",
        WRITE_FREEZE="false",
        STATE_DB_BACKEND="sqlite",
        TALISMAN_ALLOW_SQLITE_STATE="true",
        STATE_STORAGE_BACKEND="local",
        DATABASE_URL="",
        API_DISK_CACHE_DISABLE="true",
        SENTRY_ENABLED="false",
        SENTRY_DSN="",
        PERFORMANCE_BASELINES_ENABLED="false",
    )
    import httpx
    import pandas as pd
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse, ORJSONResponse
    from starlette.middleware.gzip import GZipMiddleware

    import api.macro_snapshots as snapshots
    import api.main as main
    import portfolio.technical_analysis.technical_analysis as technical
    from api.cache import daily_cache, short_cache
    from api.request_schema import schema_headers_for_path
    from api.routers.auth import require_actor
    from ontology.policy import Actor

    main.app.dependency_overrides[require_actor] = lambda: Actor(
        actor_id="benchmark", actor_type="user", roles=("admin",)
    )
    frame = pd.DataFrame(
        {"Close": [100 + i / 37 for i in range(rows)]}, index=pd.date_range("2000-01-01", periods=rows)
    )
    payload = {"series": {"benchmark": frame.reset_index().astype({"index": str}).to_dict("records")}}
    payload["_meta"] = {"snapshot": {"key": "labor_market:current:v1", "stale": False}}
    calls = {"chart": 0, "ratio": 0, "csv": 0, "snapshot": 0}

    def chart(*args, **kwargs):
        calls["chart"] += 1
        return {"ticker": "BENCH", "price_data": frame, "timestamp": "2026-01-01T00:00:00"}

    def ratio(*args, **kwargs):
        calls["ratio"] += 1
        return {"symbol_a": "BENCH", "symbol_b": "PAIR", "ratio_data": frame}

    def csv(*args, **kwargs):
        calls["csv"] += 1
        return frame.reset_index()

    def snapshot(*args, **kwargs):
        calls["snapshot"] += 1
        return copy.deepcopy(payload)

    workloads = {
        "middleware": ("GET", "/api/health", None),
        "macro": ("GET", "/api/labor-market", None),
        "chart": ("POST", "/api/chart", {"ticker": "BENCH"}),
        "ratio": ("POST", "/api/chart/ratio", {"symbol_a": "BENCH", "symbol_b": "PAIR"}),
        "csv": ("GET", "/api/chart/price-history/BENCH", None),
    }
    results = {}
    direct_json = main.app.router.default_response_class is ORJSONResponse
    gzip_level = next(m.kwargs.get("compresslevel", 9) for m in main.app.user_middleware if m.cls is GZipMiddleware)
    # Use identical bytes for the compression comparison so a smaller response
    # or a different JSON format cannot account for the CPU/size differences.
    blob = JSONResponse(jsonable_encoder(payload)).body
    for name, operation in (
        (
            "encoding",
            lambda: ORJSONResponse(payload).body if direct_json else JSONResponse(jsonable_encoder(payload)).body,
        ),
        ("gzip", lambda: gzip.compress(blob, compresslevel=gzip_level, mtime=0)),
    ):
        elapsed = []
        cpu = time.process_time()
        for _ in range(iterations):
            started = time.perf_counter()
            encoded = operation()
            elapsed.append((time.perf_counter() - started) * 1000)
        results[name] = {
            **summary(elapsed),
            "cpu_ms_per_request": round((time.process_time() - cpu) * 1000 / iterations, 3),
            "encoded_bytes": len(encoded),
        }
    with (
        patch.object(technical, "get_data", chart),
        patch.object(technical, "get_ratio_data", ratio),
        patch.object(technical, "fetch_full_price_history", csv),
        patch.object(snapshots, "get_snapshot_response", snapshot),
        patch.object(main, "is_machine_authenticated_request", lambda request: True),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://benchmark"
        ) as client:
            for name, (method, path, body) in workloads.items():
                short_cache.clear()
                daily_cache.clear()
                headers = {**schema_headers_for_path(main.app, method, path), "Accept-Encoding": "gzip"}
                # Warm imports and caches, then count only the measured work.
                response = await client.request(method, path, json=body, headers=headers)
                response.raise_for_status()
                before = calls.copy()
                elapsed = []
                cpu = time.process_time()
                for _ in range(iterations):
                    started = time.perf_counter()
                    response = await client.request(method, path, json=body, headers=headers)
                    elapsed.append((time.perf_counter() - started) * 1000)
                    response.raise_for_status()
                results[name] = {
                    **summary(elapsed),
                    "cpu_ms_per_request": round((time.process_time() - cpu) * 1000 / iterations, 3),
                    "compressed_bytes": int(response.headers.get("content-length", len(response.content))),
                    "uncompressed_bytes": len(response.content),
                    "calls": {key: value - before[key] for key, value in calls.items()},
                }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-ref")
    parser.add_argument("--iterations", type=int, default=40)
    parser.add_argument("--rows", type=int, default=3000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.source_ref:
        sys.meta_path.insert(0, GitSources(args.source_ref))
    if args.iterations < 1 or args.rows < 1:
        parser.error("iterations and rows must be positive")
    results = asyncio.run(benchmark(args.iterations, args.rows))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"source_ref": args.source_ref, "iterations": args.iterations, "rows": args.rows, "results": results},
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
