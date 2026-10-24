from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest

from api import agent_tools, provenance
from api.agent_governance import ToolPolicyDenied, ToolTimeoutError
from ontology.policy import PolicyDenied
from ontology.schemas.objects import ProvenanceEvent


def test_concurrent_cached_tool_calls_keep_metadata_private(monkeypatch):
    cached = {"value": 123, "_meta": {"fetched_at": "2026-10-24T00:00:00+00:00", "cache_ttl": 60}}
    original = deepcopy(cached)
    workers = 8
    attached = Barrier(workers)
    attach_meta = agent_tools._attach_meta

    def attach_together(payload, meta):
        result = attach_meta(payload, meta)
        if "provenance_event_id" in meta:
            # Every call attaches its metadata before any call serializes its result.
            attached.wait(timeout=10)
        return result

    monkeypatch.setattr(agent_tools, "_attach_meta", attach_together)
    monkeypatch.setattr(agent_tools, "_call_dispatch", lambda *args, **kwargs: (cached, {"cache": "hit"}))
    monkeypatch.setattr(agent_tools, "_finish_tool_provenance", lambda **kwargs: None)
    monkeypatch.setattr(provenance, "start_event", lambda **kwargs: None)
    monkeypatch.setattr("api.agent_governance._record_audit", lambda *args, **kwargs: None)

    def call(index):
        return json.loads(
            agent_tools.execute_tool("get_liquidity", {}, provenance_context={"event_id": f"call-{index}"})
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(call, range(workers)))

    assert cached == original
    for index, result in enumerate(results):
        assert result["value"] == 123
        assert result["_meta"]["provenance_event_id"] == f"call-{index}"
        assert result["_meta"]["fetched_at"] == original["_meta"]["fetched_at"]
        assert result["_meta"]["cache"] == "hit"


class _ProvenanceObjects:
    def __init__(self):
        self.rows = {}
        self.statuses = []

    def get_object(self, uid):
        return self.rows.get(uid)

    def write_object(self, object_type, uid, properties, *args, **kwargs):
        assert object_type == "ProvenanceEvent"
        validated = ProvenanceEvent.model_validate(properties)
        self.statuses.append(validated.status)
        row = {"object_uid": uid, "properties": validated.model_dump()}
        self.rows[uid] = row
        return row


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("get_liquidity", {}),
        ("propose_news_digest_delete", {"digest_id": "digest-1", "reason": "test"}),
    ],
)
@pytest.mark.parametrize(
    ("failure", "tool_status", "terminal_status"),
    [
        (ToolPolicyDenied("Tool policy denied"), "denied", "failed"),
        (PolicyDenied("Ontology policy denied"), "denied", "failed"),
        (ToolTimeoutError("Tool timed out"), "timed_out", "failed"),
        (RuntimeError("Provider failed"), "failed", "failed"),
        (None, "succeeded", "succeeded"),
    ],
)
def test_tool_outcomes_finish_schema_valid_provenance(
    monkeypatch, tool_name, arguments, failure, tool_status, terminal_status
):
    objects = _ProvenanceObjects()
    monkeypatch.setattr(provenance, "should_attempt_optional_ontology_write", lambda **kwargs: True)
    monkeypatch.setattr(provenance, "OntologyObjectService", lambda: objects)
    monkeypatch.setattr("api.agent_governance._record_audit", lambda *args, **kwargs: None)

    def dispatch(*args, **kwargs):
        if failure is not None:
            raise failure
        return {"value": 123, "status": "pending", "approval_id": 1}, {"cache": "hit"}, 1

    monkeypatch.setattr(agent_tools, "_call_dispatch_with_governance", dispatch)
    result = json.loads(agent_tools.execute_tool(tool_name, arguments, provenance_context={"event_id": "tool-event"}))
    event = objects.rows["tool-event"]["properties"]

    assert objects.statuses == ["started", terminal_status]
    assert event["status"] == terminal_status
    assert event["completed_at"]
    assert event["output_hash"] == provenance.output_hash(result)
    if failure is not None:
        assert event["error"] == str(failure)
    if tool_status in {"denied", "timed_out"}:
        assert event["metadata"]["tool_status"] == tool_status
    # Finishing the same outcome remains idempotent, and terminal events stay terminal.
    assert provenance.finish_event("tool-event", status=terminal_status)["status"] == terminal_status
    assert objects.statuses == ["started", terminal_status]
    other_status = "succeeded" if terminal_status == "failed" else "failed"
    with pytest.raises(provenance.ProvenanceWriteError, match="already terminal"):
        provenance.finish_event("tool-event", status=other_status)
