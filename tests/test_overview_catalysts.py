from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api.exceptions import DataFetchError, NotFoundError, ValidationError
from api.routers import ideas
from ontology.policy import admin_actor
from portfolio import overview_catalysts as extraction

OVERVIEW = """# MU Overview

## Financials
- Revenue recovered.

## Key Catalysts
- **HBM launch:** New memory ships in Q4. [Filing](https://example.com/filing)
- **HBM launch:** New memory ships in Q4. [Filing](https://example.com/filing)
- TBD
- None

## Industry
- This is not a catalyst.
"""


def test_parse_overview_catalysts_is_scoped_deduplicated_and_preserves_sources():
    rows = extraction.parse_overview_catalysts(OVERVIEW)
    assert len(rows) == 1
    assert rows[0]["label"] == "HBM launch"
    assert rows[0]["description"] == "HBM launch: New memory ships in Q4. [Filing](https://example.com/filing)"
    assert rows[0]["category"] == "event"


def test_parse_plain_catalysts_preserves_long_descriptions_and_heading_variants():
    description = "New production capacity will be commissioned in Q4, increasing available volume for customers."
    rows = extraction.parse_overview_catalysts(f"## Upcoming catalysts\n- {description}\n")
    assert rows[0]["description"] == description


def test_explicit_catalysts_do_not_require_an_llm(monkeypatch):
    monkeypatch.setattr(extraction, "call_llm_text", lambda **kw: pytest.fail("Unexpected LLM call"))
    assert extraction.extract_overview_catalysts("MU", OVERVIEW) == extraction.parse_overview_catalysts(OVERVIEW)


def test_extract_legacy_overview_with_source_constrained_schema(monkeypatch):
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps({"catalysts": [{"label": "HBM launch", "description": "Ships in Q4."}]}), [], None

    monkeypatch.setattr(extraction, "call_llm_text", generate)
    result = extraction.extract_overview_catalysts("MU", "# MU Overview\nCapacity ships in Q4.")
    assert result[0]["description"] == "HBM launch: Ships in Q4."
    assert "Capacity ships in Q4." in calls[0]["prompt"]
    assert "Use only facts supported by the document" in calls[0]["system"]
    assert calls[0]["json_schema"]["required"] == ["catalysts"]


@pytest.mark.parametrize("output", ["not json", "{}", '{"catalysts": null}'])
def test_extraction_rejects_invalid_output(monkeypatch, output):
    monkeypatch.setattr(extraction, "call_llm_text", lambda **kw: (output, [], None))
    with pytest.raises(ValueError, match="invalid output"):
        extraction.extract_overview_catalysts("MU", "# MU Overview")


@pytest.fixture
def idea_extraction(monkeypatch):
    monkeypatch.setattr(ideas, "_get_idea", lambda idea_id: {"id": idea_id, "ticker": "MU"})
    monkeypatch.setattr(ideas, "_read_state_text", lambda *args: (OVERVIEW, None))
    monkeypatch.setattr(ideas, "OntologyRuntimeReadService", lambda: SimpleNamespace(catalysts=lambda *a, **kw: []))
    calls = []

    def stage(action_id, payload, **kwargs):
        calls.append((action_id, payload, kwargs))
        return {"application_status": "applied"}

    monkeypatch.setattr(ideas, "stage_api_action", stage)
    return calls


def test_idea_extraction_uses_governed_overview_save(idea_extraction):
    actor = admin_actor(source="test")
    result = ideas.extract_idea_catalysts("test", actor)
    assert result["extracted_count"] == 1
    action, payload, options = idea_extraction[0]
    assert action == "save_overview_content"
    assert payload["ticker"] == "MU"
    assert "## Financials" in payload["content"]
    assert "## Industry" in payload["content"]
    assert len(extraction.parse_overview_catalysts(payload["content"])) == 1
    assert options["actor"] == actor
    assert options["apply"] is True


def test_existing_research_report_is_used_for_legacy_summaries(idea_extraction, monkeypatch):
    from api import company_research

    monkeypatch.setattr(ideas, "_read_state_text", lambda *args: ("# MU Overview\nRevenue recovered.", None))
    monkeypatch.setattr(
        company_research, "read_research_report", lambda *args: {"summary_applied": True, "content": OVERVIEW}
    )
    monkeypatch.setattr(extraction, "call_llm_text", lambda **kw: pytest.fail("Unexpected LLM call"))
    result = ideas.extract_idea_catalysts("test", admin_actor(source="test"))
    assert result["extracted_count"] == 1
    assert "HBM launch" in idea_extraction[0][1]["content"]


@pytest.mark.parametrize("content,error", [(None, None), (None, "storage unavailable")])
def test_idea_extraction_requires_readable_overview(idea_extraction, monkeypatch, content, error):
    monkeypatch.setattr(ideas, "_read_state_text", lambda *args: (content, error))
    with pytest.raises(DataFetchError if error else ValidationError):
        ideas.extract_idea_catalysts("test", admin_actor(source="test"))
    assert idea_extraction == []


def test_idea_extraction_requires_existing_idea(idea_extraction, monkeypatch):
    monkeypatch.setattr(ideas, "_get_idea", lambda idea_id: None)
    with pytest.raises(NotFoundError):
        ideas.extract_idea_catalysts("missing", admin_actor(source="test"))
    assert idea_extraction == []


def test_no_catalysts_does_not_mutate_overview(idea_extraction, monkeypatch):
    monkeypatch.setattr(extraction, "extract_overview_catalysts", lambda *args: [])
    result = ideas.extract_idea_catalysts("test", admin_actor(source="test"))
    assert result["extracted_count"] == 0
    assert idea_extraction == []


def test_failed_extraction_does_not_mutate_overview(idea_extraction, monkeypatch):
    def fail(*args):
        raise ValueError("invalid extraction")

    monkeypatch.setattr(extraction, "extract_overview_catalysts", fail)
    with pytest.raises(DataFetchError):
        ideas.extract_idea_catalysts("test", admin_actor(source="test"))
    assert idea_extraction == []
