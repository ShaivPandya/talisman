"""Deterministic, offline synthesis of retained evaluation rows."""

from __future__ import annotations

import csv
import json
import math
import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from longaeva_app.api.report_schemas import ForecastReport
from longaeva_app.hashing import content_hash, sha256_hex

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
BEGIN = "<!-- BEGIN GENERATED EVALUATION -->"
END = "<!-- END GENERATED EVALUATION -->"
VARIANTS = (
    "full_model",
    "seasonal_trend",
    "financial_only",
    "guidance",
    "llm_baseline",
    "no_external_commentary",
    "pooled_spending",
    "no_service_lag",
)
BASELINES = VARIANTS[1:5]
ABLATIONS = VARIANTS[5:]
INPUTS = {
    "observations_hash": "data/fixtures/visa_releases/observations.csv",
    "manifest_hash": "data/fixtures/visa_releases/sources/manifest.json",
    "origins_hash": "data/fixtures/origins.csv",
}
TARGETS = {
    "net_revenue": "Net revenue (GAAP, USD m)",
    "operating_profit_ex_special_items": "Operating profit (ex special items, USD m)",
    "payments_volume_growth_constant": "Payments volume (constant-dollar YoY, pp)",
    "cross_border_ex_intra_europe_growth_constant": "Cross-border (constant-dollar YoY, approximate, pp)",
    "processed_transactions_growth": "Transactions (count YoY, pp)",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def same_number(actual: Any, expected: float | None, context: str) -> None:
    """Saved floats have ten significant digits; allow accumulated rounding."""
    if expected is None:
        require(actual is None, f"{context}: expected unavailable value")
    else:
        require(
            isinstance(actual, (int, float))
            and math.isfinite(actual)
            and math.isclose(actual, expected, rel_tol=2e-8, abs_tol=1e-8),
            f"{context}: inconsistent value ({actual!r}, expected {expected!r})",
        )


def target_key(target: str, horizon: str) -> str:
    return f"{target}_sum" if horizon == "4q" and "growth" not in target else target


def score_rows(report: dict[str, Any], prefix: str, window: str = "overall") -> dict[str, dict[str, float]]:
    return {
        row["origin_date"]: row["scores"]
        for row in report["origins"]
        if (window == "overall" or row["window"] == window) and f"{prefix}.abs_error" in row["scores"]
    }


def validate_forecast(report: dict[str, Any], name: str) -> None:
    ForecastReport.model_validate(report)
    require(content_hash(report["config"]) == report["config_hash"], f"{name}: config hash mismatch")
    origins = report["origins"]
    dates = [row["origin_date"] for row in origins]
    require(len(set(dates)) == len(dates), f"{name}: duplicate origin")
    require(sorted(dates) == sorted(report["config"]["origin_dates"]), f"{name}: origin set mismatch")
    require(report["n_excluded"] == len(report["exclusions"]), f"{name}: exclusion count mismatch")
    require(report["n_scored"] == sum(row["error"] is None for row in origins), f"{name}: scored count mismatch")
    for row in origins:
        require(all(math.isfinite(value) for value in row["scores"].values()), f"{name}: nonfinite score")
        require(not row["error"] or not row["scores"], f"{name}: failed origin has scores")
    tables = [("q1", window, table) for window, table in report["aggregates"].items()]
    tables.append(("4q", "overall", report["four_quarter"]))
    for horizon, window, table in tables:
        for target, stats in table.items():
            prefix = f"{horizon}.{target}"
            rows = list(score_rows(report, prefix, window).values())
            context = f"{name}/{window}/{prefix}"
            require(stats["n"] == len(rows), f"{context}: denominator mismatch")
            coverage = [row[f"{prefix}.covered_80"] for row in rows]
            require(all(value in (0, 1) for value in coverage), f"{context}: invalid coverage")
            require(
                stats["covered_n"] == len(rows) and stats["covered_k"] == sum(coverage), f"{context}: coverage mismatch"
            )
            require(stats["coverage"] == f"{int(sum(coverage))} of {len(rows)}", f"{context}: coverage label mismatch")
            for suffix, key in (
                ("abs_error", "mae"),
                ("pct_error", "mape"),
                ("crps", "mean_crps"),
                ("wis", "mean_wis"),
            ):
                values = [row[f"{prefix}.{suffix}"] for row in rows if f"{prefix}.{suffix}" in row]
                same_number(stats[key], mean(values) if values else None, f"{context}/{key}")


def matched_comparison(full: dict[str, Any], baseline: dict[str, Any], prefix: str, window: str) -> dict[str, Any]:
    left, right = score_rows(full, prefix, window), score_rows(baseline, prefix, window)
    dates = sorted(left.keys() & right.keys())
    out: dict[str, Any] = {"origins": dates, "n": len(dates)}
    for suffix in ("abs_error", "covered_80", "crps", "wis"):
        key = f"{prefix}.{suffix}"
        # A missing metric stays unavailable; never silently compare different subsets.
        for label, rows in (("full", left), ("baseline", right)):
            out[f"{label}_{suffix}"] = (
                mean(rows[date][key] for date in dates) if dates and all(key in rows[date] for date in dates) else None
            )
        a, b = out[f"full_{suffix}"], out[f"baseline_{suffix}"]
        out[f"delta_{suffix}"] = b - a if a is not None and b is not None else None
    return out


def validate_ablations(suite: dict[str, Any], forecasts: dict[str, dict[str, Any]]) -> None:
    """Reconcile full-precision paired records with exported rows and summaries."""
    profile_deltas: dict[str, list[float]] = {}
    for profile, bundle in suite["profiles"].items():
        reports = {report["config"]["model_variant"]: report for report in bundle["reports"]}
        require(set(reports) == {"full_model", *ABLATIONS}, f"{profile}: missing ablation variant")
        for name, report in reports.items():
            validate_forecast(report, f"ablations/{profile}/{name}")
            require(
                report["config"]["origin_dates"] == forecasts["full_model"]["config"]["origin_dates"],
                f"{profile}: incompatible origins",
            )
            for key in INPUTS:
                require(
                    report["config"][key] == forecasts["full_model"]["config"][key], f"{profile}: source hash mismatch"
                )
            if profile == "central":
                require(report == forecasts[name], "Ablation central report differs from standalone report")
        groups: dict[str, list[dict[str, Any]]] = {}
        seen: set[tuple[str, str, str]] = set()
        for row in bundle["comparisons"]:
            metric = f"{row['horizon']}.{row['target']}.{row['statistic']}"
            identity = (row["variant"], row["origin_date"], metric)
            require(identity not in seen, f"{profile}: duplicate paired score")
            seen.add(identity)
            for label, variant in (("full", "full_model"), ("ablated", row["variant"])):
                origin = next(item for item in reports[variant]["origins"] if item["origin_date"] == row["origin_date"])
                same_number(origin["scores"][metric], row[label], f"{profile}/{identity}/{label}")
                require(origin["window"] == row["window"], f"{profile}: window mismatch")
                same_number(
                    origin["scores"][f"{row['horizon']}.{row['target']}.covered_80"],
                    row[f"{label}_covered_80"],
                    f"{profile}: coverage",
                )
            same_number(row["ablated_minus_full"], row["ablated"] - row["full"], f"{profile}: paired delta")
            tie = math.isclose(row["ablated"], row["full"], rel_tol=1e-10, abs_tol=1e-9)
            winner = "tie" if tie else "full_model" if row["ablated_minus_full"] > 0 else row["variant"]
            require(row["winner"] == winner, f"{profile}: winner mismatch")
            for window in ("overall", row["window"]):
                groups.setdefault(f"{row['variant']}.{window}.{metric}", []).append(row)
        expected = {
            (name, origin["origin_date"], metric)
            for name in ABLATIONS
            for origin in reports[name]["origins"]
            for metric in origin["scores"]
            if metric.endswith((".abs_error", ".crps", ".wis"))
        }
        require(seen == expected, f"{profile}: missing paired score")
        require(groups.keys() == bundle["summary"].keys(), f"{profile}: missing summary")
        for key, rows in groups.items():
            stats = bundle["summary"][key]
            require(stats["n"] == len(rows), f"{profile}/{key}: summary denominator mismatch")
            for label, winner in (("full_wins", "full_model"), ("ablated_wins", rows[0]["variant"]), ("ties", "tie")):
                require(
                    stats[label] == sum(row["winner"] == winner for row in rows),
                    f"{profile}/{key}: winner count mismatch",
                )
            for label in ("full", "ablated"):
                count = sum(row[f"{label}_covered_80"] for row in rows)
                same_number(stats[f"{label}_covered"], count, key)
                same_number(stats[f"{label}_coverage"], count / len(rows), key)
            delta = mean(row["ablated_minus_full"] for row in rows)
            same_number(stats["mean_ablated_minus_full"], delta, key)
            profile_deltas.setdefault(key, []).append(delta)
    require(profile_deltas.keys() == suite["robustness"].keys(), "Missing robustness target")
    for key, deltas in profile_deltas.items():
        row = suite["robustness"][key]
        require(
            row
            == {
                "profiles": len(deltas),
                "ties": sum(abs(d) <= 1e-9 for d in deltas),
                "full_better": sum(d > 1e-9 for d in deltas),
                "ablated_better": sum(d < -1e-9 for d in deltas),
            },
            f"{key}: inconsistent robustness count",
        )


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def validate_portfolio(portfolio: dict[str, Any]) -> None:
    from longaeva_app.evaluation.portfolio import overlap_counts

    require(content_hash(portfolio["config"]) == portfolio["config_hash"], "Portfolio config hash mismatch")
    rows = portfolio["origins"]
    require(portfolio["n_eligible"] == len(rows), "Portfolio origin count mismatch")
    require(portfolio["n_excluded"] == len(portfolio["exclusions"]), "Portfolio exclusion count mismatch")
    for key, stats in portfolio["aggregates"].items():
        scored = [row["benchmarks"][key] for row in rows if row["benchmarks"][key]["status"] == "ok"]
        require(stats["n_scored"] == len(scored), f"{key}: benchmark denominator mismatch")
        require(stats["n_unavailable"] == len(rows) - len(scored), f"{key}: unavailable count mismatch")
        require(
            stats["n_estimated"] == sum(bool(row["estimated"]) for row in scored), f"{key}: estimated count mismatch"
        )
        same_number(
            stats["mean_return"], mean(row["metrics"]["total_return"] for row in scored) if scored else None, key
        )
        same_number(
            stats["worst_window_drawdown"],
            min(row["metrics"]["max_drawdown"] for row in scored) if scored else None,
            key,
        )
    windows = [
        (date.fromisoformat(row["entry_date"]), date.fromisoformat(row["exit_date"]))
        for row in rows
        if row.get("entry_date") and row.get("exit_date")
    ]
    require(portfolio["overlap"] == overlap_counts(windows), "Portfolio overlap mismatch")
    for key in ("visa_strategy", "visa_buy_and_hold"):
        if portfolio[key]["status"] == "not_run":
            require(
                portfolio[key]["metrics"] is None and portfolio[key]["n_scored"] == 0,
                f"{key}: unavailable metrics must stay null",
            )


def table(headers: Iterable[str], rows: Iterable[Iterable[object]]) -> str:
    columns = list(headers)
    return "\n".join(
        [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
            *("| " + " | ".join(cell(value) for value in row) + " |" for row in rows),
        ]
    )


def number(value: float | None, scale: float = 1.0) -> str:
    return "Unavailable" if value is None else f"{value * scale:,.3f}"


def scale_for(target: str) -> float:
    return 100.0 if "growth" in target else 1.0


class Evidence:
    """Only package-local, named inputs; preserve original bytes and hashes."""

    def __init__(self, root: Path):
        self.root = root
        self.sources: dict[str, tuple[str, str]] = {}

    def read(self, filename: str) -> bytes:
        raw = (self.root / filename).read_bytes()
        self.sources[filename] = (sha256_hex(raw), "—")
        return raw

    def json(self, filename: str) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.read(filename))
        require(isinstance(data, dict), f"{filename}: expected object")
        digest = data.get("config_hash", data.get("content_hash", "—"))
        self.sources[filename] = (self.sources[filename][0], digest)
        if "content_hash" in data:
            require(
                content_hash({k: v for k, v in data.items() if k != "content_hash"}) == data["content_hash"],
                f"{filename}: content hash mismatch",
            )
        return data


def forecast_sections(forecasts: dict[str, dict[str, Any]]) -> list[str]:
    parts = [
        "## Forecast scores",
        "Levels and their CRPS/WIS are USD millions; driver errors and scores are percentage points. "
        "MAPE is percent. Coverage is the saved central 80% interval. `Unavailable` is not zero. "
        "Source: each `data/evaluation/visa_<variant>.json`, `aggregates.<window>.<target>` "
        "or `four_quarter.<target>`. Configurations and file hashes are in the source ledger.",
        "Four-quarter level targets are sums; four-quarter driver targets are the fourth quarter's YoY growth. "
        "The model's driver path units are annualized QoQ before the evaluation transform. "
        "WIS uses the repository weighting documented in the [model specification](model-spec.md).",
        "### Cached LLM baseline",
        f"Provider `{forecasts['llm_baseline']['config']['baseline']['provider']}`, "
        f"model `{forecasts['llm_baseline']['config']['baseline']['model']}`, "
        f"prompt `{forecasts['llm_baseline']['config']['baseline']['prompt_version']}`. "
        "Source: `visa_llm_baseline.json`, `config.baseline` and `n_scored`. "
        + forecasts["llm_baseline"]["config"]["baseline"]["limitation"],
        table(["Capture status", "Count"], forecasts["llm_baseline"]["config"]["baseline"]["capture_counts"].items()),
    ]
    for horizon, windows in (("q1", ("overall", "primary", "extension")), ("4q", ("overall",))):
        for window in windows:
            parts.append(f"### {'Next quarter' if horizon == 'q1' else 'Four quarters (separate horizon)'} — {window}")
            rows = []
            for target, label in TARGETS.items():
                for variant, report in forecasts.items():
                    stats = (
                        report["aggregates"][window][target]
                        if horizon == "q1"
                        else report["four_quarter"][target_key(target, horizon)]
                    )
                    scale = scale_for(target)
                    rows.append(
                        [
                            label,
                            variant,
                            stats["n"],
                            number(stats["mae"], scale),
                            number(stats["mape"], 100),
                            stats["coverage"],
                            number(stats["mean_crps"], scale),
                            number(stats["mean_wis"], scale),
                        ]
                    )
            parts.append(table(["Target", "Variant", "n", "MAE", "MAPE %", "Covered / n", "CRPS", "WIS"], rows))
    parts.extend(
        [
            "## Matched-origin baseline comparisons",
            "Positive delta = baseline error minus full-model error: positive favors the full model. "
            "Each row uses the intersection of origins with a scored target, independently for its horizon/window. "
            "No superiority claim is inferred from unmatched aggregate tables. Coverage is shown as percent on "
            "the same n. Source: both variants' `origins[origin_date].scores.<horizon>.<target>.*`; "
            "the exact date intersections appear below each table.",
        ]
    )
    for horizon, windows in (("q1", ("overall", "primary", "extension")), ("4q", ("overall",))):
        for window in windows:
            parts.append(f"### Matched {horizon} — {window}")
            rows, intersections = [], []
            for variant in BASELINES:
                for target, label in TARGETS.items():
                    key = target_key(target, horizon)
                    result = matched_comparison(forecasts["full_model"], forecasts[variant], f"{horizon}.{key}", window)
                    scale = scale_for(target)
                    rows.append(
                        [
                            variant,
                            label,
                            result["n"],
                            number(result["full_abs_error"], scale),
                            number(result["baseline_abs_error"], scale),
                            number(result["delta_abs_error"], scale),
                            number(result["delta_crps"], scale),
                            number(result["delta_wis"], scale),
                            number(result["full_covered_80"], 100),
                            number(result["baseline_covered_80"], 100),
                        ]
                    )
                    intersections.append(f"- `{variant}/{key}`: " + (", ".join(result["origins"]) or "none"))
            parts.append(
                table(
                    [
                        "Baseline",
                        "Target",
                        "n",
                        "Full MAE",
                        "Baseline MAE",
                        "Δ MAE",
                        "Δ CRPS",
                        "Δ WIS",
                        "Full coverage %",
                        "Baseline coverage %",
                    ],
                    rows,
                )
            )
            parts.append("\n".join(intersections))
    return parts


def failure_section(
    full: dict[str, Any],
    forecasts: dict[str, dict[str, Any]],
    inventory: list[dict[str, str]],
    observations: list[dict[str, str]],
) -> list[str]:
    rows = score_rows(full, "q1.net_revenue")
    worst = sorted(rows, key=lambda date: (-rows[date]["q1.net_revenue.abs_error"], date))[0]
    origin = next(row for row in inventory if row["cutoff_utc"][:10] == worst)
    target = f"FY{origin['target_fiscal_year']}Q{origin['target_fiscal_quarter']}"
    actuals = [
        row
        for row in observations
        if row["period_label"] == target
        and row["field"] == "net_revenue"
        and row["source_id"].startswith(origin["target_release_accession"] + "/")
        and row["vintage_role"] in ("", "current")
    ]
    require(len(actuals) == 1, "Failure case: missing or ambiguous first-print actual")
    actual = actuals[0]
    median = rows[worst]["q1.net_revenue.median"]
    same_number(
        abs(median - float(actual["value"])),
        rows[worst]["q1.net_revenue.abs_error"],
        "Failure-case actual reconciliation",
    )
    comparison = []
    for variant in ("full_model", *BASELINES):
        scores = score_rows(forecasts[variant], "q1.net_revenue").get(worst, {})
        comparison.append(
            [
                variant,
                number(scores.get("q1.net_revenue.median")),
                number(scores.get("q1.net_revenue.abs_error")),
                number(scores.get("q1.net_revenue.pct_error"), 100),
                "Unavailable"
                if "q1.net_revenue.covered_80" not in scores
                else ("Yes" if scores["q1.net_revenue.covered_80"] else "No"),
                number(scores.get("q1.net_revenue.wis")),
            ]
        )
    return [
        "## Failure case — largest next-quarter revenue error",
        f"Selection rule: maximum full-model `q1.net_revenue.abs_error`, earliest origin breaking ties. "
        f"Selected origin **{worst}**, target **{target}**. First-print GAAP revenue was "
        f"**{number(float(actual['value']))} USD million**. Source: `data/fixtures/visa_releases/observations.csv`, "
        f"period `{target}`, field `net_revenue`, source `{actual['source_id']}`, location `{actual['location']}`. "
        f"The target release was accepted at `{origin['target_release_accepted_utc']}`. "
        "Forecast and error cells below come from each variant's saved origin score keys, not a new simulation.",
        table(
            ["Variant", "Median (USD m)", "Absolute error (USD m)", "Error %", "Inside 80% interval", "WIS (USD m)"],
            comparison,
        ),
    ]


def generate(root: Path = PACKAGE_ROOT) -> str:
    evidence = Evidence(root)
    inputs = {key: sha256_hex(evidence.read(path)) for key, path in INPUTS.items()}
    inventory = list(csv.DictReader((root / INPUTS["origins_hash"]).read_text().splitlines()))
    observations = list(csv.DictReader((root / INPUTS["observations_hash"]).read_text().splitlines()))
    forecasts = {variant: evidence.json(f"data/evaluation/visa_{variant}.json") for variant in VARIANTS}
    full = forecasts["full_model"]
    historical = {row["cutoff_utc"][:10] for row in inventory if row["status"] == "candidate"}
    prospective_dates = {row["cutoff_utc"][:10] for row in inventory if row["status"] == "prospective"}
    for variant, report in forecasts.items():
        validate_forecast(report, variant)
        for key, digest in inputs.items():
            require(report["config"][key] == digest, f"{variant}: source hash mismatch: {key}")
        dates = set(report["config"]["origin_dates"])
        require(not (dates & prospective_dates), f"{variant}: prospective origin in historical scores")
        require(dates == set(full["config"]["origin_dates"]), f"{variant}: incompatible origin set")
        require(
            report["config"]["scoring_bases"] == full["config"]["scoring_bases"],
            f"{variant}: incompatible scoring bases",
        )
        for key in ("coverage_level", "quantiles", "wis"):
            require(report["config"][key] == full["config"][key], f"{variant}: incompatible scoring setting: {key}")
        require(
            dates | {row["origin_date"] for row in report["exclusions"]} == historical,
            f"{variant}: incomplete historical inventory",
        )

    exclusions = {row["origin_date"]: row["reason"] for row in full["exclusions"]}
    parts = [
        "## Retained evidence and origin inventory",
        f"The full model scores **{full['n_scored']} historical origins**, with **{full['n_excluded']} exclusions**. "
        "This is an origin count, not a count of independent targets or Monte Carlo paths. "
        "Source: `visa_full_model.json` (`n_scored`, `n_excluded`, `origins`, `exclusions`) "
        "and `data/fixtures/origins.csv`. Prospective origins remain separate and unscored.",
        table(
            ["Origin / cutoff UTC", "Window", "Origin quarter", "Target quarter", "Disposition"],
            (
                [
                    row["cutoff_utc"],
                    row["origin_window"],
                    f"FY{row['fiscal_year']}Q{row['fiscal_quarter']}",
                    f"FY{row['target_fiscal_year']}Q{row['target_fiscal_quarter']}",
                    "Prospective — not scored"
                    if row["status"] == "prospective"
                    else exclusions.get(row["cutoff_utc"][:10], "Scored"),
                ]
                for row in inventory
                if row["status"] in ("candidate", "prospective")
            ),
        ),
        "### Missing targets and origin errors",
        table(
            ["Variant", "Origin", "Target / status", "Reason"],
            (
                [variant, row["origin_date"], target, reason]
                for variant, report in forecasts.items()
                for row in report["origins"]
                for target, reason in ({"origin": row["error"]} if row["error"] else row["skipped_drivers"]).items()
            ),
        ),
        *forecast_sections(forecasts),
    ]

    ablation = evidence.json("data/evaluation/visa_ablation_persistence.json")
    validate_ablations(ablation, forecasts)
    parts.extend(
        [
            "## Ablations and persistence",
            ablation["profile_policy"] + ". " + ablation["delta_convention"],
            "Source: `visa_ablation_persistence.json`, `profiles.central.summary` and `robustness`, "
            "keys `<variant>.overall.<horizon>.<target>.<score>`. Profile direction counts are sensitivity cases, "
            "not additional independent forecasts. Detailed per-origin and per-window comparisons remain in the "
            "[ablation persistence document](../data/evaluation/ablation_persistence.md).",
        ]
    )
    ablation_rows = []
    for variant in ABLATIONS:
        for horizon in ("q1", "4q"):
            for target, label in TARGETS.items():
                key = f"{variant}.overall.{horizon}.{target_key(target, horizon)}.abs_error"
                stats, robustness = ablation["profiles"]["central"]["summary"][key], ablation["robustness"][key]
                require(
                    stats["full_wins"] + stats["ablated_wins"] + stats["ties"] == stats["n"], f"{key}: wins mismatch"
                )
                require(
                    sum(robustness[k] for k in ("full_better", "ablated_better", "ties"))
                    == robustness["profiles"]
                    == len(ablation["profiles"]),
                    f"{key}: profile count mismatch",
                )
                ablation_rows.append(
                    [
                        variant,
                        horizon,
                        label,
                        stats["n"],
                        f"{stats['full_wins']}/{stats['ablated_wins']}/{stats['ties']}",
                        number(stats["mean_ablated_minus_full"], scale_for(target)),
                        f"{stats['full_covered']}/{stats['n']}",
                        f"{stats['ablated_covered']}/{stats['n']}",
                        f"{robustness['full_better']}/{robustness['ablated_better']}/{robustness['ties']}",
                    ]
                )
    parts.append(
        table(
            [
                "Ablation",
                "Horizon",
                "Target",
                "n",
                "Full / ablated wins / ties",
                "Δ MAE",
                "Full coverage",
                "Ablated coverage",
                "Profiles favor full / ablated / tied",
            ],
            ablation_rows,
        )
    )

    extraction = evidence.json("data/evaluation/extraction.json")
    parts.extend(
        [
            "## Extraction errors",
            f"Provider `{extraction['provider']}`, model `{extraction['model']}`, prompt `{extraction['prompt_version']}`. "
            "Source: `extraction.json`, `coverage`, `errors`, `review`, `failures`. These are extraction labels, not forecast origins.",
            table(["Coverage field", "Count"], extraction["coverage"].items()),
        ]
    )
    for name, rate in extraction["errors"].items():
        same_number(
            rate["rate"], rate["errors"] / rate["denominator"] if rate["denominator"] else None, f"extraction/{name}"
        )
    parts.append(
        table(
            ["Error category", "Errors", "Denominator", "Rate %"],
            (
                [name, rate["errors"], rate["denominator"], number(rate["rate"], 100)]
                for name, rate in extraction["errors"].items()
            ),
        )
    )
    parts.append(
        f"Review status: **{extraction['review']['status']}**; reviewed labels: **{extraction['review']['reviewed_labels']}**. "
        + " ".join(extraction["limitations"])
    )
    parts.append(
        table(
            ["Failed passage", "Status", "Reason"],
            ([row["passage_id"], row["status"], row.get("error") or "—"] for row in extraction["failures"]),
        )
    )
    parts.append(
        "Detailed labels and category/family tables: [extraction error sample](../data/evaluation/extraction.md). "
        "Labeling and denominator policy: [extraction evaluation guide](extraction-eval.md)."
    )

    portfolio = evidence.json("data/evaluation/visa_portfolio.json")
    validate_portfolio(portfolio)
    benchmark_manifest = evidence.read("data/manifest/benchmarks.yaml")
    require(
        content_hash(yaml.safe_load(benchmark_manifest)) == portfolio["config"]["manifest_hash"],
        "Benchmark manifest hash mismatch",
    )
    require(yaml.safe_load(benchmark_manifest)["labels"] == portfolio["labels"], "Benchmark label mismatch")
    require(
        portfolio["config"]["origin_inventory_hash"] == inputs["origins_hash"], "Benchmark origin inventory mismatch"
    )
    parts.extend(
        [
            "## Benchmarks and portfolio availability",
            "Source: `visa_portfolio.json`, `labels`, `aggregates`, `overlap`, `visa_strategy`, `visa_buy_and_hold`. "
            "Window returns overlap; their mean is not a stitched portfolio return or an alpha estimate.",
            portfolio["labels"]["primary"],
            portfolio["labels"]["primary_footnote"],
            portfolio["labels"]["secondary"],
            portfolio["labels"]["visa"],
            table(
                [
                    "Benchmark key",
                    "Scored n",
                    "Estimated n",
                    "Unavailable n",
                    "Mean window return %",
                    "Worst window drawdown %",
                ],
                (
                    [
                        name,
                        row["n_scored"],
                        row["n_estimated"],
                        row["n_unavailable"],
                        number(row["mean_return"], 100),
                        number(row["worst_window_drawdown"], 100),
                    ]
                    for name, row in portfolio["aggregates"].items()
                ),
            ),
            f"Overlapping pairs: {portfolio['overlap']['overlapping_pairs']}; windows with overlap: {portfolio['overlap']['windows_with_overlap']}.",
            table(
                ["Comparison", "Status", "Scored n", "Reason"],
                (
                    [
                        key,
                        portfolio[key]["status"],
                        portfolio[key].get("n_scored", 0),
                        re.sub(r"; LON-\d+ gate remains blocked\.?", "", portfolio[key]["reason"]),
                    ]
                    for key in ("visa_strategy", "visa_buy_and_hold")
                ),
            ),
            *failure_section(full, forecasts, inventory, observations),
        ]
    )
    from longaeva_app.runs.prospective import load_registration

    filename = "data/demo/forecasts/prospective_fy2026q4.json"
    evidence.read(filename)
    evidence.read("data/demo/forecasts/prospective_fy2026q4.paths.npz")
    registration = load_registration(root / filename)
    parts.extend(
        [
            "## Frozen prospective registration",
            f"Target **{registration.target}**; evidence cutoff `{registration.cutoff_ts.isoformat()}`; "
            f"actual registration `{registration.registered_at.isoformat()}`; run `{registration.run['id']}`; "
            f"content hash `{registration.content_hash}`. **Not yet scored.** "
            "Registration occurred after the fiscal quarter ended, using the July evidence cutoff before results publication. "
            "It is not a July registration or a pre-quarter forecast. No prospective row enters the tables above. "
            "The preserved procedure below describes later scoring without changing this artifact.",
            "## Source ledger",
            "All paths are relative to the standalone package. SHA-256 identifies exact input bytes. "
            "Configuration/content hashes identify retained runs or suites; they are not replaced with current code hashes. "
            "Forecast JSONs export persisted evaluation rows rounded to ten significant digits. Generation validates "
            "counts, coverage and exported score means with rounding tolerance; it does not reconstruct missing path "
            "distributions or claim to replay old executions. Source files remain unchanged.",
            table(
                ["File", "SHA-256", "Configuration / content hash"],
                (
                    [f"`{name}`", f"`{digest}`", f"`{config}`"]
                    for name, (digest, config) in sorted(evidence.sources.items())
                ),
            ),
            "### Retained code fingerprints",
            table(
                ["Variant", "Engine version", "Evaluation code hash"],
                (
                    [name, report["config"]["code_version"], f"`{report['config']['evaluation_code_hash']}`"]
                    for name, report in forecasts.items()
                ),
            ),
        ]
    )
    return "\n\n".join(parts) + "\n"


def render_document(original: str, generated: str) -> str:
    require(original.count(BEGIN) == 1 and original.count(END) == 1, "Report requires exactly one generated section")
    before, tail = original.split(BEGIN)
    _, after = tail.split(END)
    return before + BEGIN + "\n\n" + generated.rstrip() + "\n\n" + END + after


def update_report(root: Path = PACKAGE_ROOT, *, check: bool = False) -> bool:
    path = root / "docs/evaluation-report.md"
    original = path.read_text(encoding="utf-8")
    rendered = render_document(original, generate(root))
    if check:
        return rendered == original
    if rendered != original:
        path.write_text(rendered, encoding="utf-8")
    return True
