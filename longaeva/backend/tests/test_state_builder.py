"""Starting-state builder tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from longaeva_app.companies.visa.starting_state import (
    identity_residuals,
    load_fixture,
    required_fixture_paths,
    to_starting_state,
)
from longaeva_app.companies.visa.state_builder import (
    StateBuildError,
    build_fixture_for_origin_date,
    buildable_origin_dates,
)
from longaeva_app.evaluation.origins import load_evaluation_origins
from longaeva_app.runs.errors import RunError
from longaeva_app.runs.inputs import resolve_fixture, resolve_fixture_by_origin_date


def test_builder_matches_committed_fixtures() -> None:
    for path in required_fixture_paths():
        committed = load_fixture(path)
        built = build_fixture_for_origin_date(committed.origin_date.isoformat())
        gold = to_starting_state(committed)
        got = to_starting_state(built)
        assert set(got) >= set(gold)
        for name, expected in gold.items():
            actual = got[name]
            denom = max(abs(expected), 1e-12)
            assert abs(actual - expected) / denom < 1e-9, name


def test_all_candidate_and_prospective_origins() -> None:
    origins = load_evaluation_origins(include_prospective=True)
    failed: list[str] = []
    built: list[str] = []
    for origin in origins:
        try:
            fixture = build_fixture_for_origin_date(origin.origin_date)
        except StateBuildError:
            failed.append(origin.label)
            continue
        built.append(origin.label)
        assert all(r.passed for r in identity_residuals(fixture))
        from longaeva_app.runs.inputs import parse_aware_utc

        cutoff = parse_aware_utc(fixture.cutoff_utc)
        for ref in fixture.sources.values():
            assert parse_aware_utc(ref.acceptance_utc) <= cutoff
    assert failed == ["FY2022Q3", "FY2022Q4"]
    assert "FY2022Q1" in built
    assert "FY2022Q2" in built
    assert "FY2026Q3" in built


def test_resolve_fixture_precedence_and_fallback() -> None:
    a = resolve_fixture(datetime(2024, 7, 23, 20, 5, 38, tzinfo=UTC))
    assert a.origin_date.isoformat() == "2024-07-23"
    # Non-fixture buildable origin.
    b = resolve_fixture_by_origin_date("2024-01-25")
    assert b.fiscal_year == 2024 and b.fiscal_quarter == 1
    with pytest.raises(RunError, match="No reconciled starting state|Unknown origin"):
        resolve_fixture(datetime(2020, 1, 1, tzinfo=UTC))


def test_buildable_origin_dates_listed() -> None:
    dates = buildable_origin_dates()
    assert "2024-07-23" in dates
    assert "2022-07-26" in dates  # listed even though build fails
    assert len(dates) == 19
