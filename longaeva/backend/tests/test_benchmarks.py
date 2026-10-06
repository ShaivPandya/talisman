"""Numeric source readers and benchmark arithmetic; all payloads are synthetic."""

from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta
from typing import Any

import pytest
import xlrd

from longaeva_app.collect.benchmarks import (
    BenchmarkInputs,
    ShillerData,
    fetch_inputs,
    read_fred,
    read_french,
    read_shiller,
)
from longaeva_app.evaluation.portfolio import drift_diagnostic, primary_returns, return_metrics


def french_zip(rows: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("daily.csv", "Research preamble\n,Mkt-RF,SMB,HML,RF\n" + rows + "\nCopyright\n")
    return stream.getvalue()


def weekdays(first: date, last: date) -> list[date]:
    return [
        first + timedelta(days=i) for i in range((last - first).days + 1) if (first + timedelta(days=i)).weekday() < 5
    ]


def test_numeric_fred() -> None:
    result = read_fred(b"DATE,SP500\n2024-01-01,.\n2024-01-02,130\n2024-01-03,131\n")
    assert result[date(2024, 1, 1)] is None
    assert result[date(2024, 1, 3)] == 131
    for payload in (
        b"DATE,X\n2024-01-01,1\n",
        b"DATE,SP500\n2024-01-01,nan\n",
        b"DATE,SP500\n2024-01-01,1\n2024-01-01,2\n",
    ):
        with pytest.raises(ValueError):
            read_fred(payload)


def test_french_percentage_conversion_and_missing_rf() -> None:
    values = read_french(french_zip("20240102,1.20,0,0,0.01\n20240103,-2,0,0,-99.99\n20240104,-999,0,0,0.01\n"))
    assert values[date(2024, 1, 2)] == pytest.approx(0.0121)
    assert values[date(2024, 1, 3)] is None
    assert values[date(2024, 1, 4)] is None
    with pytest.raises(ValueError, match="duplicate"):
        read_french(french_zip("20240102,1,0,0,0\n20240102,1,0,0,0\n"))


class FakeSheet:
    def __init__(self) -> None:
        self.rows: list[list[Any]] = [
            ["", "", "", "", "", "Real"],
            ["", "", "", "", "", "Total"],
            ["", "", "", "", "", "Return"],
            ["Date", "P", "D", "E", "CPI", "Price"],
            [2024.01, 100, 12, 1, 200, 1000],
            [2024.02, 110, "", 1, 202, 1100],
            [2024.03, 110, 0, 1, 203, ""],
        ]
        self.nrows, self.ncols = len(self.rows), 6

    def cell_value(self, row: int, col: int) -> Any:
        return self.rows[row][col]


class FakeBook:
    def sheet_by_name(self, name: str) -> FakeSheet:
        assert name == "Data"
        return FakeSheet()


def test_shiller_stacked_heading_and_missing_dividend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xlrd, "open_workbook", lambda **kwargs: FakeBook())
    result = read_shiller(b"synthetic workbook")
    assert result.dividends == {"2024-01": 12, "2024-03": 0}
    assert result.cpi["2024-02"] == 202
    assert result.real_total_return["2024-02"] == 1100
    assert result.diagnostic_basis == "monthly_average_real_total_return"


def test_primary_formula_carry_forward_and_complete_month() -> None:
    days = weekdays(date(2023, 12, 29), date(2024, 2, 29))
    inputs = BenchmarkInputs(fred=dict.fromkeys(days, 100.0), shiller=ShillerData(dividends={"2024-01": 12.0}))
    returns, estimated = primary_returns(inputs, date(2024, 3, 1))
    jan = [d for d in days if d.month == 1]
    feb = [d for d in days if d.month == 2]
    assert returns[jan[0]] == pytest.approx(1 / (len(jan) * 100))
    assert return_metrics([float(returns[d] or 0) for d in jan])["total_return"] == pytest.approx(
        (1 + 1 / (len(jan) * 100)) ** len(jan) - 1
    )
    assert set(feb) <= estimated
    assert not (set(jan) & estimated)
    partial, _ = primary_returns(inputs, date(2024, 2, 15))
    assert all(partial[d] is None for d in feb)
    # An observed French session exposes an unexplained FRED gap: don't treat
    # it as a holiday or reduce the dividend divisor to inflate daily cash.
    inputs.fred[jan[5]] = None
    inputs.french[jan[5]] = 0.0
    broken, _ = primary_returns(inputs, date(2024, 3, 1))
    assert all(broken[d] is None for d in jan)


def test_no_backward_dividend_fill() -> None:
    days = weekdays(date(2023, 12, 29), date(2024, 2, 29))
    data = BenchmarkInputs(fred=dict.fromkeys(days, 100.0), shiller=ShillerData(dividends={"2024-02": 12.0}))
    returns, _ = primary_returns(data, date(2024, 3, 1))
    assert returns[date(2024, 1, 31)] is None


def test_drift_matches_real_monthly_average_basis() -> None:
    days = weekdays(date(2023, 12, 29), date(2024, 3, 29))
    data = BenchmarkInputs(
        fred=dict.fromkeys(days, 100.0),
        shiller=ShillerData(
            dividends={"2024-01": 0.0},
            cpi={"2024-01": 100, "2024-02": 110, "2024-03": 110},
            real_total_return={"2024-01": 1000, "2024-02": 1000 / 1.1, "2024-03": 1000 / 1.1},
            diagnostic_basis="monthly_average_real_total_return",
        ),
    )
    returns, _ = primary_returns(data, date(2024, 4, 1))
    result = drift_diagnostic(data, returns, date(2024, 1, 1), date(2024, 3, 31))
    assert result["status"] == "ok"
    assert result["n_months"] == 2
    assert result["max_absolute_drift_pp"] == pytest.approx(0, abs=1e-12)
    data.shiller.diagnostic_basis = None
    assert drift_diagnostic(data, returns, days[1], days[-1])["status"] == "unavailable"


def test_fetch_failure_is_explicit_and_never_exposes_payload() -> None:
    def fail(url: str) -> tuple[bytes, dict[str, str]]:
        raise RuntimeError("RAW PAYLOAD MUST NEVER LEAVE MEMORY")

    inputs = fetch_inputs(fetch=fail)
    assert len(inputs.sources) == 3
    assert all(row["status"] == "unavailable" for row in inputs.sources)
    assert "RAW PAYLOAD" not in str(inputs.sources)
    assert inputs.sessions() == []
