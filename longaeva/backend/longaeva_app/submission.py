"""Final-export acceptance checks. Run only against the disposable verification stack."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy import func, select

from longaeva_app.config import PACKAGE_ROOT, get_settings
from longaeva_app.db.session import get_session_factory
from longaeva_app.demo import TABLES, load_bundle, seed_demo
from longaeva_app.evaluation.report import update_report
from longaeva_app.storage.local import LocalArtifactStore


class VerificationError(ValueError):
    """A final-export acceptance criterion did not pass."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def validate_inventory(root: Path) -> int:
    with (root / "docs/data-license-inventory.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    paths = [row["path"] for row in rows]
    expected = {p.relative_to(root).as_posix() for p in (root / "data").rglob("*") if p.is_file()}
    require(len(paths) == len(set(paths)) and set(paths) == expected, "Data license inventory coverage differs")
    for row in rows:
        path = root / row["path"]
        require(hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"], f"Inventory checksum: {row['path']}")
        require(
            all(row.get(key) for key in ("authorship", "retention_decision", "terms_or_provenance")),
            "Missing provenance",
        )
    return len(rows)


def check_replay(report: dict[str, Any], *, bundled: bool) -> None:
    require(report.get("llm_provider") == "", "Replay used a provider")
    status = report.get("status")
    if status == "exact_match":
        require(bool(report.get("recorded_outputs_hash")), "Missing recorded replay hash")
        require(report["recorded_outputs_hash"] == report.get("recomputed_outputs_hash"), "Replay hashes differ")
    else:
        error = report.get("max_relative_difference")
        require(
            bundled and status == "numerically_equivalent" and isinstance(error, (int, float)) and 0 <= error <= 1e-9,
            "Replay outside permitted runtime tolerance",
        )


def check_evidence(state: dict[str, Any]) -> None:
    evidence = state.get("evidence", {})
    require(bool(evidence), "Missing starting-state evidence")
    require(
        all(not value.get("unavailable_reason") for value in evidence.values()), "Unavailable starting-state evidence"
    )


def request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()


def replay_all(client: httpx.Client, bundle: dict[str, Any], new_ids: list[str]) -> list[dict[str, Any]]:
    results = []
    for run_id, bundled in [(row["id"], True) for row in bundle["tables"]["run"]] + [(i, False) for i in new_ids]:
        report = request(client, "POST", f"/runs/{run_id}/replay")
        check_replay(report, bundled=bundled)
        results.append(report)
    return results


def demo_checks(client: httpx.Client, bundle: dict[str, Any]) -> dict[str, Any]:
    inventory_count = validate_inventory(PACKAGE_ROOT)
    require(update_report(check=True), "Evaluation report is stale")
    factory = get_session_factory()
    with factory() as session:
        counts = {name: session.scalar(select(func.count()).select_from(cls)) for name, cls in TABLES.items()}
    require(counts == {name: len(rows) for name, rows in bundle["tables"].items()}, "Startup seed counts differ")
    require(counts["run"] == 7, "Expected seven seeded runs")
    forecast_counts = dict(Counter(row["kind"] for row in bundle["tables"]["forecast"]))
    require(forecast_counts == {"retrospective": 40, "prospective": 20}, "Unexpected forecast archive counts")
    for kind, count in forecast_counts.items():
        require(
            len(request(client, "GET", "/forecasts", params={"kind": kind, "limit": 200})) == count, "Missing forecasts"
        )
    for origin in bundle["origins"]:
        check_evidence(request(client, "GET", f"/workspace/origins/{origin}"))
    for link in bundle["links"]:
        parsed = urlparse(link["path"])
        if parsed.path == "/scenarios":
            query = {key: values[0] for key, values in parse_qs(parsed.query).items() if key != "origin"}
            require(
                bool(request(client, "GET", "/scenarios/comparison", params=query)["items"]), "Missing saved comparison"
            )
    observations = request(client, "GET", "/observations", params={"company": "booking"})
    require(bool(observations), "Missing Booking observations")
    for row in observations:
        evidence = request(
            client, "GET", f"/observations/{row['id']}/evidence", params={"cutoff_ts": "2026-07-28T20:05:26Z"}
        )
        require(not evidence.get("unavailable_reason"), "Missing observation evidence")
    # Add a review in the disposable stack, then prove reseeding preserves it.
    review = request(
        client,
        "POST",
        "/review-decisions",
        json={
            "observation_id": observations[0]["id"],
            "decision": "reject",
            "rationale": "Final export reseed preservation check",
            "decided_by": "export-verifier",
        },
    )
    reseed = seed_demo(factory, LocalArtifactStore(get_settings().artifact_dir))
    require(all(item["imported"] == 0 for item in reseed["counts"].values()), "Reseed imported duplicate rows")
    reviews = request(client, "GET", "/review-decisions", params={"observation_id": observations[0]["id"]})
    require(any(row["id"] == review["id"] for row in reviews), "Reseed lost the new review")
    observation = request(client, "GET", f"/observations/{observations[0]['id']}")
    require(observation["review_status"] == "rejected", "Reseed reset review status")
    # Restore acceptance for the following independent scenario checks.
    request(
        client,
        "POST",
        "/review-decisions",
        json={
            "observation_id": observations[0]["id"],
            "decision": "accept",
            "rationale": "Restore fixture acceptance after reseed check",
            "decided_by": "export-verifier",
        },
    )
    full_model = request(client, "GET", "/evaluation/reports/full_model")
    require(full_model["forecast"]["n_scored"] == 16, "Unexpected scored-origin count")
    require(request(client, "GET", "/evaluation/reports/failure_case")["status"] == "available", "Missing failure case")
    catalog = request(client, "GET", "/evaluation/reports")
    # Existing catalog/report validation checks every retained report artifact.
    require(bool(catalog), "Missing report catalog")
    baseline = next(
        row for row in bundle["tables"]["run"] if row["cutoff_ts"].startswith("2024-07-23") and not row["interventions"]
    )
    for endpoint in ("bridge", "actions"):
        result = request(client, "POST", f"/valuation/{endpoint}", json={"run_id": baseline["id"]})
        require(result.get("status") != "unsupported", f"Demo valuation {endpoint} unsupported")
    scenarios = [row for row in bundle["tables"]["scenario"] if row["id"] == baseline["scenario_id"]]
    require(len(scenarios) == 1, "Missing baseline scenario")
    group = str(uuid.uuid4())
    scenario_ids = []
    for name, interventions in (
        ("baseline", []),
        ("mix", [{"type": "mix_shift_conserving_total", "cross_border_change": -0.1, "start_quarter": 1}]),
        ("spend", [{"type": "total_spend_reduction", "reduction": 0.05, "start_quarter": 1}]),
    ):
        scenario = request(
            client,
            "POST",
            "/scenarios",
            json={
                "company": "visa",
                "name": f"final-export-{name}",
                "parameter_set_id": scenarios[0]["parameter_set_id"],
                "pair_group_id": group,
                "interventions": interventions,
            },
        )
        scenario_ids.append(scenario["id"])
    runs = request(
        client,
        "POST",
        "/scenarios/pair-runs",
        json={
            "scenario_ids": scenario_ids,
            "baseline_scenario_id": scenario_ids[0],
            "cutoff_ts": baseline["cutoff_ts"],
            "seed": 22,
            "n_paths": 5000,
            "n_quarters": 4,
        },
    )
    new_ids = [row["id"] for row in runs]
    require(len(new_ids) == 3, "Expected three paired worker runs")
    deadline = time.monotonic() + 180
    while True:
        runs = [request(client, "GET", f"/runs/{identifier}") for identifier in new_ids]
        require(all(row["status"] != "failed" for row in runs), "Paired worker run failed")
        if all(row["status"] == "succeeded" for row in runs):
            break
        require(time.monotonic() < deadline, "Paired worker runs timed out")
        time.sleep(1)
    for run in runs:
        require(run["seed"] == 22 and run["n_paths"] == 5000 and run["n_quarters"] == 4, "Pair settings differ")
        require(bool(run["job_id"]), "Paired run did not use the worker")
        require(bool(request(client, "GET", f"/runs/{run['id']}/results")), "Missing paired results")
    baseline_id = next(row["id"] for row in runs if row["scenario_id"] == scenario_ids[0])
    for row in runs:
        if row["id"] == baseline_id:
            continue
        query = {"run_id": row["id"], "baseline_run_id": baseline_id}
        comparison = request(client, "GET", "/scenarios/comparison", params=query)
        require(bool(comparison["items"]) and comparison["seed"] == 22, "Missing paired differences")
        if row["scenario_id"] == scenario_ids[1]:
            volume = [item for item in comparison["items"] if item["metric"] == "payments_volume_nominal_us"]
            require(
                len(volume) == 4 and all(abs(item["difference_mean"]) < 1e-9 for item in volume),
                "Mix shift changed total volume",
            )
        attribution = request(client, "GET", "/scenarios/attribution", params=query)
        require(
            attribution["conditional_on_model"] and bool(attribution["contributions"]),
            "Missing conditional attribution",
        )
    with httpx.Client(base_url="http://web", timeout=30, trust_env=False) as web:
        for path in ("/", "/guide", "/state", "/scenarios", "/valuation", "/evaluation", "/replay", "/api/health"):
            web.get(path).raise_for_status()
    return {
        "inventory_files": inventory_count,
        "report_current": True,
        "seed_counts": counts,
        "forecast_counts": forecast_counts,
        "origins": bundle["origins"],
        "reseed_preserved_review": True,
        "n_scored": full_model["forecast"]["n_scored"],
        "new_run_ids": new_ids,
        "replays": replay_all(client, bundle, new_ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("demo", "replay"), required=True)
    parser.add_argument("--run-id", nargs="*", default=[], type=uuid.UUID)
    args = parser.parse_args()
    settings = get_settings()
    require(
        not any(
            (
                settings.llm_provider,
                settings.llm_model,
                settings.llm_base_url,
                settings.sec_user_agent,
                settings.openai_api_key.get_secret_value(),
                settings.anthropic_api_key.get_secret_value(),
                settings.gemini_api_key.get_secret_value(),
            )
        ),
        "Provider/collection configuration is not empty",
    )
    bundle = load_bundle()
    with httpx.Client(base_url="http://api:8000", timeout=180, trust_env=False) as client:
        result = (
            demo_checks(client, bundle)
            if args.phase == "demo"
            else {
                "replays": replay_all(client, bundle, [str(identifier) for identifier in args.run_id]),
            }
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
