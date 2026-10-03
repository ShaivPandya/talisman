"""CompanyModel interface conformance (stub second company + Visa + registry)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from stub_company import StubCompany

from longaeva_app.companies import (
    clear_registry,
    list_companies,
    register_company,
    register_default_companies,
)
from longaeva_app.companies.base import CompanyModel, FiscalPeriod
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.companies.visa.state import synthetic_starting_state
from longaeva_app.db.models import Observation, ParameterSet, Source
from longaeva_app.engine.sampler import factor_root


@pytest.fixture()
def stub() -> StubCompany:
    clear_registry()
    return StubCompany()


def _starting_state_for(model: CompanyModel) -> dict[str, float]:
    if isinstance(model, VisaModel):
        return synthetic_starting_state()
    return {spec.name: 100.0 if "activity" in spec.name else 10.0 for spec in model.state_variables}


def _seeded_shocks(model: CompanyModel, n_paths: int, seed: int) -> list[dict[str, np.ndarray]]:
    rng = np.random.default_rng(seed)
    corr = model.factor_correlation(model.default_parameters())
    root = factor_root(corr)
    quarters: list[dict[str, np.ndarray]] = []
    for _ in range(4):
        z = rng.standard_normal((n_paths, len(model.factors)))
        correlated = z @ root.T
        quarters.append({name: correlated[:, i] for i, name in enumerate(model.factors)})
    return quarters


@pytest.mark.parametrize("factory", [StubCompany, VisaModel])
def test_declarations_well_formed(factory: type[CompanyModel]) -> None:
    model = factory()
    assert model.validate_declarations() == []
    assert model.validate_parameters(model.default_parameters()) == []


@pytest.mark.parametrize("factory", [StubCompany, VisaModel])
def test_fiscal_calendar_round_trip(factory: type[CompanyModel]) -> None:
    model = factory()
    for year in (2023, 2024):
        for quarter in (1, 2, 3, 4):
            period = FiscalPeriod(year, quarter)
            start = model.calendar.period_start(period)
            end = model.calendar.period_end(period)
            assert start <= end
            assert model.calendar.period_containing(start) == period
            assert model.calendar.period_containing(end) == period
            assert model.calendar.label(period) == period.label()


@pytest.mark.parametrize("factory", [StubCompany, VisaModel])
def test_factor_correlation_valid(factory: type[CompanyModel]) -> None:
    model = factory()
    corr = model.factor_correlation(model.default_parameters())
    n = len(model.factors)
    assert corr.shape == (n, n)
    assert np.allclose(corr, corr.T)
    assert np.allclose(np.diag(corr), 1.0)
    eig = np.linalg.eigvalsh(corr)
    assert np.all(eig >= -1e-10)


@pytest.mark.parametrize("factory", [StubCompany, VisaModel])
def test_four_quarter_seeded_paths_deterministic_and_finite(factory: type[CompanyModel]) -> None:
    model = factory()
    params = model.default_parameters()
    switches = model.default_switches()
    n_paths = 64
    start = _starting_state_for(model)
    shocks = _seeded_shocks(model, n_paths, seed=42)

    def run_once() -> list[dict[str, np.ndarray]]:
        state = model.initial_state(start, params, n_paths)
        metrics_history: list[dict[str, np.ndarray]] = []
        period = FiscalPeriod(2024, 1)
        for shock in shocks:
            state_before = {k: v.copy() for k, v in state.items()}
            shock_before = {k: v.copy() for k, v in shock.items()}
            step = model.transition(state, shock, params, switches, period)
            for key, arr in state_before.items():
                assert np.array_equal(arr, state[key])
            for key, arr in shock_before.items():
                assert np.array_equal(arr, shock[key])
            state = step.state
            metrics_history.append(step.metrics)
            for arr in list(step.state.values()) + list(step.metrics.values()):
                assert arr.shape == (n_paths,)
                assert np.all(np.isfinite(arr))
            for identity in model.identities:
                result = step.metrics[identity.result]
                total = np.zeros(n_paths, dtype=np.float64)
                for term in identity.terms:
                    total = total + term.sign * step.metrics[term.metric]
                denom = np.maximum(np.abs(result), 1.0)
                assert np.all(np.abs(result - total) / denom <= identity.relative_tolerance)
            period = period.next()
        return metrics_history

    first = run_once()
    second = run_once()
    for a, b in zip(first, second, strict=True):
        for key in a:
            assert np.array_equal(a[key], b[key])


@pytest.mark.db
def test_stub_company_records_roundtrip_via_api(db_session: Session, client: TestClient) -> None:
    model = StubCompany()
    now = datetime.now(UTC)
    source = Source(
        provider="test",
        company=model.key,
        doc_type="note",
        url="https://example.test/stub",
        publication_ts=now - timedelta(minutes=5),
        retrieval_ts=now,
        content_hash=f"stub-{uuid4().hex}",
        original_path=f"originals/st/{uuid4().hex}",
    )
    db_session.add(source)
    db_session.flush()
    observation = Observation(
        company=model.key,
        source_id=source.id,
        statement_type="measured",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
        value=100.0,
        unit="index",
        review_status="pending",
    )
    db_session.add(observation)
    param_set = ParameterSet(
        company=model.key,
        cutoff_ts=now,
        values=model.default_parameters(),
        ranges={},
        evidence_links={name: {"assumption": True, "rationale": "stub default"} for name in model.default_parameters()},
        assumption_flags={name: True for name in model.default_parameters()},
        content_hash=f"stub-ps-{uuid4().hex}",
    )
    db_session.add(param_set)
    db_session.commit()

    sources = client.get("/sources", params={"company": model.key})
    assert sources.status_code == 200
    assert any(row["id"] == str(source.id) for row in sources.json())

    observations = client.get("/observations", params={"company": model.key})
    assert observations.status_code == 200
    assert any(row["id"] == str(observation.id) for row in observations.json())

    parameter_sets = client.get("/parameter-sets", params={"company": model.key})
    assert parameter_sets.status_code == 200
    assert any(row["id"] == str(param_set.id) for row in parameter_sets.json())


def test_register_stub_in_registry(stub: StubCompany) -> None:
    clear_registry()
    register_company(stub)
    assert list_companies() == ["stubco"]
    clear_registry()


def test_register_default_companies_idempotent() -> None:
    clear_registry()
    first = register_default_companies()
    second = register_default_companies()
    assert first == ["visa"]
    assert second == []
    assert list_companies() == ["visa"]
    clear_registry()
