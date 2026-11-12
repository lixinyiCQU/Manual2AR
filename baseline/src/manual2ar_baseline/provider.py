"""Small compatible image/JSON transport; no reference application or skill dependency."""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pydantic import Field, SecretStr, model_validator

from .gt import Strict, Text


class ModelError(RuntimeError):
    """Deliberately contains no upstream body, URL, headers or credential."""


class Settings(Strict):
    base_url: Text
    model: Text
    api_key: SecretStr
    timeout_seconds: float = Field(default=120.0, gt=0, le=300)
    temperature: float = Field(default=0.0, ge=0, le=2)
    enable_thinking: bool | None = None
    proxy_mode: str = Field(default="system", pattern=r"^(system|auto|direct)$")

    @model_validator(mode="after")
    def endpoint(self):
        url = urllib.parse.urlsplit(self.base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Use an HTTPS base URL without embedded credentials, query or fragment")
        if not self.api_key.get_secret_value().strip():
            raise ValueError("Model API credential is not configured")
        return self


def load_settings(path: Path, model: str | None = None):
    value = json.loads(path.read_bytes())
    source = value.get("vlm", value)
    selected = {k: source[k] for k in Settings.model_fields if k in source}
    if model:
        selected["model"] = model
    selected.setdefault("api_key", os.environ.get("QIANWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY") or "")
    # Report missing/invalid fields without allowing a validation traceback to echo the private input.
    try:
        return Settings.model_validate(selected)
    except ValueError:
        raise ModelError("Invalid model configuration; check endpoint, model and credential locally") from None


class CompatibleClient:
    kind = "compatible_http"

    def __init__(self, settings: Settings, *, max_tokens=5000):
        self.settings = settings
        if type(max_tokens) is not int or not 1 <= max_tokens <= 24000:
            raise ValueError("Invalid response token limit")
        self.max_tokens = max_tokens

    def call(self, prompt, schema, images):
        content = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(raw).decode()}} for raw in images]
        content.append({"type": "text", "text": prompt + "\n仅返回 JSON，遵守此 Schema：\n" + json.dumps(schema, ensure_ascii=False)})
        payload = dict(model=self.settings.model, messages=[dict(role="user", content=content)],
                       response_format={"type": "json_object"}, max_tokens=self.max_tokens, temperature=self.settings.temperature)
        if self.settings.enable_thinking is not None:
            payload["enable_thinking"] = self.settings.enable_thinking
        request = urllib.request.Request(self.settings.base_url.rstrip("/") + "/chat/completions", data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.settings.api_key.get_secret_value()}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if self.settings.proxy_mode == "direct" else urllib.request.build_opener()
        started = time.monotonic()
        try:
            with opener.open(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ModelError("Model response exceeds local limit")
            envelope = json.loads(raw)
            choice = envelope["choices"][0]
            text = choice["message"]["content"]
            if not isinstance(text, str) or not text.strip() or choice.get("finish_reason") not in (None, "stop"):
                raise ModelError("Model response is empty or incomplete")
            usage = envelope.get("usage") or {}
            return text, dict(model=self.settings.model, elapsed_ms=round((time.monotonic() - started) * 1000),
                              temperature=self.settings.temperature, enable_thinking=self.settings.enable_thinking,
                              response_format="json_object", http_attempts=1,
                              usage={k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if type(usage.get(k)) is int})
        except urllib.error.HTTPError as error:
            raise ModelError("Model HTTP request failed: " + str(error.code)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ModelError("Model connection failed or timed out") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelError("Model returned an invalid response envelope") from None
