"""Read-only packaged evaluation and document endpoints."""

from fastapi import APIRouter

from longaeva_app.api.report_schemas import ReportCatalog, SavedDocumentRead, SavedReportRead
from longaeva_app.evaluation.reports import catalog, saved_document, saved_report

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/reports", response_model=ReportCatalog)
def get_report_catalog() -> ReportCatalog:
    return catalog()


@router.get("/reports/{report_key}", response_model=SavedReportRead)
def get_saved_report(report_key: str) -> SavedReportRead:
    return saved_report(report_key)


@router.get("/documents/{document_key}", response_model=SavedDocumentRead)
def get_saved_document(document_key: str) -> SavedDocumentRead:
    return saved_document(document_key)
