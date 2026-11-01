from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import llm_utils


def test_provider_and_model_resolution_defaults(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert llm_utils.selected_provider() == "anthropic"
    assert llm_utils.model_for_tier(llm_utils.MODEL_LOW, "anthropic") == "claude-haiku-5-5"
    assert llm_utils.model_for_tier(llm_utils.MODEL_LOW, "openai") == "gpt-6-luna"
    assert llm_utils.model_for_tier(llm_utils.MODEL_MID, "openai") == "gpt-6.1-terra"
    assert llm_utils.resolve_model("gpt-6-luna", "openai") == "gpt-6-luna"
    assert llm_utils.model_for_tier(llm_utils.MODEL_LOW, "gemini") == "gemini-3.8-flash"
    assert llm_utils.model_for_tier(llm_utils.MODEL_MID, "gemini") == "gemini-4-argon"
    assert llm_utils.model_for_tier(llm_utils.MODEL_HIGH, "gemini") == "gemini-4-argon"
    assert llm_utils.model_for_tier(llm_utils.MODEL_HIGH, "openai") == "gpt-6.1-sol"
    assert llm_utils.model_for_tier(llm_utils.MODEL_HIGH, "anthropic") == "claude-opus-5-5"
    assert llm_utils.default_reasoning_effort("anthropic", "high") == "xhigh"
    assert llm_utils.default_reasoning_effort("gemini", "high") == "medium"
    assert llm_utils.resolve_model("claude-opus-4-7", "openai") == "gpt-6.1-sol"
    assert llm_utils.reasoning_effort_options("openai", "gpt-6.1-sol") == ["low", "medium", "high", "xhigh"]
    assert "none" in llm_utils.reasoning_effort_options("openai", "gpt-5.4")
    assert "none" in llm_utils.reasoning_effort_options("openai", "gpt-6-luna")


def test_provider_model_overrides(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL_HIGH", "gpt-custom-high")
    assert llm_utils.model_for_tier(llm_utils.MODEL_HIGH, "openai") == "gpt-custom-high"

    monkeypatch.setenv("GEMINI_MODEL_MID", "gemini-custom-mid")
    assert llm_utils.model_for_tier(llm_utils.MODEL_MID, "gemini") == "gemini-custom-mid"


def test_required_key_validation(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    try:
        llm_utils.require_api_key()
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("missing OpenAI key should fail")

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-proj-wrong")
    try:
        llm_utils.require_api_key()
    except RuntimeError as exc:
        assert "Anthropic key" in str(exc)
    else:
        raise AssertionError("OpenAI key in Anthropic env should fail")

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    try:
        llm_utils.require_api_key()
    except RuntimeError as exc:
        assert "GEMINI_API_KEY" in str(exc)
    else:
        raise AssertionError("missing Gemini key should fail")

    monkeypatch.setenv("LLM_PROVIDER", "local")
    with pytest.raises(ValueError, match="anthropic.*openai.*gemini.*talisman"):
        llm_utils.require_api_key()


def _install_fake_gemini(monkeypatch, fake_client):
    import google

    fake_genai = SimpleNamespace(Client=lambda *args, **kwargs: fake_client)
    monkeypatch.setattr(google, "genai", fake_genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    llm_utils._CLIENT_CACHE.clear()
    llm_utils._CLIENT_FACTORY_CACHE.clear()


def test_anthropic_text_request_shape_and_citations(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    class FakeMessages:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text="answer",
                        citations=[SimpleNamespace(title="Source", url="https://example.com")],
                    )
                ],
                stop_reason="end_turn",
            )

    fake_messages = FakeMessages()

    class FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = fake_messages

    monkeypatch.setattr("anthropic.Anthropic", FakeAnthropic)

    text, citations, _response = llm_utils.call_llm_text(
        prompt="hello",
        model=llm_utils.MODEL_LOW,
        api_key=None,
        max_tokens=123,
        system="system",
        allowed_domains=["example.com"],
        max_web_search_uses=2,
    )

    assert text == "answer"
    assert citations == [("Source", "https://example.com")]
    assert fake_messages.kwargs["model"] == "claude-haiku-5-5"
    assert fake_messages.kwargs["max_tokens"] == 123
    assert fake_messages.kwargs["system"] == "system"
    assert fake_messages.kwargs["tools"] == [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 2,
        }
    ]
    assert "thinking" not in fake_messages.kwargs


def test_anthropic_text_request_can_stream(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    class FakeStream:
        def __init__(self, response):
            self.response = response

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_final_message(self):
            return self.response

    class FakeMessages:
        def __init__(self):
            self.kwargs = None
            self.create_called = False

        def create(self, **kwargs):
            self.create_called = True
            raise AssertionError("streaming calls should not use messages.create")

        def stream(self, **kwargs):
            self.kwargs = kwargs
            return FakeStream(
                SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="streamed answer")],
                    stop_reason="end_turn",
                )
            )

    fake_messages = FakeMessages()

    class FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = fake_messages

    monkeypatch.setattr("anthropic.Anthropic", FakeAnthropic)

    text, citations, _response = llm_utils.call_llm_text(
        prompt="hello",
        model=llm_utils.MODEL_LOW,
        api_key=None,
        max_tokens=24576,
        stream=True,
    )

    assert text == "streamed answer"
    assert citations == []
    assert fake_messages.create_called is False
    assert fake_messages.kwargs["max_tokens"] == 24576


def test_anthropic_long_text_request_streams_automatically(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_final_message(self):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="auto streamed")], stop_reason="end_turn")

    class FakeMessages:
        def __init__(self):
            self.kwargs = None
            self.create_called = False

        def create(self, **kwargs):
            self.create_called = True
            raise AssertionError("long Anthropic requests must not use messages.create")

        def stream(self, **kwargs):
            self.kwargs = kwargs
            return FakeStream()

    fake_messages = FakeMessages()

    class FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = fake_messages

    monkeypatch.setattr("anthropic.Anthropic", FakeAnthropic)

    text, _citations, _response = llm_utils.call_llm_text(
        prompt="hello",
        model=llm_utils.MODEL_HIGH,
        api_key=None,
        max_tokens=24576,
        reasoning_effort=llm_utils.REASONING_HIGH,
    )

    assert text == "auto streamed"
    assert fake_messages.create_called is False
    assert fake_messages.kwargs["model"] == "claude-opus-5-5"
    assert fake_messages.kwargs["max_tokens"] == 64_000
    assert fake_messages.kwargs["thinking"] == {"type": "adaptive", "display": "omitted"}


def test_call_llm_json_injects_schema_for_anthropic(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    class FakeMessages:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"name":"ANET"}')],
                stop_reason="end_turn",
            )

    fake_messages = FakeMessages()

    class FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = fake_messages

    monkeypatch.setattr("anthropic.Anthropic", FakeAnthropic)

    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    parsed, _citations, _response, diagnostics = llm_utils.call_llm_json(
        prompt="return json",
        model=llm_utils.MODEL_LOW,
        max_tokens=128,
        json_schema=schema,
        json_schema_name="test_schema",
    )

    prompt = fake_messages.kwargs["messages"][0]["content"]
    assert parsed == {"name": "ANET"}
    assert diagnostics["status"] == "ok"
    assert "Structured JSON output is required" in prompt
    assert "test_schema" in prompt
    assert '"name"' in prompt


def test_call_llm_json_repairs_invalid_json_once(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    calls = []

    def fake_call_llm_text(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return "not json", [], SimpleNamespace()
        return '{"ok": true}', [], SimpleNamespace()

    monkeypatch.setattr(llm_utils, "call_llm_text", fake_call_llm_text)

    parsed, _citations, _response, diagnostics = llm_utils.call_llm_json(
        prompt="return json",
        model=llm_utils.MODEL_LOW,
        max_tokens=128,
        json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
    )

    assert parsed == {"ok": True}
    assert len(calls) == 2
    assert calls[1]["enable_web_search"] is False
    assert diagnostics["status"] == "repaired"
    assert diagnostics["attempts"] == 2


def test_call_llm_json_retries_provider_error_without_search(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    calls = []

    def fake_call_llm_text(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("schema and search are not compatible")
        return '{"ok": true}', [], SimpleNamespace()

    monkeypatch.setattr(llm_utils, "call_llm_text", fake_call_llm_text)

    parsed, _citations, _response, diagnostics = llm_utils.call_llm_json(
        prompt="return json",
        model=llm_utils.MODEL_LOW,
        max_tokens=128,
        enable_web_search=True,
        json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
    )

    assert parsed == {"ok": True}
    assert len(calls) == 2
    assert calls[0]["enable_web_search"] is True
    assert calls[1]["enable_web_search"] is False
    assert diagnostics["status"] == "ok"
    assert diagnostics["attempts"] == 2
    assert diagnostics["web_search_status"] == "disabled_after_error"


def test_openai_text_request_shape_and_citations(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class FakeResponses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[
                            SimpleNamespace(
                                text="openai answer",
                                annotations=[
                                    SimpleNamespace(
                                        type="url_citation",
                                        title="OpenAI Source",
                                        url="https://example.com/openai",
                                    )
                                ],
                            )
                        ],
                    )
                ]
            )

    fake_responses = FakeResponses()

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.responses = fake_responses

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    text, citations, _response = llm_utils.call_llm_text(
        prompt="hello",
        model=llm_utils.MODEL_LOW,
        api_key=None,
        max_tokens=456,
        system="instructions",
        allowed_domains=["example.com"],
    )

    assert text == "openai answer"
    assert citations == [("OpenAI Source", "https://example.com/openai")]
    assert fake_responses.kwargs["model"] == "gpt-6-luna"
    assert fake_responses.kwargs["max_output_tokens"] == 456
    assert fake_responses.kwargs["instructions"] == "instructions"
    assert fake_responses.kwargs["tools"] == [
        {
            "type": "web_search",
            "search_context_size": "medium",
        }
    ]
    assert "reasoning" not in fake_responses.kwargs


def test_openai_json_schema_is_strictified(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class FakeResponses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(output_text='{"name":"ANET","meta":{"score":1}}')

    fake_responses = FakeResponses()

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.responses = fake_responses

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "default": ""},
            "meta": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "score": {"type": "number", "default": 0},
                    "note": {"type": ["string", "null"]},
                },
            },
        },
        "required": ["name"],
    }

    text, _citations, _response = llm_utils.call_llm_text(
        prompt="json",
        model=llm_utils.MODEL_LOW,
        max_tokens=128,
        json_schema=schema,
        json_schema_name="test_schema",
    )

    assert text == '{"name":"ANET","meta":{"score":1}}'
    response_schema = fake_responses.kwargs["text"]["format"]["schema"]
    assert fake_responses.kwargs["text"]["format"]["strict"] is True
    assert "default" not in str(response_schema)
    assert response_schema["additionalProperties"] is False
    assert response_schema["required"] == ["name", "meta"]
    assert response_schema["properties"]["meta"]["additionalProperties"] is False
    assert response_schema["properties"]["meta"]["required"] == ["score", "note"]


def test_extract_text_reads_parsed_structured_output():
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(
                        type="output_text",
                        parsed={"name": "ANET", "score": 55},
                    )
                ],
            )
        ]
    )

    assert llm_utils.extract_text(response) == '{"name": "ANET", "score": 55}'


def test_gemini_text_request_shape_reasoning_and_citations(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-key-12345678901234567890")

    class FakeModels:
        def __init__(self):
            self.kwargs = None

        def generate_content(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                text="gemini answer",
                candidates=[
                    SimpleNamespace(
                        grounding_metadata=SimpleNamespace(
                            grounding_chunks=[
                                SimpleNamespace(web=SimpleNamespace(title="Gemini Source", uri="https://example.com/g"))
                            ]
                        )
                    )
                ],
            )

    fake_models = FakeModels()
    _install_fake_gemini(monkeypatch, SimpleNamespace(models=fake_models))

    text, citations, _response = llm_utils.call_llm_text(
        prompt="hello",
        model=llm_utils.MODEL_MID,
        api_key=None,
        max_tokens=789,
        system="system",
        reasoning_effort=llm_utils.REASONING_HIGH,
    )

    assert text == "gemini answer"
    assert citations == [("Gemini Source", "https://example.com/g")]
    assert fake_models.kwargs["model"] == "gemini-4-argon"
    assert fake_models.kwargs["contents"] == [{"role": "user", "parts": [{"text": "hello"}]}]
    assert fake_models.kwargs["config"] == {
        "max_output_tokens": 789,
        "system_instruction": "system",
        "thinking_config": {"thinking_level": "high"},
    }


def test_gemini_allowed_domains_enable_unrestricted_search(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-key-12345678901234567890")

    class FakeModels:
        def __init__(self):
            self.kwargs = None

        def generate_content(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(text="grounded")

    fake_models = FakeModels()
    _install_fake_gemini(monkeypatch, SimpleNamespace(models=fake_models))

    text, _citations, _response = llm_utils.call_llm_text(
        prompt="latest",
        model=llm_utils.MODEL_LOW,
        allowed_domains=["example.com"],
        max_tokens=128,
    )

    assert text == "grounded"
    assert fake_models.kwargs["config"]["tools"] == [{"google_search": {}}]


def test_gemini_json_schema_removes_unsupported_additional_properties(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-key-12345678901234567890")

    class FakeModels:
        def __init__(self):
            self.kwargs = None

        def generate_content(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(text='{"name":"ANET","meta":{"score":1}}')

    fake_models = FakeModels()
    _install_fake_gemini(monkeypatch, SimpleNamespace(models=fake_models))

    schema = {
        "type": "object",
        "additionalProperties": False,
        "$defs": {
            "Meta": {
                "title": "Meta",
                "type": "object",
                "additionalProperties": True,
                "properties": {"score": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": None}},
            }
        },
        "properties": {
            "name": {"type": ["string", "null"]},
            "meta": {"$ref": "#/$defs/Meta"},
        },
        "required": ["name", "meta"],
    }

    text, _citations, _response = llm_utils.call_llm_text(
        prompt="json",
        model=llm_utils.MODEL_LOW,
        max_tokens=128,
        json_schema=schema,
    )

    assert text == '{"name":"ANET","meta":{"score":1}}'
    response_schema = fake_models.kwargs["config"]["response_schema"]
    assert fake_models.kwargs["config"]["response_mime_type"] == "application/json"
    assert "additionalProperties" not in str(response_schema)
    assert "$defs" not in response_schema
    assert response_schema["properties"]["name"] == {"type": "string", "nullable": True}
    assert response_schema["properties"]["meta"]["properties"]["score"] == {"type": "number", "nullable": True}


def test_openai_reasoning_effort_request_shape(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class FakeResponses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(output_text="reasoned")

    fake_responses = FakeResponses()

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.responses = fake_responses

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    text, _citations, _response = llm_utils.call_llm_text(
        prompt="hello",
        model=llm_utils.MODEL_HIGH,
        api_key=None,
        max_tokens=456,
        reasoning_effort=llm_utils.REASONING_XHIGH,
    )

    assert text == "reasoned"
    assert fake_responses.kwargs["model"] == "gpt-6.1-sol"
    assert fake_responses.kwargs["reasoning"] == {"effort": "xhigh"}


def test_openai_none_reasoning_effort_request_shape(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class FakeResponses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(output_text="fast")

    fake_responses = FakeResponses()

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.responses = fake_responses

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    text, _citations, _response = llm_utils.call_llm_text(
        prompt="hello",
        model=llm_utils.MODEL_MID,
        api_key=None,
        max_tokens=456,
        reasoning_effort=llm_utils.REASONING_NONE,
    )

    assert text == "fast"
    assert fake_responses.kwargs["model"] == "gpt-6.1-terra"
    assert fake_responses.kwargs["reasoning"] == {"effort": "none"}


def test_gpt_61_sol_rejects_none_and_minimal_reasoning():
    kwargs: dict[str, object] = {}
    with pytest.raises(ValueError, match="reasoning_effort"):
        llm_utils.apply_reasoning_config(
            kwargs,
            provider="openai",
            model="gpt-6.1-sol",
            max_tokens=64,
            reasoning_effort="none",
        )
    with pytest.raises(ValueError, match="reasoning_effort"):
        llm_utils.apply_reasoning_config(
            kwargs,
            provider="openai",
            model="gpt-6.1-sol",
            max_tokens=64,
            reasoning_effort="minimal",
        )

    llm_utils.apply_reasoning_config(
        kwargs,
        provider="openai",
        model="gpt-5.4",
        max_tokens=64,
        reasoning_effort="none",
    )
    assert kwargs["reasoning"] == {"effort": "none"}


def test_anthropic_adaptive_thinking_request_shape(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    class FakeMessages:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="reasoned")], stop_reason="end_turn")

    fake_messages = FakeMessages()

    class FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = fake_messages

    monkeypatch.setattr("anthropic.Anthropic", FakeAnthropic)

    text, _citations, _response = llm_utils.call_llm_text(
        prompt="hello",
        model=llm_utils.MODEL_MID,
        api_key=None,
        max_tokens=4096,
        reasoning_effort=llm_utils.REASONING_HIGH,
    )

    assert text == "reasoned"
    assert fake_messages.kwargs["model"] == "claude-sonnet-5-5"
    assert fake_messages.kwargs["thinking"] == {"type": "adaptive", "display": "omitted"}
    assert fake_messages.kwargs["output_config"] == {"effort": "high"}


def test_anthropic_opus_5_5_uses_adaptive_thinking(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_final_message(self):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="reasoned")], stop_reason="end_turn")

    class FakeMessages:
        def __init__(self):
            self.kwargs = None
            self.create_called = False

        def create(self, **kwargs):
            self.create_called = True
            raise AssertionError("Opus 5.5 requests must stream")

        def stream(self, **kwargs):
            self.kwargs = kwargs
            return FakeStream()

    fake_messages = FakeMessages()

    class FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = fake_messages

    monkeypatch.setattr("anthropic.Anthropic", FakeAnthropic)

    text, _citations, _response = llm_utils.call_llm_text(
        prompt="hello",
        model=llm_utils.MODEL_HIGH,
        api_key=None,
        max_tokens=4096,
        reasoning_effort=llm_utils.REASONING_XHIGH,
    )

    assert text == "reasoned"
    assert fake_messages.create_called is False
    assert fake_messages.kwargs["model"] == "claude-opus-5-5"
    assert fake_messages.kwargs["max_tokens"] == 64_000
    assert fake_messages.kwargs["thinking"] == {"type": "adaptive", "display": "omitted"}
    assert "budget_tokens" not in fake_messages.kwargs["thinking"]
    assert fake_messages.kwargs["output_config"] == {"effort": "xhigh"}


@pytest.mark.parametrize("summarize", [False, True])
@pytest.mark.parametrize("effort", ["medium", "xhigh", "max"])
def test_haiku_5_5_uses_adaptive_thinking(summarize, effort):
    kwargs = {}

    llm_utils.apply_reasoning_config(
        kwargs,
        provider="anthropic",
        model="claude-haiku-5-5",
        max_tokens=4096,
        reasoning_effort=effort,
        summarize=summarize,
    )

    assert kwargs["thinking"] == {"type": "adaptive", "display": "summarized" if summarize else "omitted"}
    assert kwargs["output_config"] == {"effort": effort}


def test_gemini_3_8_flash_rejects_minimal_reasoning():
    assert llm_utils.reasoning_effort_options("gemini", "gemini-3.8-flash") == ["low", "medium", "high"]
    assert "minimal" in llm_utils.reasoning_effort_options("gemini", "gemini-3.1-flash-lite")
    with pytest.raises(ValueError, match="reasoning_effort"):
        llm_utils.apply_reasoning_config(
            {}, provider="gemini", model="gemini-3.8-flash", max_tokens=4096, reasoning_effort="minimal"
        )


def test_anthropic_manual_thinking_request_shape(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL_LOW", "claude-haiku-4-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    class FakeMessages:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="reasoned")], stop_reason="end_turn")

    fake_messages = FakeMessages()

    class FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = fake_messages

    monkeypatch.setattr("anthropic.Anthropic", FakeAnthropic)

    text, _citations, _response = llm_utils.call_llm_text(
        prompt="hello",
        model=llm_utils.MODEL_LOW,
        api_key=None,
        max_tokens=4096,
        reasoning_effort=llm_utils.REASONING_HIGH,
    )

    assert text == "reasoned"
    assert fake_messages.kwargs["model"] == "claude-haiku-4-5"
    assert fake_messages.kwargs["thinking"] == {
        "type": "enabled",
        "budget_tokens": 2048,
        "display": "omitted",
    }
    assert fake_messages.kwargs["output_config"] == {"effort": "high"}


def test_pdf_input_shapes(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class FakeResponses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(output_text="pdf answer")

    fake_responses = FakeResponses()

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.responses = fake_responses

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    text, _citations, _response = llm_utils.call_llm_pdf_text(
        pdf_bytes=b"%PDF-test",
        prompt="read",
        model=llm_utils.MODEL_MID,
        api_key=None,
        system="system",
        filename="deck.pdf",
    )

    assert text == "pdf answer"
    content = fake_responses.kwargs["input"][0]["content"]
    assert content[0]["type"] == "input_file"
    assert content[0]["filename"] == "deck.pdf"
    assert content[0]["file_data"].startswith("data:application/pdf;base64,")
    assert content[1] == {"type": "input_text", "text": "read"}


def test_gemini_pdf_input_shape(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-key-12345678901234567890")

    class FakeModels:
        def __init__(self):
            self.kwargs = None

        def generate_content(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(text="pdf answer")

    fake_models = FakeModels()
    _install_fake_gemini(monkeypatch, SimpleNamespace(models=fake_models))

    text, _citations, _response = llm_utils.call_llm_pdf_text(
        pdf_bytes=b"%PDF-test",
        prompt="read",
        model=llm_utils.MODEL_LOW,
        api_key=None,
        system="system",
        filename="deck.pdf",
        reasoning_effort=llm_utils.REASONING_LOW,
    )

    assert text == "pdf answer"
    assert fake_models.kwargs["model"] == "gemini-3.8-flash"
    assert fake_models.kwargs["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "application/pdf"
    assert fake_models.kwargs["contents"][0]["parts"][0]["inline_data"]["data"].startswith("JVBERi10ZXN0")
    assert fake_models.kwargs["contents"][0]["parts"][1] == {"text": "read"}
    assert fake_models.kwargs["config"]["thinking_config"] == {"thinking_level": "low"}


def test_json_cache_key_survives_repair_and_reaches_openai_transport(monkeypatch):
    calls = []
    responses = iter(["not JSON", '{"ok":true}'])

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text=next(responses))

    monkeypatch.setattr(
        llm_utils, "get_llm_client", lambda *args, **kwargs: SimpleNamespace(responses=SimpleNamespace(create=create))
    )
    parsed, _, _, diagnostics = llm_utils.call_llm_json(
        prompt="return JSON", model=llm_utils.MODEL_MID, provider="openai", prompt_cache_key="session-key"
    )
    assert parsed == {"ok": True}
    assert diagnostics["status"] == "repaired"
    assert len(calls) == 2
    assert all(call["prompt_cache_key"] == "session-key" for call in calls)


def test_default_openai_calls_do_not_add_a_cache_key(monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text="Ready")

    monkeypatch.setattr(
        llm_utils, "get_llm_client", lambda *args, **kwargs: SimpleNamespace(responses=SimpleNamespace(create=create))
    )
    llm_utils.call_llm_text(prompt="hello", model=llm_utils.MODEL_MID, provider="openai")
    assert "prompt_cache_key" not in calls[0]


@pytest.mark.parametrize(
    ("provider", "model", "summarized", "plain"),
    [
        (
            "anthropic",
            "claude-opus-5-5",
            {"thinking": {"type": "adaptive", "display": "summarized"}},
            {"thinking": {"type": "adaptive", "display": "omitted"}},
        ),
        (
            "anthropic",
            "claude-sonnet-4-5",
            {"thinking": {"type": "enabled", "budget_tokens": 4096, "display": "summarized"}},
            {"thinking": {"type": "enabled", "budget_tokens": 4096, "display": "omitted"}},
        ),
        (
            "openai",
            "gpt-5.4",
            {"reasoning": {"effort": "medium", "summary": "auto"}},
            {"reasoning": {"effort": "medium"}},
        ),
        (
            "gemini",
            "gemini-4-argon",
            {"config": {"thinking_config": {"thinking_level": "medium", "include_thoughts": True}}},
            {"config": {"thinking_config": {"thinking_level": "medium"}}},
        ),
    ],
)
def test_reasoning_config_asks_for_a_thinking_summary_only_when_told_to(provider, model, summarized, plain):
    for summarize, expected in ((True, summarized), (False, plain)):
        kwargs: dict = {}
        llm_utils.apply_reasoning_config(
            kwargs,
            provider=provider,
            model=model,
            max_tokens=8192,
            reasoning_effort="medium",
            summarize=summarize,
        )
        assert {key: kwargs[key] for key in expected} == expected
