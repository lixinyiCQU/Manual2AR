from __future__ import annotations

import json

from app.vision_client import QwenChatCompletionsClient


def main() -> None:
    client = QwenChatCompletionsClient()
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["connected"]},
            "model_acknowledgement": {"type": "string"},
        },
        "required": ["status", "model_acknowledgement"],
    }
    result = client.chat_structured(
        prompt=(
            "This is a Manual2AR connection test. Return JSON with status set "
            "to connected and briefly acknowledge that you can perform "
            "conservative before/after visual state comparison."
        ),
        schema=schema,
        images_base64=[],
        max_tokens=256,
    )
    if result.get("status") != "connected":
        raise RuntimeError(f"Unexpected smoke-test result: {result}")
    print("Qwen connection test passed")
    print(f"provider=qwen")
    print(f"model={client.model}")
    print(f"base_url={client.base_url}")
    print("result=" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
