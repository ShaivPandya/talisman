"""Read-only domain API tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from longaeva_app.db.models import (
    DocumentText,
    EvaluationResult,
    Forecast,
    ParameterSet,
    Run,
    Scenario,
    Source,
)


def _seed_graph(session: Session) -> dict[str, Any]:
    now = datetime.now(UTC)
    source = Source(
        provider="sec",
        company="visa",
        doc_type="8-K",
        url="https://example.test/visa",
        publication_ts=now - timedelta(hours=2),
        retrieval_ts=now - timedelta(hours=1),
        content_hash=f"read-{uuid4().hex}",
        original_path=f"originals/rd/{uuid4().hex}",
    )
    session.add(source)
    session.flush()
    passage = DocumentText(
        source_id=source.id,
        page=0,
        char_start=0,
        char_end=12,
        text="payments volume",
    )
    session.add(passage)
    param_set = ParameterSet(
        company="visa",
        cutoff_ts=now,
        values={"yield": 0.01},
        ranges={},
        evidence_links={"yield": {"assumption": True, "rationale": "fixture"}},
        assumption_flags={"yield": True},
        content_hash=f"ps-{uuid4().hex}",
    )
    session.add(param_set)
    session.flush()
    scenario = Scenario(
        company="visa",
        name="baseline",
        parameter_set_id=param_set.id,
        interventions=[],
    )
    session.add(scenario)
    session.flush()
    run = Run(
        scenario_id=scenario.id,
        cutoff_ts=now,
        source_manifest=[{"source_id": str(source.id), "content_hash": source.content_hash}],
        source_manifest_hash=f"sm-{uuid4().hex}",
        parameter_set_hash=param_set.content_hash,
        starting_state_hash=f"st-{uuid4().hex}",
        origin_label="FY2024Q3",
        n_quarters=4,
        code_version="0.1.0",
        seed=7,
        n_paths=100,
        switches={"service_lag": True},
        lib_versions={"numpy": "2.0"},
        status="succeeded",
        outputs_path="runs/fixture/paths.npz",
        outputs_hash="b" * 64,
        summary=[{"metric": "net_revenue", "quarter_index": 0, "period_label": "FY2024Q4", "mean": 100.0}],
    )
    session.add(run)
    session.flush()
    retrospective = Forecast(
        run_id=run.id,
        origin_ts=now,
        cutoff_ts=now,
        target_period_start=date(2024, 7, 1),
        target_period_end=date(2024, 9, 30),
        metric="net_revenue",
        quantiles={"0.5": 100.0},
        kind="retrospective",
    )
    prospective = Forecast(
        run_id=run.id,
        origin_ts=now,
        cutoff_ts=now,
        target_period_start=date(2026, 7, 1),
        target_period_end=date(2026, 9, 30),
        metric="net_revenue",
        quantiles={"0.5": 110.0},
        kind="prospective",
    )
    session.add_all([retrospective, prospective])
    evaluation = EvaluationResult(
        suite_version="v1",
        origin_ts=now,
        model_variant="full",
        metric="mae",
        value=1.23,
        config_hash=f"cfg-{uuid4().hex}",
        details={"n": 8},
    )
    session.add(evaluation)
    session.commit()
    return {
        "source": source,
        "passage": passage,
        "param_set": param_set,
        "scenario": scenario,
        "run": run,
        "retrospective": retrospective,
        "prospective": prospective,
        "evaluation": evaluation,
    }


@pytest.mark.db
def test_read_endpoints_map_rows(client: TestClient, db_session: Session) -> None:
    graph = _seed_graph(db_session)
    source = graph["source"]
    assert isinstance(source, Source)
    param_set = graph["param_set"]
    scenario = graph["scenario"]
    run = graph["run"]
    assert isinstance(param_set, ParameterSet)
    assert isinstance(scenario, Scenario)
    assert isinstance(run, Run)

    assert client.get(f"/sources/{source.id}").status_code == 200
    passages = client.get(f"/sources/{source.id}/passages")
    assert passages.status_code == 200
    assert passages.json()[0]["text"] == "payments volume"

    assert client.get(f"/parameter-sets/{param_set.id}").status_code == 200
    assert client.get(f"/scenarios/{scenario.id}").status_code == 200
    assert client.get(f"/runs/{run.id}").status_code == 200

    forecasts = client.get("/forecasts")
    assert forecasts.status_code == 200
    assert len(forecasts.json()) == 2

    prospective = client.get("/forecasts", params={"kind": "prospective"})
    assert prospective.status_code == 200
    body = prospective.json()
    assert len(body) == 1
    assert body[0]["kind"] == "prospective"

    evaluation = client.get("/evaluation-results")
    assert evaluation.status_code == 200
    assert evaluation.json()[0]["metric"] == "mae"


@pytest.mark.db
def test_unknown_ids_return_404(client: TestClient) -> None:
    missing = uuid4()
    assert client.get(f"/sources/{missing}").status_code == 404
    assert client.get(f"/observations/{missing}").status_code == 404
    assert client.get(f"/parameter-sets/{missing}").status_code == 404
    assert client.get(f"/scenarios/{missing}").status_code == 404
    assert client.get(f"/runs/{missing}").status_code == 404
    assert client.get(f"/forecasts/{missing}").status_code == 404


@pytest.mark.db
def test_forecast_mutations_rejected_by_api(client: TestClient, db_session: Session) -> None:
    graph = _seed_graph(db_session)
    retrospective = graph["retrospective"]
    assert isinstance(retrospective, Forecast)
    forecast_id = retrospective.id
    assert client.put(f"/forecasts/{forecast_id}", json={"metric": "x"}).status_code == 405
    assert client.patch(f"/forecasts/{forecast_id}", json={"metric": "x"}).status_code == 405
    assert client.delete(f"/forecasts/{forecast_id}").status_code == 405
