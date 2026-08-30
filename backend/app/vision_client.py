from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from copy import deepcopy
from typing import Any

from .ollama_client import OllamaClient, OllamaError


class OpenAIResponsesClient:
    """Structured multimodal client using the official Responses API."""

    def __init__(self) -> None:
        self.base_url = os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        ).rstrip("/")
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.6")
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.timeout_seconds = int(
            os.getenv("MANUAL2AR_OPENAI_TIMEOUT_SECONDS", "180")
        )

    def chat_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        images_base64: list[str] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise OllamaError(
                "OPENAI_API_KEY is missing; GPT vision is not available"
            )
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": prompt}
        ]
        for encoded in images_base64 or []:
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{encoded}",
                    "detail": "high",
                }
            )
        payload = {
            "model": self.model,
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "manual2ar_result",
                    "schema": self._strict_schema(schema),
                    "strict": True,
                }
            },
            "max_output_tokens": max_tokens,
        }
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:600]
            raise OllamaError(
                f"OpenAI Responses API returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OllamaError(f"OpenAI Responses API request failed: {exc}") from exc

        text = self._output_text(response_payload)
        if not text:
            raise OllamaError("OpenAI Responses API returned no output_text")
        return OllamaClient._extract_json_content(text)

    @staticmethod
    def _output_text(payload: dict[str, Any]) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        for item in payload.get("output", []):
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if not isinstance(content, dict):
                    continue
                if content.get("type") == "output_text":
                    value = content.get("text")
                    if isinstance(value, str) and value.strip():
                        return value
        return ""

    @classmethod
    def _strict_schema(cls, schema: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(schema)

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                # Structured Outputs supports a JSON Schema subset. Pydantic
                # emits `default` for optional fields, but the Responses API
                # rejects that keyword in strict mode.
                node.pop("default", None)
                properties = node.get("properties")
                if node.get("type") == "object" and isinstance(properties, dict):
                    node["additionalProperties"] = False
                    node["required"] = list(properties)
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(result)
        return result


class QwenChatCompletionsClient:
    """Structured multimodal client for Alibaba Cloud Model Studio.

    Model Studio exposes an OpenAI-compatible Chat Completions endpoint.  JSON
    mode guarantees a parseable object, while the requested Pydantic schema is
    also included in the prompt because JSON mode alone does not enforce field
    names or enum values.
    """

    def __init__(self) -> None:
        self.base_url = os.getenv("DASHSCOPE_BASE_URL", "").strip().rstrip("/")
        # This client always receives images for localization and verification.
        # Keep a vision-language model as the fallback instead of silently
        # defaulting to a general text/reasoning model.
        self.model = os.getenv("DASHSCOPE_MODEL", "qwen3-vl-flash").strip()
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        self.timeout_seconds = int(
            os.getenv("MANUAL2AR_QWEN_TIMEOUT_SECONDS", "180")
        )
        self.enable_thinking = os.getenv(
            "MANUAL2AR_QWEN_ENABLE_THINKING", "false"
        ).strip().lower() in {"1", "true", "yes", "on"}

    def chat_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        images_base64: list[str] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise OllamaError(
                "DASHSCOPE_API_KEY is missing; Qwen vision is not available"
            )
        if not self.base_url:
            raise OllamaError(
                "DASHSCOPE_BASE_URL is missing; copy the OpenAI-compatible "
                "Beijing workspace URL from Alibaba Cloud Model Studio"
            )

        images = images_base64 or []
        last_error: Exception | None = None
        for attempt in range(3):
            attempt_prompt = prompt if attempt == 0 else (
                prompt
                + "\nThe previous response was empty, truncated, or invalid. "
                "Return one compact JSON object only. Do not include analysis, "
                "markdown, or prose outside the JSON object. Keep evidence and "
                "next_action concise."
            )
            payload = self._build_payload(
                prompt=attempt_prompt,
                schema=schema,
                images_base64=images,
                max_tokens=max(max_tokens, 1024) if attempt else max_tokens,
                # Structured visual checks need the final JSON, not a long
                # reasoning trace.  A retry always disables thinking because
                # Model Studio can otherwise return reasoning tokens with an
                # empty final message.content.
                enable_thinking=False if attempt else self.enable_thinking,
            )
            try:
                return self._request_and_parse(payload)
            except OllamaError as exc:
                if not self._is_retryable_error(exc) or attempt >= 2:
                    raise
                last_error = exc
        raise OllamaError(
            f"Qwen returned no usable structured result after retries: {last_error}"
        )

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        message = str(exc).lower()
        retryable_markers = (
            "no message content",
            "invalid or truncated json",
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "timed out",
            "temporarily unavailable",
            "connection reset",
        )
        return any(marker in message for marker in retryable_markers)

    def _request_and_parse(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:600]
            raise OllamaError(
                f"Qwen Chat Completions API returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OllamaError(f"Qwen Chat Completions request failed: {exc}") from exc

        text = self._message_text(response_payload)
        if not text:
            raise OllamaError(
                "Qwen Chat Completions returned no message content "
                f"({self._response_diagnostics(response_payload)})"
            )
        return OllamaClient._extract_json_content(text)

    def _build_payload(
        self,
        prompt: str,
        schema: dict[str, Any],
        images_base64: list[str],
        max_tokens: int,
        enable_thinking: bool | None = None,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        for encoded in images_base64:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{encoded}",
                    },
                }
            )
        schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        content.append(
            {
                "type": "text",
                "text": (
                    f"{prompt}\n\nOUTPUT JSON SCHEMA:\n{schema_text}\n"
                    "Return exactly one valid JSON object."
                ),
            }
        )
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the conservative visual evidence engine for "
                        "Manual2AR. Follow the requested JSON schema exactly, "
                        "do not invent hidden equipment state, and use uncertain "
                        "when the visual evidence is insufficient."
                    ),
                },
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
            "enable_thinking": (
                self.enable_thinking
                if enable_thinking is None
                else enable_thinking
            ),
            "max_tokens": max_tokens,
        }

    @staticmethod
    def _message_text(payload: dict[str, Any]) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        message = first.get("message")
        if not isinstance(message, dict):
            legacy_text = first.get("text")
            return legacy_text if isinstance(legacy_text, str) else ""
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            joined = "".join(parts)
            if joined.strip():
                return joined

        # Some OpenAI-compatible gateways put a structured final object in
        # reasoning_content when content is null.  Accept it only when it
        # visibly contains JSON; never surface an unrestricted reasoning trace.
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str) and "{" in reasoning and "}" in reasoning:
            return reasoning

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                function = call.get("function")
                if not isinstance(function, dict):
                    continue
                arguments = function.get("arguments")
                if isinstance(arguments, str) and arguments.strip():
                    return arguments
        return ""

    @staticmethod
    def _response_diagnostics(payload: dict[str, Any]) -> str:
        """Return safe metadata only; never include prompts, images, or secrets."""
        choices = payload.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else {}
        finish_reason = first.get("finish_reason") if isinstance(first, dict) else None
        usage = payload.get("usage")
        completion_tokens = None
        if isinstance(usage, dict):
            completion_tokens = usage.get("completion_tokens")
        return (
            f"finish_reason={finish_reason or 'missing'}, "
            f"completion_tokens={completion_tokens if completion_tokens is not None else 'missing'}, "
            f"model={payload.get('model') or 'missing'}"
        )


class VisionClient:
    """Provider switch that preserves the existing backend call contract."""

    def __init__(self) -> None:
        requested = os.getenv(
            "MANUAL2AR_VISION_PROVIDER", "qwen"
        ).strip().lower()
        if requested not in {"ollama", "openai", "qwen"}:
            raise ValueError(
                "MANUAL2AR_VISION_PROVIDER must be ollama, openai, or qwen"
            )
        self.provider = requested
        if requested == "openai":
            self._client = OpenAIResponsesClient()
        elif requested == "qwen":
            self._client = QwenChatCompletionsClient()
        else:
            self._client = OllamaClient()
        self.base_url = self._client.base_url
        self.model = self._client.model

    def chat_structured(self, **kwargs: Any) -> dict[str, Any]:
        return self._client.chat_structured(**kwargs)

    def configuration_status(self) -> tuple[bool, str | None]:
        """Report credential/config readiness without exposing any secret."""
        if self.provider == "qwen":
            if not getattr(self._client, "api_key", ""):
                return False, "DASHSCOPE_API_KEY is not loaded"
            if not self.base_url:
                return False, "DASHSCOPE_BASE_URL is not configured"
        elif self.provider == "openai":
            if not getattr(self._client, "api_key", ""):
                return False, "OPENAI_API_KEY is not loaded"
        return True, None
