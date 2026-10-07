"""Longaeva CLI entrypoints."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

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


def cmd_export_zip(args: argparse.Namespace) -> int:
    """Build the submission ZIP (LON-24). Guard findings abort with no ZIP written."""
    from longaeva_app.export_bundle import ExportBundleError, build_export_zip, load_forbid_file, summary_payload
    from longaeva_app.isolation_guard import format_findings, resolve_root

    root = Path(args.root).resolve() if args.root else resolve_root()
    forbid: tuple[str, ...] = ()
    if args.forbid_file:
        forbid = load_forbid_file(Path(args.forbid_file))
    try:
        summary = build_export_zip(root, Path(args.output), forbid=forbid)
    except ExportBundleError as exc:
        print(format_findings(exc.findings), flush=True)
        return 1
    print(json.dumps(summary_payload(summary), indent=2, sort_keys=True))
    return 0


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


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Chronological Visa calibration (LON-20). Prefer the host venv for --write."""
    from longaeva_app.companies.visa.calibration import (
        calibrate,
        default_origin_dates,
        persist_calibrated,
        write_artifact,
    )

    origins = list(args.origin) if args.origin else default_origin_dates()
    summaries: list[dict[str, object]] = []
    for origin_date in origins:
        result = calibrate(origin_date, run_sensitivity=not bool(args.skip_sensitivity))
        summary: dict[str, object] = {
            "origin_date": result.origin_date,
            "origin_label": result.origin_label,
            "cutoff_ts": result.cutoff_ts.isoformat().replace("+00:00", "Z"),
            "weights": result.weights,
            "content_hash": result.pooled.computed_content_hash(),
            "result_hash": result.result_hash,
            "payments_volume_growth": result.pooled.values["payments_volume_growth"],
        }
        if args.write:
            path = write_artifact(result)
            summary["artifact"] = str(path)
            print(f"Wrote {path}")
        if args.persist:
            from longaeva_app.db.session import get_session_factory

            factory = get_session_factory()
            with factory() as session:
                param_set, scenario = persist_calibrated(result, session)
                session.commit()
                summary["parameter_set_id"] = str(param_set.id)
                summary["scenario_id"] = str(scenario.id)
                print(f"Persisted parameter_set={param_set.id} scenario={scenario.id}")
        summaries.append(summary)
        if not args.json:
            print(
                f"{result.origin_date} {result.origin_label}: "
                f"pv_growth={result.pooled.values['payments_volume_growth']:.4f} "
                f"weights={{{', '.join(f'{k}={v:.3f}' for k, v in result.weights.items())}}}"
            )
    if args.json:
        print(json.dumps(summaries if len(summaries) > 1 else summaries[0], indent=2, sort_keys=True))
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


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Run the Visa evaluation harness, or a LON-29 baseline, across origins."""
    import json
    from pathlib import Path

    from longaeva_app.api.deps import get_artifact_store
    from longaeva_app.db.session import get_session_factory
    from longaeva_app.evaluation.ablations import ABLATION_VARIANTS, run_ablation, run_ablations, write_persistence
    from longaeva_app.evaluation.baselines import BASELINE_VARIANTS, format_comparison, run_baseline
    from longaeva_app.evaluation.harness import format_tables, report_to_dict, run_evaluation, write_report

    variant = str(args.variant)
    if args.output and variant in {"all", "ablations"}:
        print("--output writes one variant; use --output-dir with --variant all", flush=True)
        return 2
    variants = ["full_model", *BASELINE_VARIANTS] if variant == "all" else [variant]
    factory = get_session_factory()
    store = get_artifact_store()
    reports = []
    window = str(args.window)
    origin_dates = list(args.origin) or None
    n_paths = int(args.n_paths)
    base_seed = int(args.seed)
    use_cache = not bool(args.no_cache)
    if variant == "ablations":
        import sys

        suite = run_ablations(
            factory,
            window=window,
            origin_dates=origin_dates,
            n_paths=n_paths,
            base_seed=base_seed,
            use_cache=use_cache,
            artifact_store=store,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
        if args.output_dir:
            directory = Path(args.output_dir)
            for report in suite.profiles["central"]:
                write_report(report, directory / f"visa_{report.config.model_variant}.json")
            write_persistence(suite, directory)
        if args.json:
            print(json.dumps(suite.persistence, indent=2, sort_keys=True))
        else:
            print(format_comparison(suite.profiles["central"]))
            print("Persistence: all 13 predefined profiles complete; see visa_ablation_persistence.json")
        return 0
    for name in variants:
        if name == "llm_baseline":
            from longaeva_app.evaluation.baselines.llm_docs import run_llm_docs

            report = run_llm_docs(
                window=window,
                origin_dates=origin_dates,
                cache_path=Path(args.llm_cache),
                input_dir=Path(args.llm_input_dir),
            )
        elif name in ABLATION_VARIANTS:
            report = run_ablation(
                name,
                factory,
                window=window,
                origin_dates=origin_dates,
                n_paths=n_paths,
                base_seed=base_seed,
                use_cache=use_cache,
                artifact_store=store,
            )
        elif name == "full_model":
            report = run_evaluation(
                factory,
                window=window,
                origin_dates=origin_dates,
                n_paths=n_paths,
                base_seed=base_seed,
                use_cache=use_cache,
                artifact_store=store,
            )
        else:
            report = run_baseline(
                name,
                factory,
                window=window,
                origin_dates=origin_dates,
                n_paths=n_paths,
                base_seed=base_seed,
                use_cache=use_cache,
                artifact_store=store,
            )
        reports.append(report)
        if args.output:
            write_report(report, Path(args.output))
            print(f"wrote {args.output}", flush=True)
        if args.output_dir:
            path = Path(args.output_dir) / f"visa_{name}.json"
            write_report(report, path)
            print(f"wrote {path}", flush=True)
    if args.json:
        payload = report_to_dict(reports[0]) if len(reports) == 1 else [report_to_dict(item) for item in reports]
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif len(reports) == 1:
        print(format_tables(reports[0]))
    else:
        for item in reports:
            print(format_tables(item))
            print()
        print(format_comparison(reports))
    if any(origin.error and not origin.error.startswith("not run (") for item in reports for origin in item.origins):
        return 1
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract observations from selected passages (LON-16)."""
    import time
    from typing import Any

    from longaeva_app.api.deps import get_artifact_store
    from longaeva_app.config import get_settings
    from longaeva_app.db.models import Job
    from longaeva_app.db.session import get_session_factory
    from longaeva_app.extract.llm import ExtractionError, load_passages, run_extraction
    from longaeva_app.extract.providers import build_provider, describe_extraction

    settings = get_settings()
    described = describe_extraction(settings, provider=args.provider, model=args.model)
    if args.status:
        print(
            json.dumps(
                {
                    "enabled": described.enabled,
                    "provider": described.provider,
                    "model": described.model,
                    "configured_providers": described.configured_providers,
                    "disabled_reason": described.disabled_reason,
                    "max_passages": described.max_passages,
                    "max_passage_chars": described.max_passage_chars,
                    "prompt_version": described.prompt_version,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if described.enabled else 2
    if not described.enabled:
        print(described.disabled_reason or "Extraction is disabled.", flush=True)
        print("Set LLM_PROVIDER and the matching API key. See docs/extraction.md.", flush=True)
        return 2

    factory = get_session_factory()
    with factory() as session:
        try:
            passage_ids = _select_passages(session, args)
        except ExtractionError as exc:
            print(exc.message, flush=True)
            return 2
        if args.inline:
            provider = build_provider(settings, provider=args.provider, model=args.model)
            if provider is None:
                print(described.disabled_reason or "Extraction is disabled.", flush=True)
                return 2
            try:
                passages = load_passages(session, passage_ids, settings=settings)
                report = run_extraction(
                    session,
                    passages,
                    provider=provider,
                    settings=settings,
                    store=get_artifact_store(),
                )
                session.commit()
            except ExtractionError as exc:
                print(exc.message, flush=True)
                return 2
            finally:
                provider.close()
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
            return 0

        payload: dict[str, Any] = {"document_text_ids": [str(item) for item in passage_ids]}
        if args.provider:
            payload["provider"] = args.provider
        if args.model:
            payload["model"] = args.model
        job = Job(type="extract", payload=payload, status="queued")
        session.add(job)
        session.commit()
        job_id = job.id

    wait_sec = 180.0 if args.wait is None else float(args.wait)
    deadline = time.monotonic() + wait_sec
    outcome: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        with factory() as session:
            row = session.get(Job, job_id)
            if row is not None and row.status in {"succeeded", "failed"}:
                outcome = {
                    "job_id": str(job_id),
                    "status": row.status,
                    "error": row.error,
                    "result": row.result,
                }
                break
        time.sleep(0.5)
    if outcome is None:
        print(f"extract job {job_id} did not finish within {wait_sec:.0f}s", flush=True)
        return 2
    print(json.dumps(outcome, indent=2, sort_keys=True, default=str))
    if outcome["status"] != "succeeded":
        return 1
    return 0


def _select_passages(session: Session, args: argparse.Namespace) -> list[uuid.UUID]:
    from sqlalchemy import select

    from longaeva_app.db.models import DocumentText, Source
    from longaeva_app.extract.llm import ExtractionError

    if args.passage:
        return [uuid.UUID(item) for item in args.passage]
    if not args.source_key or not args.contains:
        raise ExtractionError("Pass --passage, or both --source-key and --contains.")
    source = session.execute(
        select(Source)
        .where(Source.attributes.contains({"manifest_key": args.source_key}))
        .order_by(Source.retrieval_ts.desc())
        .limit(1)
    ).scalar_one_or_none()
    if source is None:
        raise ExtractionError(f"No collected source for manifest key {args.source_key!r}.")
    rows = list(
        session.scalars(
            select(DocumentText)
            .where(DocumentText.source_id == source.id)
            .where(DocumentText.text.contains(args.contains))
            .order_by(DocumentText.page, DocumentText.char_start)
        ).all()
    )
    if not rows:
        raise ExtractionError(f"No passage under {args.source_key!r} contains {args.contains!r}.")
    return [row.id for row in rows]


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


def cmd_pair_run(args: argparse.Namespace) -> int:
    """Run a calibrated baseline against mix-shift and spend-reduction variants (LON-22)."""
    from typing import Any

    from longaeva_app.api.deps import get_artifact_store
    from longaeva_app.companies.visa.calibration import artifact_path, persist_calibrated
    from longaeva_app.db.models import Run
    from longaeva_app.db.session import get_session_factory
    from longaeva_app.evaluation.harness import load_calibration_artifact
    from longaeva_app.runs.inputs import parse_aware_utc, resolve_fixture_by_origin_date
    from longaeva_app.scenarios.errors import ScenarioError
    from longaeva_app.scenarios.service import (
        attribute_saved_runs,
        compare_saved_runs,
        create_scenario,
        submit_pair_runs,
    )
    from longaeva_app.worker.queue import claim_next_job, execute_job

    path = artifact_path(args.origin)
    if not path.is_file():
        print(f"No calibration artifact at {path}", flush=True)
        return 2
    fixture = resolve_fixture_by_origin_date(args.origin)
    cutoff = parse_aware_utc(fixture.cutoff_utc)
    calibrated = load_calibration_artifact(path)
    mix_change = float(args.mix_change)
    reduction = float(args.reduction)
    group = uuid.uuid4()
    factory = get_session_factory()
    with factory() as session:
        _param_set, baseline = persist_calibrated(calibrated, session)
        baseline.pair_group_id = group
        mix = create_scenario(
            session,
            company="visa",
            name=f"mix-shift-{mix_change:+.4f}",
            parameter_set_id=baseline.parameter_set_id,
            interventions=[
                {
                    "type": "mix_shift_conserving_total",
                    "cross_border_change": mix_change,
                    "start_quarter": 1,
                }
            ],
            pair_group_id=group,
            parameter_overrides={},
        )
        spend = create_scenario(
            session,
            company="visa",
            name=f"spend-reduction-{reduction:.4f}",
            parameter_set_id=baseline.parameter_set_id,
            interventions=[{"type": "total_spend_reduction", "reduction": reduction, "start_quarter": 1}],
            pair_group_id=group,
            parameter_overrides={},
        )
        try:
            runs = submit_pair_runs(
                session,
                scenario_ids=[baseline.id, mix.id, spend.id],
                baseline_scenario_id=baseline.id,
                cutoff_ts=cutoff,
                seed=int(args.seed),
                n_paths=int(args.n_paths),
                n_quarters=int(args.n_quarters),
                switches={},
            )
        except ScenarioError as exc:
            print(exc.message, flush=True)
            return 2
        session.commit()
        job_ids = [run.job_id for run in runs]
        run_ids = {
            "baseline": runs[0].id,
            "mix_shift": runs[1].id,
            "spend_reduction": runs[2].id,
        }
    if args.inline:
        if any(job_id is None for job_id in job_ids):
            print("submitted run has no job_id", flush=True)
            return 2
        # Jobs committed together share created_at, so the queue orders them by id,
        # not by the baseline-then-variant list. Claim until each submitted job runs.
        pending: set[uuid.UUID] = {job_id for job_id in job_ids if job_id is not None}
        while pending:
            claimed = claim_next_job(factory, "inline")
            if claimed not in pending:
                print(f"expected to claim one of {sorted(str(item) for item in pending)}, got {claimed}", flush=True)
                return 2
            execute_job(factory, claimed, "inline")
            pending.remove(claimed)
    store = get_artifact_store()
    with factory() as session:
        rows = {name: session.get(Run, run_id) for name, run_id in run_ids.items()}
        if any(row is None or row.status != "succeeded" for row in rows.values()):
            print(json.dumps({name: None if row is None else row.status for name, row in rows.items()}, indent=2))
            return 1
        mix_cmp = compare_saved_runs(session, store, run_id=run_ids["mix_shift"], baseline_run_id=run_ids["baseline"])
        spend_cmp = compare_saved_runs(
            session, store, run_id=run_ids["spend_reduction"], baseline_run_id=run_ids["baseline"]
        )
        mix_attr = attribute_saved_runs(
            session,
            store,
            run_id=run_ids["mix_shift"],
            baseline_run_id=run_ids["baseline"],
            metric="net_revenue",
        )
        spend_attr = attribute_saved_runs(
            session,
            store,
            run_id=run_ids["spend_reduction"],
            baseline_run_id=run_ids["baseline"],
            metric="net_revenue",
        )

    def _series(comparison: dict[str, Any], metric: str) -> list[dict[str, Any]]:
        return [
            {
                "quarter_index": item["quarter_index"],
                "period_label": item["period_label"],
                "difference_mean": item["difference_mean"],
                "p05": item["quantiles"].get("0.05"),
                "p95": item["quantiles"].get("0.95"),
            }
            for item in comparison["items"]
            if item["metric"] == metric
        ]

    def _flags(attribution: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "parameter": item["parameter"],
                "normalized_sensitivity": item["normalized_sensitivity"],
                "support_score": item["support_score"],
                "flag": item["flag"],
            }
            for item in attribution["sensitivity"]
            if item["flag"]
        ]

    payload = {
        "origin": args.origin,
        "seed": int(args.seed),
        "n_paths": int(args.n_paths),
        "run_ids": {name: str(value) for name, value in run_ids.items()},
        "mix_shift": {
            "cross_border_change": mix_change,
            "payments_volume_difference": _series(mix_cmp, "payments_volume_nominal_us"),
            "service_revenue_difference": _series(mix_cmp, "service_revenue"),
            "international_revenue_difference": _series(mix_cmp, "international_transaction_revenue"),
            "net_revenue_difference": _series(mix_cmp, "net_revenue"),
            "verification": mix_attr["verification"],
            "flags": _flags(mix_attr),
            "top_sensitivity": [
                {
                    "parameter": item["parameter"],
                    "normalized_sensitivity": item["normalized_sensitivity"],
                    "support_score": item["support_score"],
                    "flag": item["flag"],
                }
                for item in mix_attr["sensitivity"][:5]
            ],
        },
        "spend_reduction": {
            "reduction": reduction,
            "payments_volume_difference": _series(spend_cmp, "payments_volume_nominal_us"),
            "service_revenue_difference": _series(spend_cmp, "service_revenue"),
            "international_revenue_difference": _series(spend_cmp, "international_transaction_revenue"),
            "net_revenue_difference": _series(spend_cmp, "net_revenue"),
            "verification": spend_attr["verification"],
            "flags": _flags(spend_attr),
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_rules_list(_args: argparse.Namespace) -> int:
    """Print the code-defined mapping-rule registry. Does not touch the database."""
    from longaeva_app.review.rules import REGISTRY

    for spec in REGISTRY:
        target = spec.target_parameter or "-"
        print(f"{spec.rule_key}\tv{spec.version}\t{spec.kind}\t{spec.source_family}\t{spec.input_type}\t{target}")
    return 0


def cmd_apply_rules(args: argparse.Namespace) -> int:
    """Preview or apply mapping rules for one Visa origin (LON-21)."""
    from sqlalchemy import select

    from longaeva_app.db.models import ParameterSet, Scenario
    from longaeva_app.db.session import get_session_factory
    from longaeva_app.review.apply import ApplyError, apply_rules, preview_rules
    from longaeva_app.review.gate_fixtures import load_gate_fixtures
    from longaeva_app.review.rules import RuleRegistryError
    from longaeva_app.review.service import ReviewError
    from longaeva_app.runs.inputs import ensure_default_baseline, parse_aware_utc, resolve_fixture_by_origin_date

    fixture = resolve_fixture_by_origin_date(args.origin)
    cutoff = parse_aware_utc(fixture.cutoff_utc)
    families = list(args.families) if args.families else None
    factory = get_session_factory()
    try:
        with factory() as session:
            if args.load_gate_fixtures:
                load_gate_fixtures(session, accept=True, families=set(families) if families else None)
                session.commit()
            if args.parameter_set_id:
                parameter_set = session.get(ParameterSet, uuid.UUID(args.parameter_set_id))
                if parameter_set is None:
                    print(f"Parameter set {args.parameter_set_id} not found")
                    return 1
            else:
                parameter_set = session.scalars(
                    select(ParameterSet)
                    .join(Scenario, Scenario.parameter_set_id == ParameterSet.id)
                    .where(Scenario.name == "calibrated")
                    .where(Scenario.company == "visa")
                    .where(ParameterSet.cutoff_ts == cutoff)
                    .order_by(ParameterSet.created_at.desc())
                ).first()
                if parameter_set is None:
                    scenario = ensure_default_baseline(session, cutoff_ts=cutoff)
                    session.flush()
                    parameter_set = session.get(ParameterSet, scenario.parameter_set_id)
            if parameter_set is None:
                print("No parameter set for that origin")
                return 1
            if args.dry_run:
                result = preview_rules(
                    session,
                    parameter_set.id,
                    None,
                    families,
                    decided_by=args.decided_by,
                    rationale=args.rationale,
                )
            else:
                result = apply_rules(
                    session,
                    parameter_set.id,
                    None,
                    families,
                    decided_by=args.decided_by,
                    rationale=args.rationale,
                )
                session.commit()
            print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
            return 0
    except (ApplyError, ReviewError, RuleRegistryError) as exc:
        print(exc.message if hasattr(exc, "message") else str(exc))
        return 1


def cmd_valuation_multiples(args: argparse.Namespace) -> int:
    """Rebuild the trailing P/E history from bundled SEC originals (LON-25)."""
    from datetime import UTC, datetime

    from longaeva_app.valuation.multiples import FIXTURE_PATH, PeHistoryError, build_history, pe_band, write_history

    try:
        rows = build_history()
    except PeHistoryError as exc:
        print(str(exc))
        return 1
    if args.write:
        path = write_history(rows)
        shown = path.relative_to(PACKAGE_ROOT) if path.is_relative_to(PACKAGE_ROOT) else path
        print(f"Wrote {shown} ({len(rows)} quarters)")
    else:
        shown = FIXTURE_PATH.relative_to(PACKAGE_ROOT)
        print(f"{len(rows)} quarters (pass --write to update {shown})")
    for row in rows:
        print(
            f"{row.period_label} price={row.price_quote} ttm_eps={row.ttm_eps_text} "
            f"pe={row.trailing_pe_text} accepted={row.price_acceptance_utc.strftime('%Y-%m-%d')}"
        )
    band = pe_band(datetime(9999, 1, 1, tzinfo=UTC), rows=rows)
    if band is not None:
        print(f"full-sample low/mid/high = {band.low:.6f} / {band.mid:.6f} / {band.high:.6f}")
    return 0


def cmd_evaluate_portfolio(args: argparse.Namespace) -> int:
    """Fetch benchmarks in memory; Visa scoring stays explicitly not run."""
    from longaeva_app.evaluation.portfolio import (
        format_portfolio_table,
        run_portfolio_evaluation,
        write_portfolio_report,
    )

    try:
        report = run_portfolio_evaluation(window=args.window, origin_dates=args.origin or None)
    except ValueError as exc:
        print(f"Portfolio evaluation refused: {exc}")
        return 1
    if args.output:
        write_portfolio_report(report, Path(args.output))
    print(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) if args.json else format_portfolio_table(report)
    )
    return int(any(source["status"] != "ok" for source in report["sources"]))


def cmd_evaluate_extraction(args: argparse.Namespace) -> int:
    from longaeva_app.evaluation.extraction_scoring import load_corpus, load_review, score_extractions, write_report

    try:
        gold, passages = load_corpus(Path(args.gold), Path(args.passages))
        review = load_review(Path(args.review), Path(args.gold))
        cached = json.loads(Path(args.cached).read_text()) if Path(args.cached).is_file() else {"calls": []}
        report = score_extractions(gold, passages, cached, review)
        write_report(report, Path(args.output))
    except (OSError, ValueError) as exc:
        print(f"Extraction scoring failed: {exc}")
        return 2
    print(json.dumps(report["coverage"], sort_keys=True))
    return 0


def cmd_capture_llm_baseline(args: argparse.Namespace) -> int:
    from longaeva_app.config import Settings, get_settings
    from longaeva_app.db.session import get_session_factory
    from longaeva_app.evaluation.baselines.common import split_origins
    from longaeva_app.evaluation.baselines.llm_docs import (
        ForecastResponse,
        capture_forecasts,
        load_packs,
    )
    from longaeva_app.evaluation.llm_inputs import prepare_packs, verify_originals
    from longaeva_app.extract.providers import build_provider, describe_extraction

    origins, _excluded = split_origins(window=args.window, origin_dates=args.origin or None)
    directory = Path(args.input_dir)
    try:
        if args.prepare_only or any(not (directory / f"{o.origin_date}.json").is_file() for o in origins):
            prepare_packs(get_session_factory(get_settings().database_url), origins, directory)
        packs = load_packs(origins, directory)
        if args.prepare_only:
            print(f"Prepared {len(packs)} evidence packs; no provider calls")
            return 0
        for pack in packs.values():
            verify_originals(pack)
        settings = Settings(**{"_env_file": args.credentials_env}) if args.credentials_env else Settings()
        described = describe_extraction(settings, provider=args.provider, model=args.model)
        provider = build_provider(
            settings,
            provider=args.provider,
            model=args.model,
            response_schema=ForecastResponse.model_json_schema(),
            schema_name="visa_forecast",
        )
        try:
            result = capture_forecasts(
                origins,
                packs,
                provider=provider,
                provider_name=args.provider,
                model=args.model,
                settings=settings,
                output=Path(args.output),
            )
        finally:
            if provider is not None:
                provider.close()
        if provider is None:
            print(described.disabled_reason or "not run (no provider)")
        return int(provider is None or any(c["status"] != "succeeded" for c in result["calls"]))
    except (OSError, ValueError) as exc:
        print(f"LLM baseline refused: {exc}")
        return 2


def cmd_capture_extraction(args: argparse.Namespace) -> int:
    from longaeva_app.config import Settings
    from longaeva_app.db.session import get_session_factory
    from longaeva_app.evaluation.extraction_capture import capture_extractions
    from longaeva_app.evaluation.extraction_scoring import load_corpus, load_review, require_reviewed
    from longaeva_app.extract.providers import build_provider

    gold, passages = load_corpus(Path(args.gold), Path(args.passages))
    review = load_review(Path(args.review), Path(args.gold))
    try:
        require_reviewed(review, gold)
    except ValueError as exc:
        print(str(exc))
        return 2
    settings = Settings(**{"_env_file": args.credentials_env}) if args.credentials_env else Settings()
    provider = build_provider(settings, provider="openai", model="gpt-5.4")
    if provider is None:
        print("OpenAI extraction is disabled: configure OPENAI_API_KEY at runtime.")
        return 2
    try:
        with get_session_factory(settings.database_url)() as session:
            result = capture_extractions(
                session,
                gold=gold,
                passages=passages,
                review=review,
                provider=provider,
                settings=settings,
                output=Path(args.output),
            )
    finally:
        provider.close()
    return int(any(c["status"] != "succeeded" for c in result["calls"]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="longaeva", description="Longaeva CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    from longaeva_app.evaluation.extraction_scoring import FIXTURE_DIR

    for command, func in [
        ("evaluate-extraction", cmd_evaluate_extraction),
        ("capture-extraction", cmd_capture_extraction),
    ]:
        extraction = sub.add_parser(
            command,
            help="Offline extraction scoring"
            if command.startswith("evaluate")
            else "Explicit bounded extraction capture after label review",
        )
        extraction.add_argument("--gold", default=str(FIXTURE_DIR / "gold.jsonl"))
        extraction.add_argument("--passages", default=str(FIXTURE_DIR / "passages.jsonl"))
        extraction.add_argument("--review", default=str(FIXTURE_DIR / "review.json"))
        if command.startswith("evaluate"):
            extraction.add_argument("--cached", default=str(FIXTURE_DIR / "cached.json"))
            extraction.add_argument("--output", default=str(PACKAGE_ROOT / "data/evaluation/extraction.json"))
        else:
            extraction.add_argument(
                "--credentials-env", default=None, help="Optional runtime .env file (never copied into the package)"
            )
            extraction.add_argument("--output", default=str(FIXTURE_DIR / "cached.json"))
        extraction.set_defaults(func=func)

    seed = sub.add_parser("seed-demo", help="Load bundled demo dataset (stub until LON-37)")
    seed.set_defaults(func=cmd_seed_demo)

    portfolio = sub.add_parser(
        "evaluate-portfolio", help="Independent benchmark windows; real Visa scoring not run (LON-28)"
    )
    portfolio.add_argument("--window", choices=["all", "primary", "extension"], default="all")
    portfolio.add_argument("--origin", action="append", default=[], help="Origin date YYYY-MM-DD (repeatable)")
    portfolio.add_argument("--output", default=None, help="Write aggregate-only report JSON")
    portfolio.add_argument("--json", action="store_true", help="Print aggregate-only report JSON")
    portfolio.set_defaults(func=cmd_evaluate_portfolio)

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

    export_zip = sub.add_parser(
        "export-zip",
        help="Build the submission ZIP from the isolation-guard export set (LON-24)",
    )
    export_zip.add_argument(
        "--root",
        default=None,
        help="Package root containing .exportignore (default: LONGAEVA_GUARD_ROOT or PACKAGE_ROOT)",
    )
    export_zip.add_argument(
        "--output",
        required=True,
        help="Destination ZIP path",
    )
    export_zip.add_argument(
        "--forbid-file",
        default=None,
        help="New-line separated identity strings that must not appear in any member",
    )
    export_zip.set_defaults(func=cmd_export_zip)

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

    calibrate_p = sub.add_parser(
        "calibrate",
        help="Fit Visa parameters as-of an origin cutoff (LON-20)",
    )
    calibrate_p.add_argument(
        "--origin",
        action="append",
        default=[],
        help="Origin date YYYY-MM-DD (repeatable; default: both LON-3 fixture origins)",
    )
    calibrate_p.add_argument(
        "--write",
        action="store_true",
        help="Write data/calibration/visa_<origin>.json (run from the host venv; Compose mounts data/ read-only)",
    )
    calibrate_p.add_argument(
        "--persist",
        action="store_true",
        help="Save the pooled parameter set and a calibrated scenario to the database",
    )
    calibrate_p.add_argument("--json", action="store_true", help="Print a JSON summary")
    calibrate_p.add_argument(
        "--skip-sensitivity",
        action="store_true",
        help="Skip the Monte Carlo sensitivity table (faster local iteration)",
    )
    calibrate_p.set_defaults(func=cmd_calibrate)

    submit = sub.add_parser("submit-run", help="Submit a Visa simulation run (LON-23)")
    submit.add_argument(
        "--origin",
        required=True,
        help="Origin date YYYY-MM-DD (committed fixture or buildable origins.csv row)",
    )
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

    pair = sub.add_parser("pair-run", help="Paired mix-shift and spend-reduction runs (LON-22)")
    pair.add_argument("--origin", required=True, help="Origin date YYYY-MM-DD with a calibration artifact")
    pair.add_argument("--seed", type=int, default=22, help="Shared RNG seed")
    pair.add_argument("--n-paths", type=int, default=5000, help="Monte Carlo paths")
    pair.add_argument("--n-quarters", type=int, default=4, help="Horizon in fiscal quarters")
    pair.add_argument("--mix-change", type=float, default=-0.10, help="Cross-border share change, e.g. -0.10")
    pair.add_argument("--reduction", type=float, default=0.05, help="Total payments-volume reduction, e.g. 0.05")
    pair.add_argument("--inline", action="store_true", help="Execute in this process instead of the worker")
    pair.set_defaults(func=cmd_pair_run)

    evaluate_p = sub.add_parser(
        "evaluate",
        help="Score the full Visa model or a baseline across eligible origins (LON-27, LON-29)",
    )
    evaluate_p.add_argument(
        "--origin",
        action="append",
        default=[],
        help="Origin date YYYY-MM-DD (repeatable; default: all scored candidates)",
    )
    evaluate_p.add_argument(
        "--window",
        choices=("all", "primary", "extension"),
        default="all",
        help="Origin window filter",
    )
    evaluate_p.add_argument("--n-paths", type=int, default=5000, help="Monte Carlo paths per origin")
    evaluate_p.add_argument("--seed", type=int, default=27000, help="Base seed (paired per origin)")
    evaluate_p.add_argument(
        "--variant",
        choices=(
            "full_model",
            "seasonal_trend",
            "financial_only",
            "guidance",
            "llm_baseline",
            "all",
            "no_external_commentary",
            "pooled_spending",
            "no_service_lag",
            "ablations",
        ),
        default="full_model",
        help="One model/baseline/ablation; all runs baselines, ablations runs the matched 13-profile suite",
    )
    evaluate_p.add_argument("--output", default=None, help="Write one variant's results JSON to this path")
    evaluate_p.add_argument(
        "--output-dir",
        default=None,
        help="Write visa_<variant>.json for each variant that ran",
    )
    evaluate_p.add_argument("--json", action="store_true", help="Print the full report as JSON")
    evaluate_p.add_argument("--llm-cache", default=str(PACKAGE_ROOT / "data/fixtures/llm_baseline/cached.json"))
    evaluate_p.add_argument("--llm-input-dir", default=str(PACKAGE_ROOT / "data/fixtures/llm_baseline"))
    evaluate_p.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore the calibration cache under ARTIFACT_DIR/evaluation/calibration/",
    )
    evaluate_p.set_defaults(func=cmd_evaluate)

    llm_capture = sub.add_parser("capture-llm-baseline", help="Explicit, bounded forecast capture (LON-30)")
    llm_capture.add_argument("--origin", action="append", default=[])
    llm_capture.add_argument("--window", choices=("all", "primary", "extension"), default="all")
    llm_capture.add_argument("--provider", choices=("openai", "anthropic", "gemini", "stub"), default="openai")
    llm_capture.add_argument("--model", default="gpt-5.4")
    llm_capture.add_argument("--credentials-env", default=None, help="Runtime credentials file, never copied/exported")
    llm_capture.add_argument("--input-dir", default=str(PACKAGE_ROOT / "data/fixtures/llm_baseline"))
    llm_capture.add_argument("--output", default=str(PACKAGE_ROOT / "data/fixtures/llm_baseline/cached.json"))
    llm_capture.add_argument(
        "--prepare-only", action="store_true", help="Verify and freeze evidence; no provider calls"
    )
    llm_capture.set_defaults(func=cmd_capture_llm_baseline)

    extract_p = sub.add_parser("extract", help="Extract observations from selected passages (LON-16)")
    extract_p.add_argument("--passage", action="append", default=[], help="document_text UUID (repeatable)")
    extract_p.add_argument("--source-key", default=None, help="Collected manifest key")
    extract_p.add_argument("--contains", default=None, help="Substring that selects passages of --source-key")
    extract_p.add_argument("--provider", default=None, help="anthropic, openai, gemini, or stub")
    extract_p.add_argument("--model", default=None, help="Model id; default is the provider's configured model")
    extract_p.add_argument("--inline", action="store_true", help="Run in this process instead of the worker")
    extract_p.add_argument("--wait", type=float, default=None, help="Seconds to wait for the worker (default 180)")
    extract_p.add_argument("--status", action="store_true", help="Print whether extraction is configured and exit")
    extract_p.set_defaults(func=cmd_extract)

    replay = sub.add_parser("replay", help="Replay a saved run and compare hashes (LON-23)")
    replay.add_argument("run_id", help="Run UUID")
    replay.add_argument("--json", action="store_true", help="Print the full replay report as JSON")
    replay.set_defaults(func=cmd_replay)

    rules_list = sub.add_parser("rules-list", help="Print the mapping-rule registry (LON-21)")
    rules_list.set_defaults(func=cmd_rules_list)

    apply_p = sub.add_parser("apply-rules", help="Apply mapping rules to a Visa parameter set (LON-21)")
    apply_p.add_argument("--origin", required=True, help="Origin date YYYY-MM-DD")
    apply_p.add_argument(
        "--parameter-set-id", default=None, help="Parameter set UUID (default: calibrated or baseline)"
    )
    apply_p.add_argument(
        "--load-gate-fixtures",
        action="store_true",
        help="Load and accept LON-4/LON-5/LON-8 fixtures before applying",
    )
    apply_p.add_argument("--families", action="append", default=[], help="Source family filter (repeatable)")
    apply_p.add_argument("--dry-run", action="store_true", help="Preview only; do not write a child set")
    apply_p.add_argument("--decided-by", default="cli", help="Name recorded on parameter updates")
    apply_p.add_argument(
        "--rationale",
        default="Applied the mapping-rule registry to reviewed observations published by the cutoff.",
        help="Reviewer rationale recorded on parameter updates",
    )
    apply_p.set_defaults(func=cmd_apply_rules)

    multiples = sub.add_parser(
        "valuation-multiples",
        help="Rebuild the SEC trailing P/E history used by the valuation bridge (LON-25)",
    )
    multiples.add_argument(
        "--write",
        action="store_true",
        help="Write data/fixtures/valuation/visa_pe_history.csv",
    )
    multiples.set_defaults(func=cmd_valuation_multiples)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
