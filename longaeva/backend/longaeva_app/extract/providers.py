"""LLM provider adapters for passage extraction (LON-16).

Three httpx adapters follow Talisman's provider call shapes (Anthropic Messages
with a forced tool, OpenAI Responses with a strict JSON schema, Gemini
generateContent with a response schema). Nothing here imports Talisman.
``build_provider`` returns None before constructing a client when extraction
is disabled.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from longaeva_app.config import Settings
from longaeva_app.extract.prompts import PROMPT_VERSION
from longaeva_app.extract.schemas import (
    extraction_json_schema,
    gemini_response_schema,
    openai_strict_schema,
)

ANTHROPIC_ROOT = "https://api.anthropic.com"
OPENAI_ROOT = "https://api.openai.com"
GEMINI_ROOT = "https://generativelanguage.googleapis.com"
ANTHROPIC_VERSION = "2023-06-01"
TOOL_NAME = "record_observations"
KNOWN_PROVIDERS = ("anthropic", "openai", "gemini", "stub")
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-5.4",
    "gemini": "gemini-3.1-pro-preview",
    "stub": "stub-v1",
}
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class ProviderError(Exception):
    """The provider call failed after retries. The API key is not in ``message``."""

    def __init__(self, message: str, *, attempts: int, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.attempts = attempts
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ProviderResult:
    text: str
    parsed: dict[str, Any] | None
    input_tokens: int | None
    output_tokens: int | None
    attempts: int
    refusal: str | None = None
    incomplete: bool = False


@dataclass(frozen=True, slots=True)
class ExtractionStatus:
    enabled: bool
    provider: str
    model: str
    configured_providers: list[str]
    disabled_reason: str | None
    max_passages: int
    max_passage_chars: int
    prompt_version: str


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, *, system: str, user: str) -> ProviderResult: ...

    def close(self) -> None: ...


class StubProvider:
    """Canned responses for tests. ``complete`` does not touch the network."""

    name = "stub"

    def __init__(self, responses: list[str] | None = None, *, model: str = "stub-v1") -> None:
        self.model = model
        self._responses = list(responses or ['{"observations": []}'])
        self.calls = 0
        self.seen: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> ProviderResult:
        self.calls += 1
        self.seen.append((system, user))
        text = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        return ProviderResult(
            text=text,
            parsed=parse_json_object(text),
            input_tokens=1,
            output_tokens=1,
            attempts=1,
        )

    def close(self) -> None:
        return None


class _HttpProvider:
    name = ""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        client: httpx.Client,
        owns_client: bool,
        root: str,
        max_output_tokens: int,
        response_schema: dict[str, Any] | None = None,
        schema_name: str = "extraction",
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._client = client
        self._owns_client = owns_client
        self._root = root.rstrip("/")
        self._max_output_tokens = max_output_tokens
        self._response_schema = response_schema if response_schema is not None else extraction_json_schema()
        self._schema_name = schema_name

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _post(
        self, url: str, *, headers: dict[str, str], body: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str, int]:
        response, attempts = _post_with_retry(
            self._client,
            url,
            headers=headers,
            body=body,
            secrets=[self._api_key],
        )
        text = response.text
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return None, text, attempts
        if not isinstance(payload, dict):
            return None, text, attempts
        return payload, text, attempts


class AnthropicProvider(_HttpProvider):
    name = "anthropic"

    def complete(self, *, system: str, user: str) -> ProviderResult:
        schema = openai_strict_schema(self._response_schema)
        tool_name = TOOL_NAME if self._schema_name == "extraction" else self._schema_name
        body = {
            "model": self.model,
            "max_tokens": self._max_output_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": tool_name,
                    "description": "Record observations stated in the supplied passage.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": tool_name},
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        payload, text, attempts = self._post(f"{self._root}/v1/messages", headers=headers, body=body)
        parsed, raw = _anthropic_parsed(payload, text)
        usage = payload.get("usage") if isinstance(payload, dict) else None
        return ProviderResult(
            text=raw,
            parsed=parsed,
            input_tokens=_int_or_none(usage, "input_tokens"),
            output_tokens=_int_or_none(usage, "output_tokens"),
            attempts=attempts,
        )


class OpenAIProvider(_HttpProvider):
    name = "openai"

    def complete(self, *, system: str, user: str) -> ProviderResult:
        schema = openai_strict_schema(self._response_schema)
        body: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": self._max_output_tokens,
            "reasoning": {"effort": "low"},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": self._schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        headers = {
            "authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }
        payload, text, attempts = self._post(f"{self._root}/v1/responses", headers=headers, body=body)
        raw = _openai_text(payload) if payload is not None else text
        usage = payload.get("usage") if isinstance(payload, dict) else None
        return ProviderResult(
            text=raw or text,
            parsed=parse_json_object(raw),
            input_tokens=_int_or_none(usage, "input_tokens"),
            output_tokens=_int_or_none(usage, "output_tokens"),
            attempts=attempts,
            refusal=_openai_refusal(payload),
            incomplete=isinstance(payload, dict) and payload.get("status") == "incomplete",
        )


class GeminiProvider(_HttpProvider):
    name = "gemini"

    def complete(self, *, system: str, user: str) -> ProviderResult:
        schema = gemini_response_schema(self._response_schema)
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "maxOutputTokens": self._max_output_tokens,
                "responseMimeType": "application/json",
                "responseSchema": schema,
                # Gemini 3 spends the output budget on thoughts unless this is set,
                # which truncates the JSON. Low matches Talisman's reasoning default.
                "thinkingConfig": {"thinkingLevel": "LOW"},
            },
        }
        headers = {
            "x-goog-api-key": self._api_key,
            "content-type": "application/json",
        }
        model = quote(self.model, safe="")
        url = f"{self._root}/v1beta/models/{model}:generateContent"
        payload, text, attempts = self._post(url, headers=headers, body=body)
        raw = _gemini_text(payload) if payload is not None else text
        usage = payload.get("usageMetadata") if isinstance(payload, dict) else None
        return ProviderResult(
            text=raw or text,
            parsed=parse_json_object(raw),
            input_tokens=_int_or_none(usage, "promptTokenCount"),
            output_tokens=_int_or_none(usage, "candidatesTokenCount"),
            attempts=attempts,
        )


def describe_extraction(
    settings: Settings,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> ExtractionStatus:
    """Say whether a provider can be called, without creating an HTTP client."""
    requested = (settings.llm_provider if provider is None else provider).strip().lower()
    reason: str | None = None
    resolved_model = ""
    enabled = False
    if not requested:
        reason = "LLM_PROVIDER is unset. Fresh extraction is disabled until a provider is configured."
    elif requested not in KNOWN_PROVIDERS:
        reason = f"Unknown LLM provider {requested!r}. Expected one of: {', '.join(KNOWN_PROVIDERS)}."
    elif requested != "stub" and not _provider_key(settings, requested):
        reason = f"{requested} API key is unset."
    else:
        enabled = True
        resolved_model = resolve_model(settings, requested, model)
    return ExtractionStatus(
        enabled=enabled,
        provider=requested,
        model=resolved_model,
        configured_providers=configured_provider_names(settings),
        disabled_reason=reason,
        max_passages=settings.extraction_max_passages,
        max_passage_chars=settings.extraction_max_passage_chars,
        prompt_version=PROMPT_VERSION,
    )


def configured_provider_names(settings: Settings) -> list[str]:
    found = [name for name in ("anthropic", "openai", "gemini") if _provider_key(settings, name)]
    if settings.llm_provider.strip().lower() == "stub":
        found.append("stub")
    return found


def resolve_model(settings: Settings, provider_name: str, model: str | None) -> str:
    if model and model.strip():
        return model.strip()
    if settings.llm_model.strip():
        return settings.llm_model.strip()
    return DEFAULT_MODELS[provider_name]


def build_provider(
    settings: Settings,
    *,
    provider: str | None = None,
    model: str | None = None,
    client: httpx.Client | None = None,
    response_schema: dict[str, Any] | None = None,
    schema_name: str = "extraction",
) -> LLMProvider | None:
    """Return a provider, or None before any client is constructed when disabled."""
    status = describe_extraction(settings, provider=provider, model=model)
    if not status.enabled:
        return None
    if status.provider == "stub":
        return StubProvider(model=status.model)
    owns_client = client is None
    http = client if client is not None else httpx.Client(timeout=httpx.Timeout(settings.llm_timeout_sec))
    key = _provider_key(settings, status.provider)
    root = _root(settings, status.provider)
    if status.provider == "anthropic":
        return AnthropicProvider(
            model=status.model,
            api_key=key,
            client=http,
            owns_client=owns_client,
            root=root,
            max_output_tokens=settings.llm_max_output_tokens,
            response_schema=response_schema,
            schema_name=schema_name,
        )
    if status.provider == "openai":
        return OpenAIProvider(
            model=status.model,
            api_key=key,
            client=http,
            owns_client=owns_client,
            root=root,
            max_output_tokens=settings.llm_max_output_tokens,
            response_schema=response_schema,
            schema_name=schema_name,
        )
    return GeminiProvider(
        model=status.model,
        api_key=key,
        client=http,
        owns_client=owns_client,
        root=root,
        max_output_tokens=settings.llm_max_output_tokens,
        response_schema=response_schema,
        schema_name=schema_name,
    )


def parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if isinstance(value, dict):
        return value
    return None


def redact(text: str, secrets: list[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    if len(redacted) > 2000:
        return redacted[:2000]
    return redacted


def _provider_key(settings: Settings, provider_name: str) -> str:
    if provider_name == "anthropic":
        return settings.anthropic_api_key.get_secret_value().strip()
    if provider_name == "openai":
        return settings.openai_api_key.get_secret_value().strip()
    if provider_name == "gemini":
        return settings.gemini_api_key.get_secret_value().strip()
    return ""


def _root(settings: Settings, provider_name: str) -> str:
    override = settings.llm_base_url.strip().rstrip("/")
    if override:
        return override
    if provider_name == "anthropic":
        return ANTHROPIC_ROOT
    if provider_name == "openai":
        return OPENAI_ROOT
    return GEMINI_ROOT


def _post_with_retry(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any],
    secrets: list[str],
) -> tuple[httpx.Response, int]:
    attempts = 0
    last_error = "provider request failed"
    while attempts < 2:
        attempts += 1
        try:
            response = client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            last_error = redact(str(exc), secrets)
            if attempts == 1:
                continue
            raise ProviderError(last_error, attempts=attempts) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(redact(str(exc), secrets), attempts=attempts) from exc
        if response.status_code in _RETRYABLE_STATUS and attempts == 1:
            last_error = redact(response.text, secrets)
            continue
        if response.status_code >= 400:
            raise ProviderError(
                redact(response.text, secrets),
                attempts=attempts,
                status_code=response.status_code,
            )
        return response, attempts
    raise ProviderError(last_error, attempts=attempts)


def _anthropic_parsed(payload: dict[str, Any] | None, fallback: str) -> tuple[dict[str, Any] | None, str]:
    if payload is None:
        return parse_json_object(fallback), fallback
    blocks = payload.get("content")
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_input = block.get("input")
            if isinstance(tool_input, dict):
                return tool_input, json.dumps(tool_input, sort_keys=True)
        texts = [
            str(block.get("text") or "") for block in blocks if isinstance(block, dict) and block.get("type") == "text"
        ]
        if texts:
            raw = "\n".join(texts)
            return parse_json_object(raw), raw
    return parse_json_object(fallback), fallback


def _openai_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    chunks: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                    chunks.append(str(part.get("text") or ""))
    return "".join(chunks)


def _openai_refusal(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    for item in payload.get("output", []):
        if isinstance(item, dict):
            for part in item.get("content", []):
                if isinstance(part, dict) and part.get("type") == "refusal":
                    return str(part.get("refusal") or "Provider refused the forecast")
    return None


def _gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0]
    if not isinstance(first, dict):
        return ""
    content = first.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    return "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))


def _int_or_none(usage: object, key: str) -> int | None:
    if not isinstance(usage, dict):
        return None
    value = usage.get(key)
    if isinstance(value, int):
        return value
    return None
