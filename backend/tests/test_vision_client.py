from __future__ import annotations

from app.ollama_client import OllamaError
from app.vision_client import OpenAIResponsesClient, QwenChatCompletionsClient


def test_openai_output_text_reads_responses_message() -> None:
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"status":"ok"}'}
                ],
            }
        ]
    }
    assert OpenAIResponsesClient._output_text(payload) == '{"status":"ok"}'


def test_openai_strict_schema_closes_objects_and_requires_fields() -> None:
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "default": "unknown"},
            "box": {
                "type": "object",
                "properties": {"x": {"type": "integer"}},
            },
        },
    }
    strict = OpenAIResponsesClient._strict_schema(schema)
    assert strict["additionalProperties"] is False
    assert strict["required"] == ["status", "box"]
    assert "default" not in strict["properties"]["status"]
    assert strict["properties"]["box"]["additionalProperties"] is False
    assert strict["properties"]["box"]["required"] == ["x"]


def test_qwen_payload_sends_ordered_images_and_json_schema(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_MODEL", "qwen3.7-plus-2026-05-26")
    client = QwenChatCompletionsClient()
    payload = client._build_payload(
        prompt="Compare IMAGE 1 and IMAGE 2.",
        schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
        },
        images_base64=["before", "after"],
        max_tokens=512,
    )
    assert payload["model"] == "qwen3.7-plus-2026-05-26"
    assert payload["response_format"] == {"type": "json_object"}
    content = payload["messages"][1]["content"]
    assert content[0]["image_url"]["url"].endswith(",before")
    assert content[1]["image_url"]["url"].endswith(",after")
    assert "OUTPUT JSON SCHEMA" in content[2]["text"]
    assert '"status"' in content[2]["text"]


def test_qwen_message_text_reads_string_and_blocks() -> None:
    assert QwenChatCompletionsClient._message_text(
        {"choices": [{"message": {"content": '{"status":"ok"}'}}]}
    ) == '{"status":"ok"}'


def test_qwen_message_text_accepts_structured_gateway_fallbacks() -> None:
    assert QwenChatCompletionsClient._message_text(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "reasoning_content": 'visual notes\n{"status":"ok"}',
                    }
                }
            ]
        }
    ).endswith('{"status":"ok"}')
    assert QwenChatCompletionsClient._message_text(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {"function": {"arguments": '{"status":"ok"}'}}
                        ],
                    }
                }
            ]
        }
    ) == '{"status":"ok"}'


def test_qwen_empty_content_retries_without_thinking(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("MANUAL2AR_QWEN_ENABLE_THINKING", "true")
    client = QwenChatCompletionsClient()
    payloads: list[dict] = []

    def fake_request(payload: dict) -> dict:
        payloads.append(payload)
        if len(payloads) == 1:
            raise OllamaError("Qwen Chat Completions returned no message content")
        return {"status": "ok"}

    monkeypatch.setattr(client, "_request_and_parse", fake_request)
    result = client.chat_structured(
        prompt="Return status.",
        schema={"type": "object"},
        max_tokens=128,
    )
    assert result == {"status": "ok"}
    assert payloads[0]["enable_thinking"] is True
    assert payloads[1]["enable_thinking"] is False


def test_qwen_empty_response_diagnostics_are_safe() -> None:
    diagnostics = QwenChatCompletionsClient._response_diagnostics(
        {
            "model": "qwen3-vl-flash",
            "choices": [{"finish_reason": "length", "message": {"content": None}}],
            "usage": {"completion_tokens": 640},
        }
    )
    assert "finish_reason=length" in diagnostics
    assert "completion_tokens=640" in diagnostics
    assert "qwen3-vl-flash" in diagnostics
    assert QwenChatCompletionsClient._message_text(
        {
            "choices": [
                {"message": {"content": [{"text": "{\"status\":"}, {"text": "\"ok\"}"}]}}
            ]
        }
    ) == '{"status":"ok"}'
