from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from api import agent_governance as governance
from api import provenance
from api.agent_governance import AgentBudgetExceeded, AgentBudgetState, ModelEgressScanState, redact_secrets


@pytest.mark.parametrize("conversation_key", ["messages", "input", "contents"])
def test_incremental_scan_matches_full_scan_after_mutations(conversation_key):
    state = ModelEgressScanState()
    payload = {
        "system": "Analyze my portfolio. password=initial-secret",
        "tools": [{"name": "lookup", "description": "Bearer abcdefghijklmnop"}],
        "config": {"system_instruction": "secret=gemini-secret", "max_output_tokens": 100},
        "max_tokens": 100,
        "api_key": "never-send-this",
        conversation_key: [{"role": "user", "content": "sk-ant-1234567890abcdefghijklmnop"}],
    }

    def verify():
        assert state.redact(payload) == redact_secrets(payload)

    verify()
    verify()
    payload[conversation_key].append({"role": "assistant", "content": [{"text": "password=tool-secret"}]})
    verify()
    payload[conversation_key][0]["content"] = "Bearer replaced-secret-token"
    payload[conversation_key][1]["content"][0]["text"] = "secret=nested-mutation"
    verify()
    payload["system"] = "password=changed-system"
    payload["tools"][0]["description"] = "api_key=changed-tool-schema"
    payload["config"]["system_instruction"] = "secret=changed-config"
    verify()
    payload[conversation_key].reverse()
    verify()
    payload[conversation_key].pop()
    verify()
    payload[conversation_key][0]["content"] = ("password=tuple-secret",)
    verify()
    payload[conversation_key][0]["content"] = ["password=tuple-secret"]
    verify()
    sanitized, findings = state.redact(payload)
    sanitized[conversation_key][0]["content"] = "password=provider-mutation"
    findings.clear()
    verify()  # Provider mutation must not poison the private cache.
    del payload[conversation_key]
    verify()


def test_incremental_scan_only_scans_new_messages_and_prunes_removed_ones(monkeypatch):
    calls = []
    original = governance.redact_secrets

    def counting_redact(value, **kwargs):
        calls.append(deepcopy(value))
        return original(value, **kwargs)

    monkeypatch.setattr(governance, "redact_secrets", counting_redact)
    state = ModelEgressScanState()
    payload = {"system": "fixed", "messages": [{"role": "user", "content": "original"}]}
    state.redact(payload)
    calls.clear()
    state.redact(deepcopy(payload))
    assert calls == []
    added = {"role": "user", "content": "password=new-secret"}
    payload["messages"].append(added)
    state.redact(payload)
    assert calls == [added]
    payload["messages"].clear()
    state.redact(payload)
    assert set(state._entries) == {"$.system"}


def test_incremental_scan_does_not_cache_opaque_values():
    state = ModelEgressScanState()
    opaque = SimpleNamespace(text="opaque")
    for _ in range(2):
        sanitized, findings = state.redact({"messages": [{"content": opaque}]})
        assert sanitized["messages"][0]["content"] is opaque
        assert findings == []
    assert state._entries == {}


def test_scan_reuse_still_checks_gateway_budget_and_audits_every_call(monkeypatch):
    audits = []
    decisions = []
    original = governance._model_gateway_decision

    def gateway(**kwargs):
        decisions.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(governance, "_model_gateway_decision", gateway)
    monkeypatch.setattr(governance, "_record_audit", lambda *args, **kwargs: audits.append(kwargs))
    state = ModelEgressScanState()
    budget = AgentBudgetState(max_model_calls=2, max_input_tokens=10000)
    kwargs = {
        "provider": "anthropic",
        "purpose": "agent_chat",
        "actor": None,
        "budget": budget,
        "scan_state": state,
        "stream_kwargs": {"model": "claude-test", "messages": [{"role": "user", "content": "portfolio"}]},
    }
    for _ in range(2):
        _, manifest = governance.prepare_model_egress(**kwargs)
        assert manifest["data_sensitivity"] == "portfolio_private"
    with pytest.raises(AgentBudgetExceeded):
        governance.prepare_model_egress(**kwargs)
    assert len(decisions) == 3
    assert len(audits) == 2


class _ProvenanceObjects:
    def __init__(self):
        self.reads = []
        self.rows = {}

    def get_object(self, uid):
        self.reads.append(uid)
        return self.rows.get(uid)

    def write_object(self, object_type, uid, properties, *args, **kwargs):
        row = {"object_uid": uid, "properties": properties}
        self.rows[uid] = row
        return row


def test_unique_provenance_skips_reads_but_finish_and_reusable_ids_still_validate(monkeypatch):
    objects = _ProvenanceObjects()
    monkeypatch.setattr(provenance, "should_attempt_optional_ontology_write", lambda **kwargs: True)
    monkeypatch.setattr(provenance, "OntologyObjectService", lambda: objects)
    result = provenance.start_event(event_type="model_call", event_name="test", event_id="fresh", unique_event_id=True)
    assert result["status"] == "started"
    assert objects.reads == []
    assert provenance.finish_event("fresh", status="succeeded")["status"] == "succeeded"
    assert objects.reads == ["fresh"]
    original = deepcopy(objects.rows["fresh"])
    assert provenance.start_event(event_type="model_call", event_name="test", event_id="fresh")["status"] == "succeeded"
    assert objects.rows["fresh"] == original
    with pytest.raises(provenance.ProvenanceWriteError, match="already terminal"):
        provenance.finish_event("fresh", status="failed")
    objects.reads.clear()
    provenance.start_event(event_type="model_call", event_name="test", event_id="reusable", idempotency_key="retry")
    assert len(objects.reads) == 2


@pytest.mark.parametrize("kwargs", [{}, {"event_id": "stable", "idempotency_key": "retry"}])
def test_unique_provenance_requires_an_explicit_non_idempotent_id(kwargs):
    with pytest.raises(ValueError, match="fresh event_id"):
        provenance.start_event(event_type="model_call", event_name="test", unique_event_id=True, **kwargs)


def test_agent_provenance_ids_remain_unique_with_a_frozen_clock(monkeypatch):
    from api.routers import agent

    starts = []
    monkeypatch.setattr(provenance, "start_event", lambda **kwargs: starts.append(kwargs))
    monkeypatch.setattr(agent.time, "time", lambda: 1234567890.0)
    for _ in range(2):
        agent._start_agent_turn_provenance(session_id="s", message="same", provider="anthropic", actor=None)
        agent._start_model_call_provenance(
            parent_event_id=None,
            session_id="s",
            workflow_run_id=None,
            provider="anthropic",
            purpose="agent_chat",
            stream_kwargs={},
            actor=None,
            attempt=0,
        )
    assert len({row["event_id"] for row in starts}) == 4
    assert all(row["unique_event_id"] is True for row in starts)
