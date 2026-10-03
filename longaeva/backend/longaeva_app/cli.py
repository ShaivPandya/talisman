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


def cmd_parse_visa(args: argparse.Namespace) -> int:
    """Offline Visa table parser (LON-14)."""
    from collections import Counter

    from longaeva_app.extract.visa_tables import iter_origin_parses, write_outputs

    status_rows, obs_rows = iter_origin_parses()
    counts = Counter(row["status"] for row in status_rows)
    eras = Counter(row["era"] for row in status_rows)
    print(f"releases: {len(status_rows)}  observations: {len(obs_rows)}")
    print("status:", dict(counts))
    print("era:", dict(eras))
    if args.write:
        status_path, obs_path = write_outputs(status_rows, obs_rows)
        print(f"Wrote {status_path}")
        print(f"Wrote {obs_path}")
    return 0


def _parse_switch(raw: str) -> tuple[str, bool]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("switch must be name=true|false")
    name, value = raw.split("=", 1)
    name = name.strip()
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return name, True
    if lowered in {"0", "false", "no", "off"}:
        return name, False
    raise argparse.ArgumentTypeError(f"invalid switch value {value!r}")


def cmd_submit_run(args: argparse.Namespace) -> int:
    """Submit a Visa run; optionally execute inline or wait for the worker (LON-23)."""
    import json
    import time
    import uuid

    from longaeva_app.db.models import Run
    from longaeva_app.db.session import get_session_factory
    from longaeva_app.runs.inputs import (
        ensure_default_baseline,
        parse_aware_utc,
        resolve_fixture_by_origin_date,
    )
    from longaeva_app.runs.service import submit_run
    from longaeva_app.worker.queue import claim_next_job, execute_job

    fixture = resolve_fixture_by_origin_date(args.origin)
    cutoff = parse_aware_utc(fixture.cutoff_utc)
    switches = dict(args.switch or [])
    factory = get_session_factory()
    with factory() as session:
        if args.scenario:
            scenario_id = uuid.UUID(args.scenario)
        else:
            scenario = ensure_default_baseline(session, cutoff_ts=cutoff, company="visa")
            session.commit()
            scenario_id = scenario.id
        run = submit_run(
            session,
            scenario_id=scenario_id,
            cutoff_ts=cutoff,
            seed=int(args.seed),
            n_paths=int(args.n_paths),
            n_quarters=int(args.n_quarters),
            switches=switches,
        )
        session.commit()
        run_id = run.id
        job_id = run.job_id
    if args.inline:
        if job_id is None:
            print("submitted run has no job_id", flush=True)
            return 2
        claimed = claim_next_job(factory, "inline")
        if claimed != job_id:
            print(f"expected to claim {job_id}, got {claimed}", flush=True)
            return 2
        execute_job(factory, job_id, "inline")
    elif args.wait is not None:
        deadline = time.monotonic() + float(args.wait)
        while time.monotonic() < deadline:
            with factory() as session:
                row = session.get(Run, run_id)
                if row is not None and row.status in {"succeeded", "failed"}:
                    break
            time.sleep(0.25)
    with factory() as session:
        row = session.get(Run, run_id)
        payload = {
            "run_id": str(run_id),
            "job_id": str(job_id) if job_id else None,
            "status": None if row is None else row.status,
            "outputs_hash": None if row is None else row.outputs_hash,
            "error": None if row is None else row.error,
            "origin_label": fixture.origin_date.isoformat(),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        if row is None:
            return 2
        if args.inline or args.wait is not None:
            return 0 if row.status == "succeeded" else 1
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """Replay a saved run and compare output hashes (LON-23 / UF-06)."""
    import json
    import uuid

    from longaeva_app.api.deps import get_artifact_store
    from longaeva_app.db.session import get_session_factory
    from longaeva_app.runs.errors import RunError
    from longaeva_app.runs.service import replay_run

    run_id = uuid.UUID(args.run_id)
    factory = get_session_factory()
    store = get_artifact_store()
    with factory() as session:
        try:
            report = replay_run(session, run_id, artifact_store=store)
        except RunError as exc:
            print(exc.message, flush=True)
            return 2
    if args.json:
        payload = dict(report)
        payload["run_id"] = str(payload["run_id"])
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(f"status={report['status']} recorded={report['recorded_outputs_hash']}")
        print(f"recomputed={report['recomputed_outputs_hash']}")
        print(f"llm_provider={report['llm_provider']!r} differences={report['differences']}")
    status = report["status"]
    if status in {"exact_match", "numerically_equivalent"}:
        return 0
    if status in {"mismatch", "inputs_changed"}:
        return 1
    return 2


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

    parse_visa = sub.add_parser(
        "parse-visa",
        help="Parse retained Visa releases and 10-Q/10-K tables (LON-14, offline)",
    )
    parse_visa.add_argument(
        "--write",
        action="store_true",
        help="Regenerate data/fixtures/visa_releases/observations.csv and parse_status.csv",
    )
    parse_visa.set_defaults(func=cmd_parse_visa)

    submit = sub.add_parser("submit-run", help="Submit a Visa simulation run (LON-23)")
    submit.add_argument("--origin", required=True, help="Origin date YYYY-MM-DD (LON-3 fixture)")
    submit.add_argument("--scenario", default=None, help="Scenario UUID; default: uncalibrated baseline")
    submit.add_argument("--seed", type=int, default=0, help="RNG seed")
    submit.add_argument("--n-paths", type=int, default=5000, help="Monte Carlo paths")
    submit.add_argument("--n-quarters", type=int, default=4, help="Horizon in fiscal quarters")
    submit.add_argument(
        "--switch",
        action="append",
        default=[],
        type=_parse_switch,
        help="Ablation switch name=true|false (repeatable)",
    )
    submit.add_argument("--inline", action="store_true", help="Execute in this process instead of the worker")
    submit.add_argument("--wait", type=float, default=None, help="Seconds to wait for the worker")
    submit.set_defaults(func=cmd_submit_run)

    replay = sub.add_parser("replay", help="Replay a saved run and compare hashes (LON-23)")
    replay.add_argument("run_id", help="Run UUID")
    replay.add_argument("--json", action="store_true", help="Print the full replay report as JSON")
    replay.set_defaults(func=cmd_replay)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
