from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api import company_research as legacy
from api import company_research_context as context
from api import company_research_store as store
from api.company_research_evidence import Fact, Source, validate_sources
from ontology.policy import actor_to_dict, user_actor


@pytest.fixture
def research_context(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SQLITE_PATH", tmp_path / "runs.sqlite3")
    monkeypatch.setattr(legacy, "LOCAL_REPORTS_DIR", tmp_path / "reports")
    snapshot = {
        "ticker": "MU",
        "kinds": ["overview"],
        "model": "gpt-6.1-sol",
        "prompts": {"overview": "Research {ticker}"},
        "prompt_version": "v1",
        "requested_at": "2026-10-24",
        "actor": actor_to_dict(user_actor("researcher", roles=("admin",))),
    }
    state = store.create_run(snapshot, apply=False)[0]
    assert store.claim_run(state["run_id"], "worker")
    provider = SimpleNamespace(request=MagicMock())
    return context.ResearchContext(provider, state, "worker")


def choice(tool="get_thesis", **args):
    return context.ReadChoice(tool=tool, arguments_json=json.dumps(args), reason="Relevant company operating evidence")


def collect(research_context, monkeypatch, data=None):
    research_context.provider.request.side_effect = [
        context.ReadSelection(reads=[choice()]),
        context.ReadSelection(reads=[]),
    ]
    read = MagicMock(
        return_value=json.dumps(data or {"note": "Private forecast: 37 units.", "observed_on": "2026-10-20"})
    )
    monkeypatch.setattr(context, "execute_tool", read)
    research_context.collect("Micron")
    return read


def fact(research_context, **changes):
    snapshot = research_context.sources[0]
    source = Source(
        url=snapshot["url"],
        title=snapshot["title"],
        passage="Private forecast: 37 units.",
        published_on=date(2026, 10, 20),
        location="note, observed_on",
    ).model_copy(update=changes)
    return Fact(record_id="private", section="Business", claim="Internal forecast is 37 units.", sources=[source])


def test_discovery_uses_requesting_actor_and_resume_freezes_selected_reads(research_context, monkeypatch):
    read = collect(research_context, monkeypatch)
    assert read.call_count == 1
    assert read.call_args.kwargs["actor"].actor_id == "researcher"
    assert read.call_args.args == ("get_thesis", {"ticker": "MU"})
    assert read.call_args.kwargs["provenance_context"]["workflow_run_id"] == research_context.run_id
    assert all(
        c.kwargs["private"] and not c.kwargs.get("web") for c in research_context.provider.request.call_args_list
    )
    frozen = list(research_context.sources)
    resumed = context.ResearchContext(research_context.provider, research_context.state, "worker")
    read.side_effect = AssertionError("Resume must not re-read mutable data")
    resumed.collect("Micron")
    assert resumed.sources == frozen
    assert research_context.provider.request.call_count == 2


def test_selection_is_bounded_deduplicated_and_rejects_writes(research_context, monkeypatch):
    research_context.provider.request.side_effect = [
        context.ReadSelection(reads=[choice(), choice(), choice("propose_catalyst")]),
        context.ReadSelection(reads=[choice(), choice("search_web", query="MU"), choice("get_thesis", ticker="AAPL")]),
    ]
    read = MagicMock(return_value='{"note":"Company evidence"}')
    monkeypatch.setattr(context, "execute_tool", read)
    research_context.collect("Micron")
    assert read.call_count == 1
    assert len(research_context.sources) == 1
    assert len(research_context.warnings) == 3


def test_denied_reads_and_missing_sources_are_visible_gaps(research_context, monkeypatch):
    collect(research_context, monkeypatch, {"error": "Policy denied", "_meta": {"status": "blocked"}})
    assert not research_context.sources
    assert "unavailable or denied" in research_context.warnings[0]
    evidence = research_context.evidence("overview", ["Business"], [])
    assert evidence.gaps == research_context.warnings and not evidence.facts


def test_snapshot_redacts_secrets_before_persistence_and_followup_selection(research_context, monkeypatch):
    collect(research_context, monkeypatch, {"api_key": "fixture-private-value", "note": "Operating data"})
    assert research_context.sources[0]["data"]["api_key"] != "fixture-private-value"
    assert "fixture-private-value" not in legacy._read_json(research_context.key).__str__()
    assert "fixture-private-value" not in research_context.provider.request.call_args.kwargs["prompt"]


def test_context_size_cap_does_not_silently_clip_a_source(research_context, monkeypatch):
    collect(research_context, monkeypatch, {"note": "x" * context.MAX_CONTEXT_BYTES})
    assert not research_context.sources
    assert "bounded context" in research_context.warnings[0]


def test_checkpoint_survives_worker_replacement_before_context_completion(research_context, monkeypatch):
    read = collect(research_context, monkeypatch)
    # Reproduce a crash after saving the read, before saving the collection manifest.
    path = legacy.LOCAL_REPORTS_DIR / research_context.key
    path.unlink()
    research_context.provider.request.side_effect = [
        context.ReadSelection(reads=[choice()]),
        context.ReadSelection(reads=[]),
    ]
    resumed = context.ResearchContext(research_context.provider, research_context.state, "worker")
    resumed.collect("Micron")
    assert read.call_count == 1 and resumed.sources == research_context.sources


def test_read_arguments_scope_company_data_and_disable_refreshes():
    catalog = context.read_catalog()
    args = context.read_arguments(
        choice("search_knowledge_base", query="capacity", tickers="AAPL", top_k=100), "MU", catalog
    )
    assert args["tickers"] == "MU" and args["top_k"] == 5
    args = context.read_arguments(choice("get_industry_monitor", refresh=True), "MU", catalog)
    assert not args["refresh"]
    args = context.read_arguments(choice("search_alternative_data_catalog", suggest_sites=True), "MU", catalog)
    assert not args["suggest_sites"] and args["ticker"] == "MU"
    for selected in (
        choice("get_thesis", ticker="AAPL"),
        choice("get_thesis", account_id="other"),
        choice("fetch_alternative_data"),
    ):
        with pytest.raises(ValueError):
            context.read_arguments(selected, "MU", catalog)


def test_private_citations_bind_to_saved_passages_dates_and_run(research_context, monkeypatch):
    collect(research_context, monkeypatch)
    original = fact(research_context)
    research_context.validate_sources(original)
    validate_sources(original, as_of=date(2026, 10, 24))
    for changes in (
        {"passage": "Invented production figure"},
        {"published_on": date(2026, 10, 19)},
        {"title": "Mislabelled public filing"},
        {"url": original.sources[0].url.replace("MU/", "AAPL/")},
        {"url": "https://unobserved.example/"},
    ):
        with pytest.raises(ValueError):
            research_context.validate_sources(fact(research_context, **changes))


def test_citation_excerpts_preserve_quotes_and_markdown_newlines(research_context, monkeypatch):
    passage = 'The company said "37 units".\nA second line.'
    collect(research_context, monkeypatch, {"markdown": passage})
    research_context.validate_sources(fact(research_context, passage=passage, published_on=None))


@pytest.mark.parametrize("written_date", ["05 August 2026", "5 August 2026", "August 5, 2026", "Aug. 5, 2026"])
@pytest.mark.parametrize("description", ["", "; revenue discussion", ": Revenue", " (Revenue)", " — Revenue"])
def test_upload_quotes_accept_pdf_whitespace_and_unambiguous_dates(research_context, written_date, description):
    url = "/api/names/MU/documents/" + "a" * 32 + "/content"
    research_context.sources = [
        {
            "url": url,
            "title": "Private upload: analyst.pdf",
            "source_kind": "private_upload",
            "data": {
                "passages": [
                    {"url": url, "location": "page 1, excerpt 1", "text": written_date + "\nRevenue rose\n20%."}
                ]
            },
        }
    ]
    citation = Source(
        url=url,
        title="Private upload: analyst.pdf",
        published_on=date(2026, 8, 5),
        passage="Revenue rose 20%.",
        location="page 1, excerpt 1" + description,
    )
    research_context.validate_sources(citation)
    assert citation.location == "page 1, excerpt 1"
    for changes in (
        {"published_on": date(2026, 8, 6)},
        {"passage": "Revenue rose 21%."},
        {"location": "page 2, excerpt 1"},
        {"location": "page 1, excerpt 10; Revenue"},
        {"location": "page 10, excerpt 1; Revenue"},
    ):
        with pytest.raises(ValueError):
            research_context.validate_sources(citation.model_copy(update=changes))


def test_uploaded_quote_location_is_canonical_in_retained_evidence(research_context):
    url = "/api/names/MU/documents/" + "a" * 32 + "/content"
    research_context.sources = [
        {
            "url": url,
            "title": "Private upload: analyst.txt",
            "source_kind": "private_upload",
            "data": {"passages": [{"url": url, "location": "lines 10-20", "text": "Revenue rose 20%."}]},
        }
    ]
    record = Fact(
        record_id="upload",
        section="Business",
        claim="Revenue rose 20%.",
        sources=[
            Source(
                url=url,
                title="Private upload: analyst.txt",
                published_on=None,
                passage="Revenue rose 20%.",
                location="  LINES   10-20; revenue discussion",
            )
        ],
    )

    def respond(_step, _model, **kwargs):
        result = context.ContextEvidence(facts=[record], commitments=[], gaps=[])
        kwargs["validate"](result)
        return result

    research_context.provider.request.side_effect = respond
    result = research_context.evidence("overview", ["Business"], [])
    assert len(result.facts) == 1 and not result.gaps
    assert result.facts[0].sources[0].location == "lines 10-20"


def test_private_evidence_retains_supported_records_and_reports_rejections(research_context, monkeypatch):
    collect(research_context, monkeypatch)
    supported = fact(research_context)
    unsupported = supported.model_copy(deep=True)
    unsupported.record_id = "invented"
    unsupported.sources[0].passage = "A different unsupported forecast."

    def respond(_step, _model, **kwargs):
        value = context.ContextEvidence(facts=[supported, unsupported], commitments=[], gaps=[])
        kwargs["validate"](value)
        return value

    research_context.provider.request.side_effect = respond
    result = research_context.evidence("overview", ["Business"], [])
    assert result.facts == [supported]
    assert len(result.gaps) == 1 and "invented" in result.gaps[0]

    def all_invalid(_step, _model, **kwargs):
        value = context.ContextEvidence(facts=[unsupported], commitments=[], gaps=[])
        kwargs["validate"](value)
        return value

    research_context.provider.request.side_effect = all_invalid
    with pytest.raises(ValueError, match="exact excerpts"):
        research_context.evidence("overview", ["Business"], [])


def test_private_evidence_requires_assigned_sections_and_stable_ids(research_context, monkeypatch):
    collect(research_context, monkeypatch)
    original = fact(research_context)

    def respond(_step, _model, **kwargs):
        result = context.ContextEvidence(facts=[original], commitments=[], gaps=[])
        kwargs["validate"](result)
        before = result.facts[0].record_id
        kwargs["validate"](result)
        assert before == result.facts[0].record_id
        return result

    research_context.provider.request.side_effect = respond
    assert research_context.evidence("overview", ["Business"], []).facts
    with pytest.raises(ValueError, match="assigned section"):
        research_context.evidence("overview", ["Risks"], [])


def test_source_endpoint_requires_original_actor_and_matching_run(auth_client, research_context, monkeypatch):
    from fastapi.testclient import TestClient

    collect(research_context, monkeypatch)
    source_url = research_context.sources[0]["url"]
    assert TestClient(auth_client.app).get(source_url).status_code == 401
    assert auth_client.get(source_url).status_code == 404
    # The authenticated test admin can read only its own research snapshots.
    store.mutate_run(
        research_context.run_id,
        lambda s: s["snapshot"].update(actor=actor_to_dict(user_actor("admin", roles=("admin",)))),
    )
    result = auth_client.get(source_url)
    assert result.status_code == 200 and "no-store" in result.headers["cache-control"]
    assert result.json()["data"]["note"] == "Private forecast: 37 units."
    assert auth_client.get(source_url.replace("MU/", "AAPL/")).status_code == 404
    assert auth_client.get(source_url[:-24] + "0" * 24).status_code == 404
