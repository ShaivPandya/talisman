"""Longaeva CLI entrypoints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPENAPI_PATH = PACKAGE_ROOT / "docs" / "openapi.json"


def cmd_seed_demo(_args: argparse.Namespace) -> int:
    print("No demo dataset yet (LON-37). Seed is a no-op stub.")
    return 0


def cmd_export_openapi(args: argparse.Namespace) -> int:
    from longaeva_app.api.main import app

    app.openapi_schema = None
    schema = app.openapi()
    out = Path(args.output) if args.output else DEFAULT_OPENAPI_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    return 0


def cmd_export_check(args: argparse.Namespace) -> int:
    """Run the isolation guard (LON-12) or list the export file set."""
    from longaeva_app.isolation_guard import format_findings, list_export_paths, scan

    root = Path(args.root).resolve() if args.root else None
    if args.list:
        for rel in list_export_paths(root):
            print(rel)
        return 0
    findings = scan(root, strict=bool(args.strict))
    print(format_findings(findings))
    return 1 if findings else 0


def cmd_build_manifests(args: argparse.Namespace) -> int:
    """Regenerate visa/booking/census YAML manifests from committed fixtures."""
    from longaeva_app.collect.manifest import MANIFEST_DIR, build_manifests

    out_dir = Path(args.output) if args.output else MANIFEST_DIR
    built = build_manifests(manifest_dir=out_dir, write=True)
    for name, docs in built.items():
        print(f"Wrote {out_dir / name} ({len(docs)} documents)")
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    """Fetch curated manifests into the artifact store and database (LON-13)."""
    from longaeva_app.collect.collector import collect, summarize_report

    manifests = list(args.manifest) if args.manifest else None
    only = list(args.only) if args.only else None
    report = collect(
        manifests=manifests,
        only_keys=only,
        refresh=bool(args.refresh),
        dry_run=bool(args.dry_run),
    )
    print(summarize_report(report))
    return 1 if report.failed_count else 0


def cmd_engine_benchmark(args: argparse.Namespace) -> int:
    """Time a Visa 5,000-path × 4-quarter run (LON-19 / NR-01)."""
    import platform
    import time
    from datetime import UTC, datetime

    import numpy as np

    from longaeva_app.companies.base import FiscalPeriod
    from longaeva_app.companies.visa.model import VisaModel
    from longaeva_app.companies.visa.starting_state import load_fixture, required_fixture_paths, to_starting_state
    from longaeva_app.engine.runner import simulate

    model = VisaModel()
    fixture_path = required_fixture_paths()[0] if args.fixture is None else Path(args.fixture)
    fixture = load_fixture(fixture_path)
    start = to_starting_state(fixture)
    params = model.default_parameters()
    origin = FiscalPeriod(fixture.fiscal_year, fixture.fiscal_quarter)
    n_paths = int(args.n_paths)
    n_quarters = int(args.n_quarters)
    repeats = int(args.repeats)

    # Warm-up (excluded from timing).
    simulate(model, start, params, origin=origin, seed=0, n_paths=min(64, n_paths), n_quarters=n_quarters)

    timings: list[float] = []
    for i in range(repeats):
        t0 = time.perf_counter()
        simulate(model, start, params, origin=origin, seed=i + 1, n_paths=n_paths, n_quarters=n_quarters)
        timings.append(time.perf_counter() - t0)

    payload = {
        "measured_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "fixture": str(fixture_path.relative_to(PACKAGE_ROOT))
        if fixture_path.is_relative_to(PACKAGE_ROOT)
        else str(fixture_path),
        "origin": origin.label(),
        "n_paths": n_paths,
        "n_quarters": n_quarters,
        "repeats": repeats,
        "timings_s": timings,
        "min_s": min(timings),
        "median_s": float(np.median(timings)),
        "max_s": max(timings),
        "nr01_limit_s": 60.0,
        "nr01_pass": max(timings) <= 60.0,
        "numpy": np.__version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["nr01_pass"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="longaeva", description="Longaeva CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed-demo", help="Load bundled demo dataset (stub until LON-37)")
    seed.set_defaults(func=cmd_seed_demo)

    openapi = sub.add_parser("export-openapi", help="Write the published OpenAPI snapshot")
    openapi.add_argument(
        "--output",
        default=None,
        help=f"Output path (default: {DEFAULT_OPENAPI_PATH})",
    )
    openapi.set_defaults(func=cmd_export_openapi)

    guard = sub.add_parser(
        "export-check",
        help="Run the isolation guard over the export set (LON-12)",
    )
    guard.add_argument(
        "--root",
        default=None,
        help="Package root containing .exportignore (default: LONGAEVA_GUARD_ROOT or PACKAGE_ROOT)",
    )
    guard.add_argument(
        "--strict",
        action="store_true",
        help="Also fail when excluded paths (e.g. .env) are present — for unpacked export copies",
    )
    guard.add_argument(
        "--list",
        action="store_true",
        help="Print the export file set (relative paths) and exit 0",
    )
    guard.set_defaults(func=cmd_export_check)

    manifests = sub.add_parser(
        "build-manifests",
        help="Regenerate visa/booking/census manifests from committed fixtures (LON-13)",
    )
    manifests.add_argument(
        "--output",
        default=None,
        help="Manifest directory (default: data/manifest)",
    )
    manifests.set_defaults(func=cmd_build_manifests)

    collect_p = sub.add_parser(
        "collect",
        help="Fetch curated source manifests into artifacts + database (LON-13)",
    )
    collect_p.add_argument(
        "--manifest",
        action="append",
        default=None,
        help="Manifest name (repeatable), e.g. visa.yaml; default: all",
    )
    collect_p.add_argument(
        "--only",
        action="append",
        default=None,
        help="Collect only this manifest key (repeatable)",
    )
    collect_p.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch even when a source for the key already exists on disk",
    )
    collect_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve the selection and print actions without fetching or writing",
    )
    collect_p.set_defaults(func=cmd_collect)

    bench = sub.add_parser(
        "engine-benchmark",
        help="Time Visa Monte Carlo paths for NR-01 (LON-19)",
    )
    bench.add_argument(
        "--fixture",
        default=None,
        help="Starting-state fixture path (default: data/fixtures/states/visa_2024-07-23.json)",
    )
    bench.add_argument("--n-paths", type=int, default=5000, help="Number of Monte Carlo paths")
    bench.add_argument("--n-quarters", type=int, default=4, help="Horizon in fiscal quarters")
    bench.add_argument("--repeats", type=int, default=3, help="Timed repeats after a warm-up")
    bench.set_defaults(func=cmd_engine_benchmark)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
