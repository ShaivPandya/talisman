"""Provider adapters with httpx.MockTransport. No network."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from longaeva_app.config import Settings
from longaeva_app.extract.providers import (
    AnthropicProvider,
    GeminiProvider,
    OpenAIProvider,
    ProviderError,
    StubProvider,
    build_provider,
    describe_extraction,
)

KEY = "short-key"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "llm_provider": "",
        "llm_model": "",
        "llm_base_url": "",
        "anthropic_api_key": SecretStr(""),
        "openai_api_key": SecretStr(""),
        "gemini_api_key": SecretStr(""),
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_unset_provider_does_not_construct_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> httpx.Client:
        raise AssertionError("httpx.Client must not be constructed")

    monkeypatch.setattr("longaeva_app.extract.providers.httpx.Client", boom)
    settings = _settings()
    assert describe_extraction(settings).enabled is False
    assert "unset" in (describe_extraction(settings).disabled_reason or "").lower()
    assert build_provider(settings) is None


def test_missing_key_disables_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> httpx.Client:
        raise AssertionError("httpx.Client must not be constructed")

    monkeypatch.setattr("longaeva_app.extract.providers.httpx.Client", boom)
    settings = _settings(llm_provider="anthropic")
    described = describe_extraction(settings)
    assert described.enabled is False
    assert described.disabled_reason is not None
    assert "API key" in described.disabled_reason
    assert build_provider(settings) is None


def test_unknown_provider_disables_without_raising() -> None:
    settings = _settings(llm_provider="nope")
    described = describe_extraction(settings)
    assert described.enabled is False
    assert described.disabled_reason is not None
    assert "Unknown" in described.disabled_reason
    assert build_provider(settings) is None


def test_stub_provider_does_not_construct_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> httpx.Client:
        raise AssertionError("httpx.Client must not be constructed")

    monkeypatch.setattr("longaeva_app.extract.providers.httpx.Client", boom)
    provider = build_provider(_settings(llm_provider="stub"))
    assert isinstance(provider, StubProvider)
    result = provider.complete(system="rules", user="Passage:\nonly this")
    assert result.parsed == {"observations": []}
    assert provider.seen == [("rules", "Passage:\nonly this")]


def _transport(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_anthropic_request_shape_and_tool_parse() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["api_key"] = request.headers.get("x-api-key")
        seen["version"] = request.headers.get("anthropic-version")
        payload = {
            "content": [
                {
                    "type": "tool_use",
                    "name": "record_observations",
                    "input": {"observations": []},
                }
            ],
            "usage": {"input_tokens": 3, "output_tokens": 4},
        }
        return httpx.Response(200, json=payload)

    provider = AnthropicProvider(
        model="claude-sonnet-4-6",
        api_key=KEY,
        client=_transport(handler),
        owns_client=True,
        root="https://api.anthropic.com",
        max_output_tokens=128,
    )
    result = provider.complete(system="rules", user="Passage:\nRoom nights grew 8%")
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["api_key"] == KEY
    assert seen["version"] == "2023-06-01"
    assert seen["body"]["tool_choice"] == {"type": "tool", "name": "record_observations"}
    assert seen["body"]["tools"][0]["input_schema"]["additionalProperties"] is False
    assert seen["body"]["messages"][0]["content"] == "Passage:\nRoom nights grew 8%"
    assert result.parsed == {"observations": []}
    assert result.input_tokens == 3
    assert result.output_tokens == 4


def test_openai_request_shape_and_output_text() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["authorization"] = request.headers.get("authorization")
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": '{"observations": []}'}],
                }
            ],
            "usage": {"input_tokens": 2, "output_tokens": 3},
        }
        return httpx.Response(200, json=payload)

    provider = OpenAIProvider(
        model="gpt-5.4",
        api_key=KEY,
        client=_transport(handler),
        owns_client=True,
        root="https://api.openai.com",
        max_output_tokens=128,
    )
    result = provider.complete(system="rules", user="Passage:\nonly")
    assert seen["url"] == "https://api.openai.com/v1/responses"
    assert seen["authorization"] == f"Bearer {KEY}"
    assert seen["body"]["reasoning"] == {"effort": "low"}
    text_format = seen["body"]["text"]["format"]
    assert text_format["strict"] is True
    assert text_format["schema"]["additionalProperties"] is False
    assert result.parsed == {"observations": []}
    assert result.input_tokens == 2


def test_gemini_request_shape_keeps_the_key_out_of_the_url() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["api_key"] = request.headers.get("x-goog-api-key")
        payload = {
            "candidates": [{"content": {"parts": [{"text": '{"observations": []}'}]}}],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 6},
        }
        return httpx.Response(200, json=payload)

    provider = GeminiProvider(
        model="gemini-3.1-pro-preview",
        api_key=KEY,
        client=_transport(handler),
        owns_client=True,
        root="https://generativelanguage.googleapis.com",
        max_output_tokens=128,
    )
    result = provider.complete(system="rules", user="Passage:\nonly")
    assert ":generateContent" in seen["url"]
    assert KEY not in seen["url"]
    assert seen["api_key"] == KEY
    assert seen["body"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}
    schema = seen["body"]["generationConfig"]["responseSchema"]
    assert schema["properties"]["observations"]["items"]["properties"]["activity_type"]["nullable"] is True
    assert result.parsed == {"observations": []}
    assert result.output_tokens == 6


def test_retry_then_provider_error_redacts_the_key() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text=f"overloaded {KEY}")
        return httpx.Response(
            200,
            json={"content": [{"type": "tool_use", "name": "record_observations", "input": {"observations": []}}]},
        )

    provider = AnthropicProvider(
        model="claude-sonnet-4-6",
        api_key=KEY,
        client=_transport(handler),
        owns_client=True,
        root="https://api.anthropic.com",
        max_output_tokens=32,
    )
    result = provider.complete(system="rules", user="Passage:\nonly")
    assert result.attempts == 2
    assert calls["n"] == 2

    def always_fail(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=f"bad gateway token={KEY}")

    failing = AnthropicProvider(
        model="claude-sonnet-4-6",
        api_key=KEY,
        client=_transport(always_fail),
        owns_client=True,
        root="https://api.anthropic.com",
        max_output_tokens=32,
    )
    with pytest.raises(ProviderError) as caught:
        failing.complete(system="rules", user="Passage:\nonly")
    assert caught.value.attempts == 2
    assert KEY not in caught.value.message
    assert "[redacted]" in caught.value.message


def test_timeout_retries_once_and_redacts_the_key() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout(f"timed out {KEY}")

    provider = OpenAIProvider(
        model="gpt-5.4",
        api_key=KEY,
        client=_transport(handler),
        owns_client=True,
        root="https://api.openai.com",
        max_output_tokens=32,
    )
    with pytest.raises(ProviderError) as caught:
        provider.complete(system="rules", user="Passage:\nonly")
    assert calls["n"] == 2
    assert caught.value.attempts == 2
    assert KEY not in caught.value.message
