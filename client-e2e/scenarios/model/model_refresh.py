"""Fork feature: `/model refresh` re-lists the `discover = true` providers and reports each one."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline

handshake = {
    "models/refresh": {
        "entries": [
            {
                "providerName": "openrouter",
                "endpoint": "https://openrouter.ai/api/v1/models",
                "modelIds": ["moonshotai/kimi-k3", "openai/gpt-5", "z-ai/glm-5"],
            },
            {
                "providerName": "local",
                "endpoint": "http://127.0.0.1:1234/v1/models",
                "modelIds": ["qwen3-coder"],
            },
        ],
        "totalModels": 4,
        "errors": ["local: HTTP 503"],
    }
}
request_methods = {"models/refresh"}
capture_startup = False
timeline: Timeline = ["/model refresh\r"]
screen_contains = (
    "Could not refresh local: HTTP 503; models listed: openrouter 3, local 1",
)
