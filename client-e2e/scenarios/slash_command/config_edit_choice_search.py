"""Fork feature: a long `/config` choice list takes `/` search, and Enter saves the best match."""

from __future__ import annotations

from typing import Any

from e2e.app_server.scenario import Timeline, take_snapshot


def _model(alias: str, display_name: str) -> dict[str, Any]:
    return {
        "name": alias,
        "alias": alias,
        "thinking": "off",
        "supportsImages": False,
        "displayName": display_name,
    }


models = [_model(f"model-{index}", f"Model {index}") for index in range(20)] + [
    _model("openai/gpt-5", "OpenAI: GPT-5"),
    _model("openai/gpt-5-mini", "OpenAI: GPT-5 Mini"),
]
handshake = {
    "config/read": {"config": {"models": models}},
    "runtime/read": {"runtime": {"config": {"models": models}}},
}

timeline: Timeline = ["/config\r", "\r", "/", "gpt mini", take_snapshot(), "\x1b", "\r", take_snapshot()]
screen_excludes = ("Search choices",)
