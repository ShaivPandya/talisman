"""Earnings/multiple valuation bridge."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import numpy as np
import numpy.typing as npt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.api.schemas import ParameterEvidence, ParameterSetCreate
from longaeva_app.collect.visa_filings import source_text
from longaeva_app.db.models import ParameterSet, Scenario
from longaeva_app.runs.inputs import (
    default_parameter_ranges,
    default_parameter_values,
    parse_aware_utc,
    resolve_fixture_by_origin_date,
)
from longaeva_app.storage.local import LocalArtifactStore
from longaeva_app.valuation.bridge import OUTER_ENVELOPE_LABEL, ValuationResult, value_bridge
from longaeva_app.valuation.multiples import (
    FIXTURE_PATH,
    SOURCE_BASIS,
    EpsComponent,
    MultipleBand,
    build_history,
    history_csv_text,
    load_history,
    override_band,
    parse_utc,
    pe_band,
)
from longaeva_app.worker.queue import claim_next_job, execute_job

ORIGIN_CUTOFF = "2024-07-23T20:05:38Z"
_ORIGIN = "2024-07-23"
_N_PATHS = 32


def _cutoff() -> datetime:
    return parse_aware_utc(resolve_fixture_by_origin_date(_ORIGIN).cutoff_utc)


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _evidence_parameter_set(session: Session, cutoff: datetime) -> ParameterSet:
    values = default_parameter_values()
    obs_id = uuid4()
    links: dict[str, ParameterEvidence] = {}
    flags: dict[str, Any] = {}
    first = True
    for name in values:
        if not first:
            links[name] = ParameterEvidence(assumption=True, rationale="fixture assumption")
            flags[name] = True
        else:
            links[name] = ParameterEvidence(observation_ids=[obs_id])
            flags[name] = False
            first = False
    create = ParameterSetCreate(
        company="visa",
        cutoff_ts=cutoff,
        values=values,
        ranges=default_parameter_ranges(),
        evidence_links=links,
        assumption_flags=flags,
    )
    row = ParameterSet(
        company="visa",
        cutoff_ts=cutoff,
        values=create.values,
        ranges=create.ranges,
        evidence_links={key: link.model_dump(mode="json") for key, link in create.evidence_links.items()},
        assumption_flags=create.assumption_flags,
        content_hash=create.computed_content_hash(),
    )
    session.add(row)
    session.flush()
    return row


def _scenario(session: Session, param_set: ParameterSet) -> Scenario:
    row = Scenario(
        company="visa",
        name="test-baseline",
        parameter_set_id=param_set.id,
        interventions=[],
    )
    session.add(row)
    session.flush()
    return row


def _submit_and_execute(
    client: TestClient,
    test_engine: Engine,
    artifact_store: LocalArtifactStore,
    *,
    scenario_id: str,
    cutoff: datetime,
) -> dict[str, Any]:
    created = client.post(
        "/runs",
        json={
            "scenario_id": scenario_id,
            "cutoff_ts": cutoff.isoformat(),
            "seed": 7,
            "n_paths": _N_PATHS,
            "n_quarters": 4,
            "switches": {},
        },
    )
    assert created.status_code == 202, created.text
    payload = created.json()
    factory = _factory(test_engine)
    claimed = claim_next_job(factory, "test-worker")
    assert claimed is not None
    assert str(claimed) == payload["job_id"]
    execute_job(factory, claimed, "test-worker", artifact_store=artifact_store)
    fetched = client.get(f"/runs/{payload['id']}")
    assert fetched.status_code == 200
    result: dict[str, Any] = fetched.json()
    return result


def _paths(value: float, *, n_paths: int = 8, n_quarters: int = 4) -> npt.NDArray[np.float64]:
    return np.full((n_paths, n_quarters), value, dtype=np.float64)


def _bridge(
    paths: npt.NDArray[np.float64],
    *,
    tax_rate: float | None = 0.0,
    net_interest_other: float | None = 0.0,
    diluted_shares: float | None = 100.0,
    band: MultipleBand | None = None,
) -> ValuationResult:
    return value_bridge(
        paths,
        tax_rate=tax_rate,
        net_interest_other=net_interest_other,
        diluted_shares=diluted_shares,
        band=band if band is not None else override_band(10.0, 20.0, 30.0),
        assumption_sources={
            "tax_rate": "starting_state" if tax_rate is not None else "missing",
            "net_interest_other": "starting_state" if net_interest_other is not None else "missing",
            "diluted_shares": "starting_state" if diluted_shares is not None else "missing",
        },
    )


def test_constant_paths_match_the_earnings_identity() -> None:
    # (250 + 0) * (1 - 0) * 4 quarters / 100 shares = 10 EPS.
    result = _bridge(_paths(250.0))
    assert result.status == "ok"
    assert result.reason is None
    assert result.forward_eps is not None
    assert result.forward_eps.mean == pytest.approx(10.0)
    assert result.forward_eps.p10 == pytest.approx(10.0)
    assert result.forward_eps.p90 == pytest.approx(10.0)
    assert result.grid is not None
    assert len(result.grid) == 9
    mid = next(cell for cell in result.grid if cell.eps_quantile == "p50" and cell.multiple_role == "mid")
    assert mid.value_per_share == pytest.approx(200.0)
    assert mid.equity_usd_millions == pytest.approx(20_000.0)
    assert result.outer_envelope is not None
    assert result.outer_envelope.label == OUTER_ENVELOPE_LABEL
    assert result.outer_envelope.low_per_share == pytest.approx(100.0)
    assert result.outer_envelope.high_per_share == pytest.approx(300.0)
    assert result.assumptions[0].source == "starting_state"

    taxed = _bridge(_paths(1000.0), tax_rate=0.2, net_interest_other=75.0, diluted_shares=200.0)
    # (1000 + 75) * 0.8 * 4 / 200 = 17.2
    assert taxed.forward_eps is not None
    assert taxed.forward_eps.mean == pytest.approx(17.2)


def test_non_positive_path_is_unsupported_without_a_value() -> None:
    paths = _paths(100.0, n_paths=4)
    paths[1, :] = -500.0
    result = _bridge(paths)
    assert result.status == "unsupported"
    assert result.reason is not None
    assert "non-positive" in result.reason
    assert "1 of 4" in result.reason
    assert "bias" in result.reason
    assert result.forward_eps is None
    assert result.grid is None
    assert result.earnings_driven is None
    assert result.multiple_driven is None
    assert result.outer_envelope is None


def test_spreads_separate_earnings_and_multiple_uncertainty() -> None:
    flat = _bridge(_paths(250.0))
    assert flat.earnings_driven is not None
    assert flat.multiple_driven is not None
    assert flat.earnings_driven.spread_per_share == pytest.approx(0.0)
    assert flat.multiple_driven.spread_per_share == pytest.approx(200.0)

    varied = np.vstack([_paths(100.0, n_paths=2), _paths(300.0, n_paths=2)])
    degenerate = _bridge(varied, band=override_band(15.0, 15.0, 15.0))
    assert degenerate.status == "ok"
    assert degenerate.earnings_driven is not None
    assert degenerate.multiple_driven is not None
    assert degenerate.multiple_driven.spread_per_share == pytest.approx(0.0)
    assert degenerate.earnings_driven.spread_per_share > 0.0


def test_short_horizon_and_bad_inputs_are_unsupported() -> None:
    short = _bridge(_paths(10.0, n_quarters=3))
    assert short.status == "unsupported"
    assert short.reason is not None
    assert "3 quarters" in short.reason
    assert short.grid is None

    bad_tax = _bridge(_paths(10.0), tax_rate=1.0)
    assert bad_tax.reason is not None
    assert "tax_rate" in bad_tax.reason

    bad_shares = _bridge(_paths(10.0), diluted_shares=0.0)
    assert bad_shares.reason is not None
    assert "diluted_shares" in bad_shares.reason

    missing = _bridge(_paths(10.0), tax_rate=None)
    assert missing.reason is not None
    assert "Missing tax_rate" in missing.reason

    unordered = _bridge(_paths(10.0), band=override_band(30.0, 10.0, 20.0))
    assert unordered.reason is not None
    assert "ordered" in unordered.reason

    direct = value_bridge(
        _paths(10.0),
        tax_rate=0.0,
        net_interest_other=0.0,
        diluted_shares=100.0,
        band=None,
    )
    assert direct.status == "unsupported"
    assert direct.reason is not None
    assert "4" in direct.reason


def test_fixture_matches_a_fresh_extract_and_round_trips() -> None:
    committed = FIXTURE_PATH.read_text(encoding="utf-8")
    assert history_csv_text(load_history()) == committed
    assert history_csv_text(build_history()) == committed


def test_price_spans_match_the_bundled_originals() -> None:
    rows = load_history()
    assert len(rows) == 14
    assert rows[0].period_label == "FY2023Q1"
    assert rows[-1].period_label == "FY2026Q2"
    for row in rows:
        accession, document = row.price_source_id.split("/", 1)
        html = source_text(accession, document)
        assert html[row.price_char_start : row.price_char_end] == row.price_quote
        assert row.price_quote == f"{row.avg_purchase_price:.2f}"
        assert row.trailing_pe == pytest.approx(row.avg_purchase_price / row.ttm_eps, abs=5e-7)
        assert row.eps_components[0].period_label == row.period_label
        assert len(row.eps_components) == 4


def test_cutoff_excludes_the_same_day_10q() -> None:
    rows = load_history()
    cutoff = parse_utc(ORIGIN_CUTOFF)
    band = pe_band(cutoff, rows=rows)
    assert band is not None
    assert "FY2024Q3" not in band.periods
    assert "FY2024Q2" in band.periods
    assert band.window_start == "FY2023Q1"
    assert band.window_end == "FY2024Q2"
    assert band.n_quarters == 6
    assert "not a market close" in band.source_label
    assert "average open-market repurchase price" in band.source_label
    assert "EPS excluding special items" in band.source_label
    assert "applied to forward earnings" in band.source_label
    assert "FY2023Q1–FY2024Q2 (6 quarters)" in band.source_label
    assert SOURCE_BASIS in band.source_label

    current = next(row for row in rows if row.period_label == "FY2024Q3")
    assert current.eps_components[0].acceptance_utc <= cutoff
    assert current.price_acceptance_utc > cutoff
    assert current.price_acceptance_utc - cutoff < timedelta(hours=6)
    included = pe_band(current.price_acceptance_utc, rows=rows)
    assert included is not None
    assert "FY2024Q3" in included.periods


def test_eps_release_after_cutoff_drops_the_quarter() -> None:
    base = load_history()[0]
    early = parse_utc("2024-01-01T00:00:00Z")
    late = parse_utc("2024-06-01T00:00:00Z")
    labels = ("FY2024Q1", "FY2024Q2", "FY2024Q3", "FY2024Q4")
    synthetic = []
    for index, label in enumerate(labels):
        shifted = tuple(replace(component, acceptance_utc=early) for component in base.eps_components)
        components: tuple[EpsComponent, EpsComponent, EpsComponent, EpsComponent] = (
            shifted[0],
            shifted[1],
            shifted[2],
            shifted[3],
        )
        if index == 3:
            components = (replace(components[0], acceptance_utc=late), components[1], components[2], components[3])
        synthetic.append(
            replace(
                base,
                period_label=label,
                trailing_pe=float(10 + index * 10),
                trailing_pe_text=f"{10 + index * 10:.6f}",
                price_acceptance_utc=early,
                eps_components=components,
            )
        )
    midpoint = parse_utc("2024-03-01T00:00:00Z")
    assert pe_band(midpoint, rows=synthetic) is None
    full = pe_band(late, rows=synthetic)
    assert full is not None
    assert full.low == pytest.approx(10.0)
    assert full.high == pytest.approx(40.0)
    assert full.mid == pytest.approx(25.0)
    assert full.n_quarters == 4


@pytest.mark.db
def test_api_bridge_succeeded_queued_unknown_and_override(
    client: TestClient,
    test_engine: Engine,
    db_session: Session,
    artifact_store: LocalArtifactStore,
) -> None:
    cutoff = _cutoff()
    param_set = _evidence_parameter_set(db_session, cutoff)
    scenario = _scenario(db_session, param_set)
    db_session.commit()

    missing = client.post("/valuation/bridge", json={"run_id": str(uuid4())})
    assert missing.status_code == 404

    row = _submit_and_execute(
        client,
        test_engine,
        artifact_store,
        scenario_id=str(scenario.id),
        cutoff=cutoff,
    )
    assert row["status"] == "succeeded"
    valued = client.post("/valuation/bridge", json={"run_id": row["id"]})
    assert valued.status_code == 200, valued.text
    body = valued.json()
    assert body["status"] == "ok"
    assert body["metric"] == "operating_profit_ex_special_items"
    assert body["forward_eps"]["mean"] > 0
    assert len(body["grid"]) == 9
    assert body["earnings_driven"]["spread_per_share"] >= 0
    assert body["multiple_driven"]["spread_per_share"] > 0
    assert "not a market close" in body["multiple_band"]["source_label"]
    assert body["outer_envelope"]["label"] == OUTER_ENVELOPE_LABEL
    sources = {item["name"]: item["source"] for item in body["assumptions"]}
    assert sources == {
        "tax_rate": "starting_state",
        "net_interest_other": "starting_state",
        "diluted_shares": "starting_state",
    }

    overridden = client.post(
        "/valuation/bridge",
        json={
            "run_id": row["id"],
            "tax_rate": 0.2,
            "multiple_range": {"low": 22.0, "mid": 27.0, "high": 32.0},
        },
    )
    assert overridden.status_code == 200, overridden.text
    custom = overridden.json()
    assert custom["status"] == "ok"
    assert custom["multiple_band"]["source"] == "request_override"
    assert custom["multiple_band"]["low"] == 22.0
    assert custom["multiple_band"]["high"] == 32.0
    assert "Request override" in custom["multiple_band"]["source_label"]
    custom_sources = {item["name"]: item["source"] for item in custom["assumptions"]}
    assert custom_sources["tax_rate"] == "request_override"
    assert custom_sources["diluted_shares"] == "starting_state"
    mid = next(cell for cell in custom["grid"] if cell["eps_quantile"] == "p50" and cell["multiple_role"] == "mid")
    assert mid["multiple"] == 27.0

    queued = client.post(
        "/runs",
        json={
            "scenario_id": str(scenario.id),
            "cutoff_ts": cutoff.isoformat(),
            "seed": 7,
            "n_paths": 32,
            "n_quarters": 4,
            "switches": {},
        },
    )
    assert queued.status_code == 202, queued.text
    blocked = client.post("/valuation/bridge", json={"run_id": queued.json()["id"]})
    assert blocked.status_code == 409


@pytest.mark.db
def test_multiples_endpoint_filters_on_cutoff(client: TestClient) -> None:
    full = client.get("/valuation/multiples")
    assert full.status_code == 200, full.text
    listed = full.json()
    assert listed["status"] == "ok"
    assert len(listed["rows"]) == 14
    assert "not a market close" in listed["source_basis"]
    assert listed["rows"][0]["price_anchor"] == "Average Purchase Price per Share"

    filtered = client.get("/valuation/multiples", params={"cutoff_ts": ORIGIN_CUTOFF})
    assert filtered.status_code == 200, filtered.text
    body = filtered.json()
    labels = [row["period_label"] for row in body["rows"]]
    assert "FY2024Q3" not in labels
    assert "FY2024Q2" in labels
    assert body["band"]["window_end"] == "FY2024Q2"
    assert body["band"]["n_quarters"] == 6
    assert body["cutoff_ts"].startswith("2024-07-23T20:05:38")
