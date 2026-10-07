"""Evidence integrity, denominator safety and offline reproduction for LON-33."""

from __future__ import annotations

import copy
import json
import shutil
import socket
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import Engine

from longaeva_app.cli import build_parser, cmd_evaluation_report
from longaeva_app.evaluation import report
from longaeva_app.hashing import content_hash


def saved(variant: str = "full_model") -> dict[str, Any]:
    return dict(json.loads((report.PACKAGE_ROOT / f"data/evaluation/visa_{variant}.json").read_text()))


@pytest.fixture()
def bundle(tmp_path: Path) -> Path:
    names = [
        *report.INPUTS.values(),
        "data/manifest/benchmarks.yaml",
        *(f"data/evaluation/visa_{variant}.json" for variant in report.VARIANTS),
        "data/evaluation/visa_ablation_persistence.json",
        "data/evaluation/extraction.json",
        "data/evaluation/visa_portfolio.json",
        "data/demo/forecasts/prospective_fy2026q4.json",
        "data/demo/forecasts/prospective_fy2026q4.paths.npz",
        "docs/evaluation-report.md",
    ]
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(report.PACKAGE_ROOT / name, target)
    return tmp_path


def test_bundled_report_repeats_offline_and_preserves_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Report generation must not connect or construct providers")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr("longaeva_app.extract.providers.build_provider", forbidden)
    inputs = [*report.PACKAGE_ROOT.glob("data/evaluation/*.json"), *report.PACKAGE_ROOT.glob("data/demo/forecasts/*")]
    before = {path: path.read_bytes() for path in inputs}
    first = report.generate()
    assert report.generate() == first
    assert report.update_report(check=True)
    assert {path: path.read_bytes() for path in inputs} == before
    assert "2024-10-29" in first and "9,510.000" in first
    assert "Not yet scored" in first
    portfolio = json.loads((report.PACKAGE_ROOT / "data/evaluation/visa_portfolio.json").read_text())
    assert portfolio["labels"]["primary"] in first
    assert portfolio["labels"]["secondary"] in first
    assert "Unavailable" in first


def test_check_detects_drift_without_writing_and_refresh_preserves_authored_text(bundle: Path) -> None:
    path = bundle / "docs/evaluation-report.md"
    original = path.read_text()
    changed = original.replace("## Forecast scores", "## Stale scores") + "\nAuthored note.\n"
    path.write_text(changed)
    assert not report.update_report(bundle, check=True)
    assert path.read_text() == changed
    assert report.update_report(bundle)
    assert path.read_text() == original + "\nAuthored note.\n"
    assert report.update_report(bundle, check=True)


@pytest.mark.parametrize("original", ["no markers", report.END + report.BEGIN, report.BEGIN * 2 + report.END])
def test_invalid_section_markers_refuse_replacement(original: str) -> None:
    with pytest.raises(ValueError):
        report.render_document(original, "new")


def test_missing_or_changed_source_refuses_generation(bundle: Path) -> None:
    source = bundle / report.INPUTS["observations_hash"]
    source.write_text(source.read_text() + "\n")
    with pytest.raises(ValueError, match="source hash mismatch"):
        report.generate(bundle)
    source.unlink()
    with pytest.raises(OSError):
        report.generate(bundle)


def test_broken_json_and_content_hash(bundle: Path) -> None:
    path = bundle / "data/evaluation/extraction.json"
    data = json.loads(path.read_text())
    data["coverage"]["total_labels"] += 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="content hash mismatch"):
        report.generate(bundle)
    path.write_text("not JSON")
    with pytest.raises(ValueError):
        report.generate(bundle)


def test_config_and_aggregate_validation() -> None:
    original = saved()
    bad = copy.deepcopy(original)
    bad["config"]["n_paths"] += 1
    with pytest.raises(ValueError, match="config hash mismatch"):
        report.validate_forecast(bad, "full_model")
    for field, value in (("n", 0), ("covered_k", 0), ("mae", 0.0), ("mean_wis", None)):
        bad = copy.deepcopy(original)
        bad["four_quarter"]["net_revenue_sum"][field] = value
        with pytest.raises(ValueError):
            report.validate_forecast(bad, "full_model")


def test_matched_denominators_and_absent_metrics() -> None:
    full, seasonal, llm = saved(), saved("seasonal_trend"), saved("llm_baseline")
    result = report.matched_comparison(full, seasonal, "q1.net_revenue", "overall")
    assert result["n"] == 14
    assert "2022-01-27" not in result["origins"]
    assert "2022-04-26" not in result["origins"]
    assert result["full_abs_error"] != full["aggregates"]["overall"]["net_revenue"]["mae"]
    quantiles = report.matched_comparison(full, llm, "q1.net_revenue", "primary")
    assert quantiles["n"] == 10
    assert quantiles["baseline_crps"] is quantiles["delta_crps"] is None
    four_quarters = report.matched_comparison(full, llm, "4q.net_revenue_sum", "overall")
    assert four_quarters["n"] == 0
    assert four_quarters["full_abs_error"] is four_quarters["baseline_abs_error"] is None


def test_prospective_cannot_become_historical(bundle: Path) -> None:
    path = bundle / "data/evaluation/visa_full_model.json"
    data = json.loads(path.read_text())
    data["config"]["origin_dates"][0] = "2026-07-28"
    data["origins"][0]["origin_date"] = "2026-07-28"
    data["config_hash"] = content_hash(data["config"])
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="prospective origin"):
        report.generate(bundle)


def test_ablation_summary_must_match_retained_pair_records() -> None:
    suite = json.loads((report.PACKAGE_ROOT / "data/evaluation/visa_ablation_persistence.json").read_text())
    key = next(iter(suite["profiles"]["central"]["summary"]))
    suite["profiles"]["central"]["summary"][key]["mean_ablated_minus_full"] += 1
    with pytest.raises(ValueError, match="inconsistent value"):
        report.validate_ablations(suite, {name: saved(name) for name in report.VARIANTS})


def test_cli_reports_validation_and_staleness(monkeypatch: pytest.MonkeyPatch) -> None:
    args = build_parser().parse_args(["evaluation-report", "--check"])
    monkeypatch.setattr(report, "update_report", lambda **kwargs: False)
    assert cmd_evaluation_report(args) == 1

    def invalid(**kwargs: Any) -> bool:
        raise ValueError("bad source")

    monkeypatch.setattr(report, "update_report", invalid)
    assert cmd_evaluation_report(args) == 1


def test_benchmark_means_and_unavailable_values() -> None:
    portfolio = json.loads((report.PACKAGE_ROOT / "data/evaluation/visa_portfolio.json").read_text())
    report.validate_portfolio(portfolio)
    broken = copy.deepcopy(portfolio)
    broken["aggregates"]["sp500_tr_approx"]["mean_return"] = 0
    with pytest.raises(ValueError, match="inconsistent value"):
        report.validate_portfolio(broken)
    portfolio["visa_strategy"]["metrics"] = {"total_return": 0}
    with pytest.raises(ValueError, match="must stay null"):
        report.validate_portfolio(portfolio)
