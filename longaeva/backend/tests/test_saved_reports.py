"""Packaged result projections, availability, and database-free reads."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from longaeva_app.api.main import app
from longaeva_app.db.session import get_db
from longaeva_app.evaluation import reports


@pytest.fixture()
def report_client() -> Any:
    def forbidden_db() -> None:
        raise AssertionError("Saved reports must not open a database")

    app.dependency_overrides[get_db] = forbidden_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _original(filename: str) -> dict[str, Any]:
    return dict(json.loads((reports.PACKAGE_ROOT / "data/evaluation" / filename).read_text()))


def test_catalog_and_completed_document_without_db(report_client: TestClient) -> None:
    response = report_client.get("/evaluation/reports")
    assert response.status_code == 200
    catalog = {r["key"]: r for r in response.json()["reports"]}
    assert catalog["full_model"]["status"] == "available"
    for key, owner in {
        "failure_case": "LON-33",
    }.items():
        result = report_client.get(f"/evaluation/reports/{key}").json()
        assert result["status"] == "available"
        assert result["kind"] == "document"
        assert result["document_key"] == "evaluation-report"
        assert result["owner_issue"] == owner
        assert result["forecast"] is result["ablations"] is result["portfolio"] is None
    assert catalog["llm_baseline"]["status"] == "available"
    document = report_client.get("/evaluation/documents/evaluation-report").json()
    assert "## Failure case" in document["markdown"]
    assert "## Matched-origin baseline comparisons" in document["markdown"]


def test_prospective_is_available_without_db_and_never_scored(report_client: TestClient) -> None:
    result = report_client.get("/evaluation/reports/prospective")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["kind"] == "prospective"
    assert body["status"] == "available"
    assert body["forecast"] is None
    report = body["prospective"]
    assert report["target"] == "FY2026Q4"
    assert report["scoring_status"] == "Not yet scored"
    assert len(report["forecasts"]) == 20
    assert "aggregates" not in report and "n_scored" not in report
    assert "parameters" not in report and "evidence" not in report
    assert len(result.content) < 30_000
    assert report["replay_status"] == "exact_match"


def test_prospective_invalid_artifacts_fail_visibly(
    report_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original = reports.PACKAGE_ROOT / "data/demo/forecasts"
    destination = tmp_path / "data/demo/forecasts"
    shutil.copytree(original, destination)
    monkeypatch.setattr(reports, "PACKAGE_ROOT", tmp_path)
    (tmp_path / "data/evaluation").mkdir(parents=True)
    path = destination / "prospective_fy2026q4.json"
    content = path.read_bytes()
    path.write_text("not json")
    assert report_client.get("/evaluation/reports/prospective").status_code == 500
    path.write_bytes(content)
    (destination / "prospective_fy2026q4.paths.npz").write_bytes(b"corrupted")
    assert report_client.get("/evaluation/reports/prospective").status_code == 500


def test_extraction_preserves_coverage_denominators_and_provenance(report_client: TestClient) -> None:
    original = _original("extraction.json")
    result = report_client.get("/evaluation/reports/extraction")
    assert result.status_code == 200
    assert result.json()["kind"] == "extraction"
    assert result.json()["extraction"] == original
    assert result.json()["extraction"]["coverage"]["total_labels"] >= 40


@pytest.mark.parametrize(
    "key",
    [
        "full_model",
        "seasonal_trend",
        "financial_only",
        "guidance",
        "llm_baseline",
        "no_external_commentary",
        "pooled_spending",
        "no_service_lag",
    ],
)
def test_forecast_projection_keeps_saved_scores_and_counts(report_client: TestClient, key: str) -> None:
    original = _original(f"visa_{key}.json")
    response = report_client.get(f"/evaluation/reports/{key}")
    assert response.status_code == 200
    report = response.json()["forecast"]
    assert report["config"] == original["config"]
    assert report["config_hash"] == original["config_hash"]
    assert report["n_scored"] == original["n_scored"]
    assert report["n_excluded"] == original["n_excluded"]
    assert report["aggregates"] == original["aggregates"]
    assert report["four_quarter"] == original["four_quarter"]
    assert [o["scores"] for o in report["origins"]] == [o["scores"] for o in original["origins"]]
    assert all("inputs" not in o for o in report["origins"])


def test_ablations_are_bounded_and_keep_every_profile(report_client: TestClient) -> None:
    original = _original("visa_ablation_persistence.json")
    response = report_client.get("/evaluation/reports/ablations")
    assert response.status_code == 200
    result = response.json()["ablations"]
    assert len(response.content) < 1_000_000
    assert result["content_hash"] == original["content_hash"]
    assert result["robustness"] == original["robustness"]
    assert result["summaries"] == {k: v["summary"] for k, v in original["profiles"].items()}
    assert len(result["summaries"]) == 13
    assert "profiles" not in result and "evidence" not in result


def test_portfolio_preserves_exact_labels_nulls_and_exclusions(report_client: TestClient) -> None:
    original = _original("visa_portfolio.json")
    response = report_client.get("/evaluation/reports/portfolio")
    assert response.status_code == 200
    result = response.json()["portfolio"]
    assert result["labels"] == original["labels"]
    assert result["aggregates"] == original["aggregates"]
    assert result["overlap"] == original["overlap"]
    assert result["n_excluded"] == 3
    assert result["visa_strategy"]["status"] == "not_run"
    assert result["visa_buy_and_hold"]["metrics"] is None
    assert all(o["visa_strategy"]["metrics"] is None for o in result["origins"])


def test_documents_and_unknown_keys(report_client: TestClient) -> None:
    result = report_client.get("/evaluation/documents/model-spec")
    assert result.status_code == 200
    assert result.json()["markdown"] == (reports.PACKAGE_ROOT / "docs/model-spec.md").read_text()
    assert result.json()["document_links"]["definitions.md"] == "definitions"
    assert result.json()["document_links"]["mapping-rules.md"] == "mapping-rules"
    assert result.json()["document_links"]["visa-parser.md"] == "visa-parser"
    for path in ["/evaluation/reports/secrets", "/evaluation/documents/secrets", "/evaluation/documents/%2E%2E%2F.env"]:
        assert report_client.get(path).status_code == 404


def test_missing_invalid_and_replaced_artifacts(
    report_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original = _original("visa_full_model.json")
    monkeypatch.setattr(reports, "PACKAGE_ROOT", tmp_path)
    assert report_client.get("/evaluation/reports/full_model").json()["status"] == "pending"
    assert report_client.get("/evaluation/reports/extraction").json()["status"] == "pending"
    assert report_client.get("/evaluation/reports/prospective").json()["status"] == "pending"
    assert report_client.get("/evaluation/documents/model-spec").json()["status"] == "pending"
    assert report_client.get("/evaluation/reports/failure_case").json()["status"] == "pending"
    path = tmp_path / "data/evaluation/visa_full_model.json"
    path.parent.mkdir(parents=True)
    for invalid in ["not json", "[]", '{"origins":[]}']:
        path.write_text(invalid)
        result = report_client.get("/evaluation/reports/full_model")
        assert result.status_code == 500
        assert "invalid" in result.json()["detail"]
    path.write_text(json.dumps(original))
    assert (
        report_client.get("/evaluation/reports/full_model").json()["forecast"]["config_hash"] == original["config_hash"]
    )
    original["config_hash"] = "changed-in-disposable-test-artifact"
    path.write_text(json.dumps(original))
    assert (
        report_client.get("/evaluation/reports/full_model").json()["forecast"]["config_hash"] == original["config_hash"]
    )


def test_openapi_has_new_and_existing_contracts(report_client: TestClient) -> None:
    schema = report_client.get("/openapi.json").json()
    assert "/evaluation-results" in schema["paths"]
    assert "/evaluation/reports/{report_key}" in schema["paths"]
    assert "/evaluation/documents/{document_key}" in schema["paths"]
    assert "SavedReportRead" in schema["components"]["schemas"]
