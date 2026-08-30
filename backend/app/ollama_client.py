from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("MANUAL2AR_OLLAMA_URL", "http://127.0.0.1:11434")
        self.model = os.getenv("MANUAL2AR_OLLAMA_MODEL", "minicpm-v4.6:q4_0")
        self.timeout_seconds = int(
            os.getenv("MANUAL2AR_OLLAMA_TIMEOUT_SECONDS", "180")
        )

    def chat_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        images_base64: list[str] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "user", "content": prompt}
        if images_base64:
            message["images"] = images_base64

        payload = {
            "model": self.model,
            "messages": [message],
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "format": schema,
            "options": {
                "temperature": 0,
                "num_ctx": 8192,
                "num_predict": max_tokens,
            },
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        content = response_payload.get("message", {}).get("content")
        if not content:
            raise OllamaError("Ollama returned an empty structured response")

        return self._extract_json_content(content)

    @staticmethod
    def _extract_json_content(content: str) -> dict[str, Any]:
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
                raise OllamaError(
                    "Ollama returned content without a JSON object"
                )
            try:
                value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
            except json.JSONDecodeError as exc:
                raise OllamaError(
                    "Ollama returned invalid or truncated JSON content"
                ) from exc

        if not isinstance(value, dict):
            raise OllamaError("Ollama structured response was not a JSON object")
        return value
