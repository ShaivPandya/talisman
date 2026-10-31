"""Conservative guard: new calls in async routes require a nonblocking review."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Keep this small: heavy work belongs in the callable passed to run_in_threadpool.
# These calls only read upload bytes asynchronously, dispatch workers, or raise errors.
COMMON_SAFE_CALLS = {"read_upload_file_bytes", "run_in_threadpool", "ValidationError", "HTTPException"}
REVIEWED_SAFE_CALLS = {
    "thesis.py": {"_normalize_ticker", "_validate_ticker", "enqueue_document_generation_upload"},
    "overview.py": {"_normalize_ticker", "_validate_ticker", "enqueue_document_generation_upload"},
    "management_quality.py": {"_normalize_ticker", "_validate_ticker", "enqueue_document_generation_upload"},
    "source_ingestion.py": {"require_multimodal_ingestion_enabled", "UploadInput", "_actor_dict"},
    "portfolio_edit.py": {"_is_ibkr_flex_xml_upload"},
    "economic_growth.py": {"_is_excel_upload"},
    "portfolio_news.py": {"_is_markdown_upload"},
    "news_digest_sync.py": {"require_news_digest_sync_secret", "_is_markdown_upload"},
}


def _unreviewed_calls(function: ast.AsyncFunctionDef, allowed: set[str]) -> list[ast.Call]:
    # Defaults, annotations, and route decorators run when the module is imported.
    return [
        node
        for statement in function.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call) and ast.unparse(node.func) not in allowed
    ]


def test_async_routes_only_call_reviewed_nonblocking_functions():
    paths = sorted((ROOT / "api" / "routers").rglob("*.py"))
    # The document routes delegate here; guard their async callee as well.
    paths.append(ROOT / "api" / "document_generation_jobs.py")
    violations = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        allowed = COMMON_SAFE_CALLS | REVIEWED_SAFE_CALLS.get(path.name, set())
        for function in tree.body:
            if isinstance(function, ast.AsyncFunctionDef):
                violations.extend(
                    f"{path.relative_to(ROOT)}:{call.lineno}: {function.name} calls {ast.unparse(call.func)}"
                    for call in _unreviewed_calls(function, allowed)
                )
    assert not violations, "Move blocking work into run_in_threadpool or review the call:\n" + "\n".join(violations)


@pytest.mark.parametrize(
    "statement",
    [
        "write_bytes(path, key, payload)",
        "SourceIngestionService().upload_artifact(upload)",
        "parse_ibkr_flex_open_positions_xml(payload)",
        "requests.get(url)",
        "await run_in_threadpool(service_factory(), payload)",
    ],
)
def test_guard_flags_direct_and_nested_blocking_calls(statement):
    function = ast.parse(f"async def upload():\n    {statement}\n").body[0]
    assert isinstance(function, ast.AsyncFunctionDef)
    assert _unreviewed_calls(function, COMMON_SAFE_CALLS)


def test_guard_allows_threadpool_dispatch_and_ignores_import_time_defaults():
    function = ast.parse(
        "@router.post('/upload')\n"
        "async def upload(file: UploadFile = File(...)):\n"
        "    payload = await read_upload_file_bytes(file, limit_bytes=1024)\n"
        "    return await run_in_threadpool(process_upload, payload)\n"
    ).body[0]
    assert isinstance(function, ast.AsyncFunctionDef)
    assert not _unreviewed_calls(function, COMMON_SAFE_CALLS)
