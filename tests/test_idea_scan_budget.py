from __future__ import annotations

from types import SimpleNamespace

import pytest

import llm_utils
from api.idea_scan import budget as b


def anthropic_response(input_tokens=1000, output_tokens=500, searches=0, cache_read=0, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text="{}")],
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=0,
            server_tool_use=SimpleNamespace(web_search_requests=searches),
        ),
    )


def test_usage_and_cost_for_anthropic():
    usage = b.usage_from_response("anthropic", anthropic_response(10_000, 2_000, searches=2, cache_read=1_000))
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens, usage.web_searches) == (
        10_000,
        2_000,
        1_000,
        2,
    )
    # Sonnet 5.5: $2/M in, $10/M out, $0.20/M cache read, $0.01 per search.
    assert b.cost_usd("claude-sonnet-5-5", usage) == pytest.approx(0.02 + 0.02 + 0.0002 + 0.02)
    assert b.cost_usd("claude-opus-5-5", usage) == pytest.approx(0.04 + 0.04 + 0.0002 + 0.02)


def test_usage_for_openai_and_gemini():
    openai = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=1000, output_tokens=100, input_tokens_details=SimpleNamespace(cached_tokens=400)
        ),
        output=[SimpleNamespace(type="web_search_call"), SimpleNamespace(type="message")],
    )
    usage = b.usage_from_response("openai", openai)
    assert (usage.input_tokens, usage.cache_read_tokens, usage.web_searches) == (600, 400, 1)

    gemini = SimpleNamespace(
        usage_metadata=SimpleNamespace(prompt_token_count=800, candidates_token_count=100, thoughts_token_count=50),
        candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(web_search_queries=["a", "b"]))],
    )
    usage = b.usage_from_response("gemini", gemini)
    assert (usage.input_tokens, usage.output_tokens, usage.web_searches) == (800, 150, 2)


def test_unknown_and_dated_models_are_priced():
    assert b.model_price("claude-opus-5-5-20260401") == b.MODEL_PRICES["claude-opus-5-5"]
    assert b.model_price("anthropic.claude-haiku-4-5") == b.MODEL_PRICES["claude-haiku-4-5"]
    assert b.model_price("mystery-model") == b.FALLBACK_PRICE


def test_production_review_model_is_priced(caplog):
    # A gpt-6-luna review from the 2026-10-29 production run: 13,339 in, 850 out, one search.
    usage = b.Usage(input_tokens=13_339, output_tokens=850, web_searches=1)
    assert b.cost_usd("gpt-6-luna", usage) == pytest.approx(0.01176, abs=1e-5)
    with caplog.at_level("WARNING"):
        b.model_price("gpt-unlisted")
        b.model_price("gpt-unlisted")
    assert sum("no price for model" in r.message for r in caplog.records) == 1


def test_track_counts_every_observed_response():
    budget = b.RunBudget(2.0)
    with budget.track("review", "AAA"):
        llm_utils._notify_response_observer(
            "anthropic", "claude-sonnet-5-5", anthropic_response(10_000, 1_000, searches=1)
        )
        llm_utils._notify_response_observer("anthropic", "claude-sonnet-5-5", anthropic_response(5_000, 500))
    llm_utils._notify_response_observer("anthropic", "claude-sonnet-5-5", anthropic_response(10**9, 10**9))
    record = budget.records[0]
    assert record.calls == 2
    assert record.usage.input_tokens == 15_000
    assert budget.spent_usd == pytest.approx(0.03 + 0.015 + 0.01)
    assert budget.summary()["by_step"] == {"review": pytest.approx(0.055)}


def test_estimates_follow_observed_costs_and_gate_new_steps():
    budget = b.RunBudget(0.5)
    assert budget.estimate("review") == b.RunBudget.PRIOR_ESTIMATES_USD["review"]
    assert budget.can_start("review")
    with budget.track("review", "AAA"):
        llm_utils._notify_response_observer("anthropic", "claude-sonnet-5-5", anthropic_response(100_000, 10_000))
    assert budget.spent_usd == pytest.approx(0.3)
    assert budget.estimate("review") == pytest.approx(0.375)
    assert not budget.can_start("review")
    assert budget.can_start("digest", reserve_usd=0.0)
    assert not budget.can_start("digest", reserve_usd=0.2)


class _FakeAnthropicMessages:
    def __init__(self, responses):
        self.responses = list(responses)

    def create(self, **_kwargs):
        return self.responses.pop(0)


def test_observer_sees_pause_turn_continuations(monkeypatch):
    responses = [anthropic_response(1000, 10, searches=1, stop_reason="pause_turn"), anthropic_response(2000, 20)]
    client = SimpleNamespace(messages=_FakeAnthropicMessages(responses))
    monkeypatch.setattr(llm_utils, "get_llm_client", lambda *_a, **_k: client)
    seen = []
    with llm_utils.observe_llm_responses(lambda provider, model, response: seen.append((provider, model, response))):
        llm_utils._call_anthropic_messages(
            messages=[{"role": "user", "content": "hi"}],
            model="claude-sonnet-5-5",
            api_key="test",
            max_tokens=100,
        )
    assert [s[0] for s in seen] == ["anthropic", "anthropic"]
    assert sum(b.usage_from_response("anthropic", s[2]).input_tokens for s in seen) == 3000


def test_failing_observer_never_breaks_the_call():
    def boom(*_args):
        raise RuntimeError("accounting bug")

    with llm_utils.observe_llm_responses(boom):
        llm_utils._notify_response_observer("anthropic", "m", anthropic_response())


def test_search_hits_are_collected_as_sources():
    response = anthropic_response(searches=1)
    response.content = [
        SimpleNamespace(type="server_tool_use", name="web_search"),
        SimpleNamespace(
            type="web_search_tool_result",
            content=[
                SimpleNamespace(type="web_search_result", url="https://news.example.com/a", title="A"),
                SimpleNamespace(type="web_search_result", url="https://news.example.com/b", title="B"),
            ],
        ),
        SimpleNamespace(type="web_search_tool_result", content=SimpleNamespace(error_code="max_uses_exceeded")),
        SimpleNamespace(
            type="text", text="{}", citations=[SimpleNamespace(title="A again", url="https://news.example.com/a")]
        ),
    ]
    assert b.search_sources(response) == [
        ("A again", "https://news.example.com/a"),
        ("A", "https://news.example.com/a"),
        ("B", "https://news.example.com/b"),
    ]
    budget = b.RunBudget(2.0)
    with budget.track("macro", "m") as record:
        llm_utils._notify_response_observer("anthropic", "claude-opus-5-5", response)
        llm_utils._notify_response_observer("anthropic", "claude-opus-5-5", response)
    assert [url for _t, url in record.sources] == ["https://news.example.com/a", "https://news.example.com/b"]
