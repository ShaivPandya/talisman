"""LON-28 independent-window arithmetic and aggregate-only report contract."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from longaeva_app import cli
from longaeva_app.collect import benchmarks
from longaeva_app.collect.benchmark_sources import load_manifest
from longaeva_app.collect.benchmarks import ShillerData
from longaeva_app.evaluation.portfolio import (
    Dividend,
    Signal,
    format_portfolio_table,
    overlap_counts,
    return_metrics,
    run_portfolio_evaluation,
    score_synthetic_window,
    select_window,
    write_portfolio_report,
)
from longaeva_app.valuation.actions import CONFIG_PATH, load_decision_rule


def weekdays(first: date, last: date) -> list[date]:
    return [
        first + timedelta(days=i) for i in range((last - first).days + 1) if (first + timedelta(days=i)).weekday() < 5
    ]


def french_zip(rows: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("daily.csv", ",Mkt-RF,SMB,HML,RF\n" + rows + "\n")
    return stream.getvalue()


CUTOFF = datetime(2024, 1, 5, 22, tzinfo=UTC)
DAYS = weekdays(date(2024, 1, 1), date(2024, 6, 30))
NOW = datetime(2026, 10, 6, 17, tzinfo=UTC)


def score(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "sessions": DAYS,
        "prices": dict.fromkeys(DAYS, 100.0),
        "cutoff": CUTOFF,
        "signal": Signal(100, 100, CUTOFF, CUTOFF),
        "dividends": [],
        "dividends_complete": True,
        "benchmark_returns": {"market": [0.0] * 63},
        "rule": load_decision_rule(),
        "capital": 100_000,
    }
    args.update(overrides)
    return score_synthetic_window(**args)


@pytest.mark.parametrize(
    ("value", "action", "weight"), [(100, "hold", 0.8), (120, "add", 1), (80, "trim", 0.6), (70, "exit", 0)]
)
def test_all_actions_funded_round_trip(value: float, action: str, weight: float) -> None:
    result = score(signal=Signal(value, 100, CUTOFF, CUTOFF))
    strategy = result["strategy"]
    assert result["action"] == action
    assert strategy["target_weight"] == pytest.approx(weight)
    notional = 100_000 * weight / 1.0009
    assert strategy["entry_cost"] == pytest.approx(notional * 0.0009)
    assert strategy["exit_cost"] == pytest.approx(notional * 0.0009)
    assert strategy["total_return"] == pytest.approx(-2 * notional * 0.0009 / 100_000)
    assert strategy["initial_cash_after_costs"] >= 0
    assert 0 <= strategy["average_invested_exposure"] <= 1
    assert strategy["funding_cost"] == 0
    assert result["visa_buy_and_hold"]["total_return"] == pytest.approx(-2 * 0.0009 / 1.0009)
    assert result["excess_vs_benchmarks"]["market"] == strategy["total_return"]
    assert strategy["entry_cost"] + strategy["exit_cost"] == pytest.approx(
        sum(strategy[key] for key in ("transaction_cost", "slippage_cost", "market_impact_cost"))
    )


def test_entry_next_session_and_63_intervals() -> None:
    window = select_window(DAYS, CUTOFF, 63)
    assert window[0] == date(2024, 1, 8)  # Friday cutoff -> Monday close.
    assert len(window) == 64
    assert DAYS.index(window[-1]) - DAYS.index(window[0]) == 63
    with pytest.raises(ValueError, match="insufficient"):
        select_window(DAYS[:40], CUTOFF, 63)
    with pytest.raises(ValueError, match="cover cutoff"):
        select_window(DAYS[20:], CUTOFF, 63)
    with pytest.raises(ValueError, match="unique ordered"):
        select_window(DAYS[::-1], CUTOFF, 63)


def test_dividend_entitlement_paid_and_receivable_no_double_count() -> None:
    days = select_window(DAYS, CUTOFF, 63)
    dividends = [
        Dividend(days[0], days[2], 100),  # Bought at ex-date close: not entitled.
        Dividend(days[5], days[10], 1),
        Dividend(days[-1], days[-1] + timedelta(days=20), 2),  # Held entering ex-date.
    ]
    result = score(dividends=dividends)["strategy"]
    shares = (80_000 / 1.0009) / 100
    assert result["dividends_paid"] == pytest.approx(shares)
    assert result["dividends_receivable"] == pytest.approx(2 * shares)
    assert result["total_return"] == pytest.approx(score()["strategy"]["total_return"] + 3 * shares / 100_000)
    with pytest.raises(ValueError, match="coverage"):
        score(dividends_complete=False)
    with pytest.raises(ValueError, match="duplicate"):
        score(dividends=[dividends[1], dividends[1]])


def test_drawdown_and_exposure_include_cash_and_terminal_costs() -> None:
    prices = dict.fromkeys(DAYS, 100.0)
    days = select_window(DAYS, CUTOFF, 63)
    prices[days[1]], prices[days[2]] = 120, 90
    result = score(prices=prices)["strategy"]
    shares = 80_000 / 1.0009 / 100
    peak = 20_000 + shares * 120
    trough = 20_000 + shares * 90
    assert result["max_drawdown"] == pytest.approx(trough / peak - 1)
    assert 0.7 < result["average_invested_exposure"] < 0.9
    assert return_metrics([0.1, -0.2, 0.1]) == pytest.approx({"total_return": -0.032, "max_drawdown": -0.2})


def test_late_signals_bad_prices_missing_benchmark_and_changed_rule_refused() -> None:
    with pytest.raises(ValueError, match="after cutoff"):
        score(signal=Signal(100, 100, CUTOFF, CUTOFF + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="after cutoff"):
        score(signal=Signal(100, 100, CUTOFF + timedelta(seconds=1), CUTOFF))
    with pytest.raises(ValueError, match="timezone"):
        score(signal=Signal(100, 100, CUTOFF.replace(tzinfo=None), CUTOFF))
    with pytest.raises(ValueError, match="coverage"):
        score(prices={})
    with pytest.raises(ValueError, match="coverage"):
        score(benchmark_returns={"market": [0.0] * 62})
    with pytest.raises(ValueError, match="frozen"):
        score(rule=replace(load_decision_rule(), add_fraction=0.5))


def test_overlap_counts_independent_windows() -> None:
    assert overlap_counts(
        [
            (date(2024, 1, 1), date(2024, 4, 1)),
            (date(2024, 3, 1), date(2024, 6, 1)),
            (date(2024, 6, 1), date(2024, 7, 1)),
        ]
    ) == {"overlapping_pairs": 1, "windows_with_overlap": 2}


def synthetic_fetch(monkeypatch: pytest.MonkeyPatch) -> Any:
    days = weekdays(date(2023, 12, 1), date(2024, 12, 31))
    fred = ("DATE,SP500\n" + "\n".join(f"{d},137.12345" for d in days)).encode()
    french = french_zip("\n".join(f"{d:%Y%m%d},0.1,0,0,0.01" for d in days))
    monkeypatch.setattr(benchmarks, "read_shiller", lambda body: ShillerData(dividends={"2024-01": 12}))
    manifest = load_manifest()
    bodies = dict(
        zip(
            (manifest["sources"][k]["url"] for k in ("fred_sp500", "shiller_ie_data", "ken_french_daily")),
            (fred, b"private raw workbook", french),
            strict=True,
        )
    )
    return lambda url: (bodies[url], {})


def test_report_contract_selection_counts_and_no_raw_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fetch = synthetic_fetch(monkeypatch)
    report = run_portfolio_evaluation(origin_dates=["2024-07-23", "2022-07-26", "2026-07-28"], fetch=fetch, now=NOW)
    assert report["n_eligible"] == 1
    assert report["n_excluded"] == 2
    assert report["aggregates"]["sp500_tr_approx"]["n_scored"] == 1
    assert report["aggregates"]["sp500_tr_approx"]["n_estimated"] == 1
    assert report["aggregates"]["us_total_market_tr"]["n_scored"] == 1
    row = report["origins"][0]
    assert row["benchmarks"]["us_total_market_tr"]["metrics"]["total_return"] == pytest.approx(1.0011**63 - 1)
    for where in (report, row):
        for key in ("visa_strategy", "visa_buy_and_hold"):
            assert where[key]["status"] == "not_run"
            assert where[key]["metrics"] is None
    assert row["excess_vs_visa"] is None
    assert row["excess_vs_benchmarks"] is None
    assert report["labels"] == load_manifest()["labels"]
    assert report["sec_dividends"]["scoring_ready"] is False
    assert report["drift_diagnostic"]["status"] == "unavailable"
    path = tmp_path / "report.json"
    write_portfolio_report(report, path)
    text = path.read_text()
    assert "137.12345" not in text and "private raw workbook" not in text
    assert '"daily_returns"' not in text and '"prices"' not in text
    assert json.loads(text)["suite_version"] == "lon28-v1"
    assert "not run" in format_portfolio_table(report)
    assert (
        report["config_hash"]
        == run_portfolio_evaluation(origin_dates=["2024-07-23", "2022-07-26", "2026-07-28"], fetch=fetch, now=NOW)[
            "config_hash"
        ]
    )


def test_fetch_failure_and_rule_freeze_precede_network(tmp_path: Path) -> None:
    calls: list[str] = []

    def fail(url: str) -> tuple[bytes, dict[str, str]]:
        calls.append(url)
        raise OSError("offline")

    rule_path = tmp_path / "rule.yaml"
    rule_path.write_text(CONFIG_PATH.read_text().replace("add_at_or_above: 0.15", "add_at_or_above: 0.16"))
    with pytest.raises(ValueError, match="frozen"):
        run_portfolio_evaluation(rule_path=rule_path, fetch=fail, now=NOW)
    assert not calls
    report = run_portfolio_evaluation(origin_dates=["2024-07-23"], fetch=fail, now=NOW)
    assert len(calls) == 3
    assert report["aggregates"]["sp500_tr_approx"]["n_scored"] == 0
    assert report["aggregates"]["sp500_tr_approx"]["mean_return"] is None
    assert report["origins"][0]["benchmarks"]["sp500_tr_approx"]["status"] == "unavailable"


def test_cli_json_and_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from longaeva_app.evaluation import portfolio

    fetch = synthetic_fetch(monkeypatch)
    monkeypatch.setattr(
        portfolio, "run_portfolio_evaluation", lambda **kwargs: run_portfolio_evaluation(**kwargs, fetch=fetch, now=NOW)
    )
    output = tmp_path / "results.json"
    assert cli.main(["evaluate-portfolio", "--origin", "2024-07-23", "--json", "--output", str(output)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == json.loads(output.read_text())
    assert printed["n_eligible"] == 1
