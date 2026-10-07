"""Read packaged artifacts without a database, network, or scoring side effects."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from longaeva_app.api.report_schemas import (
    AblationReport,
    DocumentMetadata,
    ExtractionReport,
    ForecastReport,
    PortfolioReport,
    ReportCatalog,
    ReportMetadata,
    SavedDocumentRead,
    SavedReportRead,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[3]

# The client supplies keys, never filesystem paths.
REPORTS = {
    "full_model": ("Full model", "forecast", "LON-27", "visa_full_model.json"),
    "seasonal_trend": ("Seasonal / trend", "forecast", "LON-29", "visa_seasonal_trend.json"),
    "financial_only": ("Financial-only driver model", "forecast", "LON-29", "visa_financial_only.json"),
    "guidance": ("Company guidance", "forecast", "LON-29", "visa_guidance.json"),
    "no_external_commentary": ("No external commentary", "forecast", "LON-31", "visa_no_external_commentary.json"),
    "pooled_spending": ("Pooled spending", "forecast", "LON-31", "visa_pooled_spending.json"),
    "no_service_lag": ("No service lag", "forecast", "LON-31", "visa_no_service_lag.json"),
    "ablations": ("Ablation robustness", "ablations", "LON-31", "visa_ablation_persistence.json"),
    "portfolio": ("Benchmarks and portfolio", "portfolio", "LON-28", "visa_portfolio.json"),
    "extraction": ("Extraction error sample", "extraction", "LON-18", "extraction.json"),
    "llm_baseline": ("LLM same-document baseline", "forecast", "LON-30", "visa_llm_baseline.json"),
    "prospective": ("Prospective Q4 FY2026 registration", "pending", "LON-32", None),
    "failure_case": ("Final report and failure case", "pending", "LON-33", None),
}
DOCUMENTS = {
    "evaluation-notes": ("Evaluation notes", "LON-27", "docs/evaluation.md"),
    "extraction-eval": ("Extraction evaluation guide", "LON-18", "docs/extraction-eval.md"),
    "llm-baseline": ("LLM forecast baseline guide", "LON-30", "docs/llm-baseline.md"),
    "model-spec": ("Model specification", "LON-19", "docs/model-spec.md"),
    "evaluation-report": ("Final evaluation report", "LON-33", "docs/evaluation-report.md"),
    "limitations": ("Limitations", "LON-33", "docs/limitations.md"),
    "definitions": ("Visa definitions", "LON-2", "docs/definitions.md"),
    "scenarios": ("Scenarios", "LON-22", "docs/scenarios.md"),
    "valuation": ("Valuation bridge", "LON-25", "docs/valuation.md"),
    "actions": ("Illustrative actions", "LON-26", "docs/actions.md"),
    "portfolio-evaluation": ("Portfolio evaluation", "LON-28", "docs/portfolio-evaluation.md"),
    "ablation-persistence": ("Ablation persistence", "LON-31", "data/evaluation/ablation_persistence.md"),
}


def report_metadata(key: str) -> ReportMetadata:
    if key not in REPORTS:
        raise HTTPException(404, "Unknown saved report")
    title, kind, owner, filename = REPORTS[key]
    available = filename is not None and (PACKAGE_ROOT / "data/evaluation" / filename).is_file()
    return ReportMetadata.model_validate(
        {
            "key": key,
            "title": title,
            "kind": kind,
            "owner_issue": owner,
            "status": "available" if available else "pending",
            "reason": None if available else f"Saved content is not available yet; owned by {owner}.",
        }
    )


def document_metadata(key: str) -> DocumentMetadata:
    if key not in DOCUMENTS:
        raise HTTPException(404, "Unknown saved document")
    title, owner, filename = DOCUMENTS[key]
    available = (PACKAGE_ROOT / filename).is_file()
    return DocumentMetadata(
        key=key,
        title=title,
        filename=filename,
        owner_issue=owner,
        status="available" if available else "pending",
        reason=None if available else f"Saved document is not available yet; owned by {owner}.",
    )


def catalog() -> ReportCatalog:
    return ReportCatalog(
        reports=[report_metadata(key) for key in REPORTS],
        documents=[document_metadata(key) for key in DOCUMENTS],
    )


def _object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Expected a saved object")
    return raw


def _project(key: str, data: dict[str, Any]) -> dict[str, Any]:
    kind = REPORTS[key][1]
    if kind == "forecast":
        # Drop the per-origin inputs and duplicated retained evidence. Keep saved scores.
        return {"forecast": ForecastReport.model_validate(data).model_dump()}
    if kind == "portfolio":
        return {"portfolio": PortfolioReport.model_validate(data).model_dump()}
    if kind == "extraction":
        return {"extraction": ExtractionReport.model_validate(data).model_dump()}
    if kind == "ablations":
        profiles = _object(data["profiles"])
        summaries = {name: profile["summary"] for name, profile in profiles.items()}
        hashes = {
            name: {r["config"]["model_variant"]: r["config_hash"] for r in profile["reports"]}
            for name, profile in profiles.items()
        }
        projection = {
            k: data[k]
            for k in (
                "suite_version",
                "content_hash",
                "delta_convention",
                "profile_policy",
                "settings",
                "robustness",
            )
        }
        projection.update(summaries=summaries, config_hashes=hashes)
        return {"ablations": AblationReport.model_validate(projection).model_dump()}
    raise ValueError("Unsupported saved report kind")


@lru_cache(maxsize=12)
def _cached_report(key: str, path: Path, mtime: int, size: int) -> dict[str, Any]:
    # Fingerprint invalidates a cached projection when a later issue replaces an artifact.
    del mtime, size
    data = _object(json.loads(path.read_text(encoding="utf-8")))
    return _project(key, data)


def saved_report(key: str) -> SavedReportRead:
    metadata = report_metadata(key)
    if metadata.status == "pending":
        return SavedReportRead(**metadata.model_dump())
    filename = REPORTS[key][3]
    assert filename is not None
    path = PACKAGE_ROOT / "data/evaluation" / filename
    try:
        stat = path.stat()
        projection = _cached_report(key, path, stat.st_mtime_ns, stat.st_size)
        return SavedReportRead(**metadata.model_dump(), **projection)
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        raise HTTPException(500, f"Saved report '{key}' is unreadable or invalid.") from exc


def saved_document(key: str) -> SavedDocumentRead:
    metadata = document_metadata(key)
    if metadata.status == "pending":
        return SavedDocumentRead(**metadata.model_dump())
    try:
        markdown = (PACKAGE_ROOT / metadata.filename).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HTTPException(500, f"Saved document '{key}' is unreadable.") from exc
    return SavedDocumentRead(
        **metadata.model_dump(),
        markdown=markdown,
        document_links={Path(filename).name: doc_key for doc_key, (_, _, filename) in DOCUMENTS.items()},
    )
