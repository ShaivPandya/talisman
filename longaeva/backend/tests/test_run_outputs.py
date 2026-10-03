"""Unit tests for run output hashing, provenance, fixtures, and archive kind (LON-23)."""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy.orm import Session

from longaeva_app import __version__
from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.companies.visa.state import synthetic_starting_state
from longaeva_app.engine.outputs import (
    RELATIVE_TOLERANCE,
    canonical_outputs_hash,
    load_npz_arrays,
    max_relative_difference,
    simulation_to_npz_bytes,
    summary_payload,
)
from longaeva_app.engine.provenance import code_version, files_digest, simulation_source_files
from longaeva_app.engine.replay import compare_simulation
from longaeva_app.engine.runner import SimulationResult, simulate
from longaeva_app.runs.errors import RunError
from longaeva_app.runs.forecasts import expected_forecast_kind
from longaeva_app.runs.inputs import (
    document_manifest_for_fixture,
    resolve_fixture,
    resolve_fixture_by_origin_date,
    starting_state_hash,
    starting_state_values,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _small_sim(*, seed: int = 1, n_paths: int = 8) -> SimulationResult:
    model = VisaModel()
    return simulate(
        model,
        synthetic_starting_state(),
        model.default_parameters(),
        origin=FiscalPeriod(2024, 3),
        seed=seed,
        n_paths=n_paths,
        n_quarters=4,
    )


def test_package_version_matches_pyproject() -> None:
    data = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == data["project"]["version"]


def test_outputs_hash_stable_and_order_independent() -> None:
    result = _small_sim(seed=3)
    first = canonical_outputs_hash(result)
    shuffled = SimulationResult(
        metrics={key: result.metrics[key] for key in reversed(list(result.metrics))},
        states={key: result.states[key] for key in reversed(list(result.states))},
        draws=result.draws,
        periods=result.periods,
        seed=result.seed,
        n_paths=result.n_paths,
        switches=result.switches,
        params=result.params,
    )
    assert canonical_outputs_hash(shuffled) == first
    assert canonical_outputs_hash(_small_sim(seed=3)) == first


def test_outputs_hash_changes_on_one_ulp() -> None:
    result = _small_sim(seed=4)
    baseline = canonical_outputs_hash(result)
    tweaked_metrics = dict(result.metrics)
    arr = np.array(tweaked_metrics["net_revenue"], dtype=np.float64, copy=True)
    arr[0, 0] = np.nextafter(arr[0, 0], arr[0, 0] + 1.0)
    tweaked_metrics["net_revenue"] = arr
    changed = SimulationResult(
        metrics=tweaked_metrics,
        states=result.states,
        draws=result.draws,
        periods=result.periods,
        seed=result.seed,
        n_paths=result.n_paths,
        switches=result.switches,
        params=result.params,
    )
    assert canonical_outputs_hash(changed) != baseline


def test_npz_roundtrip_preserves_arrays() -> None:
    result = _small_sim(seed=5)
    metrics, states, periods = load_npz_arrays(simulation_to_npz_bytes(result))
    assert periods == [period.label() for period in result.periods]
    assert max_relative_difference(metrics, result.metrics) == 0.0
    assert max_relative_difference(states, result.states) == 0.0


def test_code_version_includes_simulation_sources_and_changes_with_bytes() -> None:
    files = simulation_source_files()
    names = {path.name for path in files}
    assert "runner.py" in names
    assert "hashing.py" in names
    assert "model.py" in names
    digest = files_digest(files)
    assert files_digest(files, extra=b"changed") != digest
    assert code_version().startswith(f"{__version__}+")


def test_summary_payload_has_quarter_keys() -> None:
    payload = summary_payload(_small_sim(seed=6))
    assert {item["quarter_index"] for item in payload} == {0, 1, 2, 3}
    assert all("period_label" in item and "std" in item for item in payload)


def test_compare_exact_match() -> None:
    result = _small_sim(seed=7)
    digest = canonical_outputs_hash(result)
    comparison = compare_simulation(result, recorded_hash=digest)
    assert comparison.status == "exact_match"
    assert comparison.differences == []


def test_compare_numerically_equivalent_on_hash_mismatch_with_identical_arrays() -> None:
    result = _small_sim(seed=8)
    comparison = compare_simulation(
        result,
        recorded_hash="0" * 64,
        recorded_metrics=result.metrics,
        recorded_states=result.states,
        recorded_code_version="a",
        recomputed_code_version="a",
        recorded_lib_versions={"numpy": "2"},
        recomputed_lib_versions={"numpy": "2", "blas": "openblas"},
    )
    assert comparison.status == "numerically_equivalent"
    assert comparison.max_relative_difference <= RELATIVE_TOLERANCE
    assert "outputs_hash" in comparison.differences
    assert any(item.startswith("lib_versions.blas") for item in comparison.differences)


def test_resolve_both_fixtures_and_reject_unknown() -> None:
    a = resolve_fixture(datetime(2024, 7, 23, 20, 5, 38, tzinfo=UTC))
    b = resolve_fixture(datetime(2025, 10, 28, 20, 6, 3, tzinfo=UTC))
    assert a.origin_date.isoformat() == "2024-07-23"
    assert b.origin_date.isoformat() == "2025-10-28"
    by_date = resolve_fixture(datetime(2024, 7, 23, 0, 0, tzinfo=UTC))
    assert by_date.origin_date.isoformat() == "2024-07-23"
    assert resolve_fixture_by_origin_date("2025-10-28").fiscal_year == 2025
    with pytest.raises(RunError, match="No reconciled starting state"):
        resolve_fixture(datetime(2020, 1, 1, tzinfo=UTC))


def test_starting_state_hash_stable() -> None:
    fixture = resolve_fixture_by_origin_date("2024-07-23")
    values = starting_state_values(fixture)
    assert starting_state_hash(values) == starting_state_hash(dict(reversed(list(values.items()))))


@pytest.mark.db
def test_manifest_excludes_post_cutoff_documents(db_session: Session) -> None:
    fixture = resolve_fixture_by_origin_date("2024-07-23")
    entries = document_manifest_for_fixture(db_session, fixture)
    assert entries
    input_keys = {ref.source_id for ref in fixture.sources.values() if ref.role == "input"}
    assert {item["document_key"] for item in entries} == input_keys
    assert all(item["publication_ts"] <= fixture.cutoff_utc for item in entries)


def test_expected_forecast_kind_uses_clock() -> None:
    before = datetime(2024, 7, 24, tzinfo=UTC)
    after = datetime(2026, 10, 3, tzinfo=UTC)
    assert expected_forecast_kind(fiscal_year=2024, fiscal_quarter=3, now=before) == "prospective"
    assert expected_forecast_kind(fiscal_year=2024, fiscal_quarter=3, now=after) == "retrospective"
    assert expected_forecast_kind(fiscal_year=2026, fiscal_quarter=3, now=after) == "prospective"
