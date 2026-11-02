"""File-configured Qwen structured vision client; no provider globals or environment credentials."""
from __future__ import annotations
import json,re
import urllib.error
import urllib.request
from copy import deepcopy
from typing import Any
from manual2ar.infrastructure.network import MODES, local_proxy, trust_environment

class VisionError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        text = message.lower()
        self.code = code or ('credentials' if 'http 401' in text or 'http 403' in text else
                             'rate_limited' if 'http 429' in text else
                             'upstream' if any('http '+str(code) in text for code in (500,502,503,504)) else
                             'timeout' if 'timed out' in text else
                             'network' if 'request failed' in text else
                             'invalid_response')

def extract_json_content(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline >= 0:
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()

    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start < 0:
            raise VisionError(
                "Vision returned content without a JSON object"
            )
        try:
            value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        except json.JSONDecodeError as exc:
            raise VisionError(
                "Vision returned invalid or truncated JSON content"
            ) from exc

    if not isinstance(value, dict):
        raise VisionError("Vision structured response was not a JSON object")
    return value

class QwenChatCompletionsClient:
    """Structured multimodal client for the configured Qwen-compatible endpoint.

    Model Studio exposes an OpenAI-compatible Chat Completions endpoint.  JSON
    mode guarantees a parseable object, while the requested Pydantic schema is
    also included in the prompt because JSON mode alone does not enforce field
    names or enum values.
    """

    def __init__(self, settings: dict) -> None:
        self.base_url=settings['base_url'].strip().rstrip('/')
        self.model=settings['model']
        self.api_key=settings['api_key'].strip()
        self.timeout_seconds=settings['timeout_seconds']
        self.enable_thinking=settings.get('enable_thinking',False)
        self.temperature=settings.get('temperature',0)
        self.proxy_mode=settings.get('proxy_mode','system')
        if self.proxy_mode not in MODES:raise ValueError('Invalid vlm.proxy_mode')

    def chat_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        images_base64: list[str] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise VisionError(
                "Fill vlm.api_key in configs/app.local.json"
            )
        if not self.base_url:
            raise VisionError(
                "vlm.base_url is missing; copy the OpenAI-compatible "
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
            except VisionError as exc:
                if not self._is_retryable_error(exc) or attempt >= 2:
                    raise
                last_error = exc
        raise VisionError(
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
            "connection refused",
            "unexpected_eof",
            "eof occurred in violation",
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
            use_environment=trust_environment(request.full_url,self.proxy_mode)
            open_request=urllib.request.urlopen if use_environment else urllib.request.build_opener(urllib.request.ProxyHandler({})).open
            try:
                response=open_request(request,timeout=self.timeout_seconds)
            except urllib.error.URLError as error:
                # A desktop proxy may stop between preflight and connection.
                # Retry directly only for a refused loopback proxy, not an HTTP
                # response, certificate failure or a remote corporate proxy.
                if self.proxy_mode!='auto' or not use_environment or not local_proxy(request.full_url) or 'connection refused' not in str(error).lower():raise
                response=urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=self.timeout_seconds)
            with response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:600]
            raise VisionError(
                f"Qwen Chat Completions API returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise VisionError(f"Qwen Chat Completions request failed: {exc}") from exc

        text = self._message_text(response_payload)
        if not text:
            raise VisionError(
                "Qwen Chat Completions returned no message content "
                f"({self._response_diagnostics(response_payload)})"
            )
        return extract_json_content(text)

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
            "temperature": self.temperature,
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
