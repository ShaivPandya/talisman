from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from api.agent_costs import agent_turn_cost
from api.agent_models import AgentChatRequest
from api.routers import agent


def call(**overrides):
    return {
        "provider": "anthropic",
        "model": "claude-sonnet-5-5",
        "status": "ok",
        "input_tokens": 10_000,
        "output_tokens": 1000,
        **overrides,
    }


def test_cost_prices_each_round_with_cache_reads_and_writes():
    result = agent_turn_cost(
        [
            call(cache_creation_input_tokens=8000),
            call(cache_read_input_tokens=8000),
            call(provider="openai", model="gpt-6-luna", input_tokens=1000, output_tokens=100),
        ]
    )
    assert result["estimated_usd"] == pytest.approx(0.04895)
    assert result["complete"] is True
    assert result["model_calls"] == result["priced_model_calls"] == 3
    assert result["input_tokens"] == 21_000


def test_anthropic_hour_cache_and_dated_models():
    result = agent_turn_cost(
        [
            call(
                model="claude-sonnet-5-5-20260928",
                cache_creation_input_tokens=8000,
                cache_creation_long_input_tokens=3000,
            )
        ]
    )
    assert result["estimated_usd"] == pytest.approx(0.0385)


def test_long_context_is_priced_per_request_rather_than_turn_total():
    short = call(provider="openai", model="gpt-6.1-sol", input_tokens=200_000)
    assert agent_turn_cost([short, short])["estimated_usd"] == pytest.approx(0.82)
    assert agent_turn_cost([{**short, "input_tokens": 300_000}])["estimated_usd"] == pytest.approx(1.215)


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": "custom-model"},
        {"model": "gpt-6.1-sol-pro", "provider": "openai"},
        {"provider": "talisman"},
        {"output_tokens": None},
        {"input_tokens": -1},
        {"input_tokens": True},
        {"cache_read_input_tokens": 20_000},
    ],
)
def test_missing_or_invalid_pricing_is_never_reported_as_free(overrides):
    result = agent_turn_cost([call(**overrides)])
    assert result["estimated_usd"] is None
    assert result["complete"] is False
    assert result["priced_model_calls"] == 0


def test_retries_with_reported_usage_count_and_unreported_retries_are_partial():
    result = agent_turn_cost([call(status="error"), call(), call(output_tokens=None, status="error")])
    assert result["estimated_usd"] == pytest.approx(0.06)
    assert result["complete"] is False
    assert result["model_calls"] == 3
    assert result["priced_model_calls"] == 2


def test_deterministic_and_denied_turns_have_no_model_cost():
    assert agent_turn_cost([])["estimated_usd"] == 0
    assert agent_turn_cost([call(status="denied")])["model_calls"] == 0


def test_gemini_promotion_expiry_does_not_change_saved_estimates():
    model_call = call(provider="gemini", model="gemini-4-argon")
    before = agent_turn_cost([model_call], now=datetime(2026, 11, 30, tzinfo=UTC))
    after = agent_turn_cost([model_call], now=datetime(2026, 12, 1, tzinfo=UTC))
    assert before["estimated_usd"] == pytest.approx(0.03)
    assert after["estimated_usd"] == pytest.approx(0.06)


def test_gemini_cost_includes_thinking_and_cache_discount():
    usage = agent._usage_dict(
        SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=10_000,
                candidates_token_count=100,
                thoughts_token_count=900,
                cached_content_token_count=8000,
            )
        )
    )
    result = agent_turn_cost(
        [call(provider="gemini", model="gemini-4-argon", **usage)], now=datetime(2026, 10, 29, tzinfo=UTC)
    )
    assert result["estimated_usd"] == pytest.approx(0.0148)


def test_done_payload_and_saved_transcript_metadata_share_cost():
    timings = agent._new_agent_timings()
    agent._record_model_timing(
        timings,
        {"input_tokens": 10_000, "output_tokens": 1000},
        started=0,
        status="ok",
        provider="anthropic",
        model="claude-sonnet-5-5",
    )
    # Timing inputs ordinarily contain only usage, phase and purpose, not provider identity.
    guard = agent._TurnTranscriptGuard(AgentChatRequest(message="Review liquidity"))
    guard.timings = timings
    payload = agent._done_payload({"usage": {}}, timings, 0)
    assert payload["cost"] == guard.metadata()["cost"]
    assert payload["cost"]["estimated_usd"] == pytest.approx(0.03)


def test_cost_survives_message_storage_round_trip():
    from api.conversation_messages import message_record, record_message

    cost = agent_turn_cost([call()])
    row = message_record("session", {"role": "assistant", "content": "Answer", "cost": cost}, 1, None)
    assert record_message(row)["cost"] == cost
