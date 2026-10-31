"""`/model` search: `/` focuses, typing ranks models by name, alias and provider, Esc leaves then clears."""

from __future__ import annotations

from typing import Any

from e2e.app_server.scenario import Timeline


def _model(alias: str, display_name: str, provider: str) -> dict[str, Any]:
    return {
        "name": alias,
        "alias": alias,
        "thinking": "off",
        "supportsImages": False,
        "displayName": display_name,
        "provider": provider,
    }


_DEFAULT = _model("mistral-medium-3.5", "Mistral Medium 3.5", "mistral")
_MODELS = [
    _DEFAULT,
    _model("mistral-large-3", "Mistral Large 3", "mistral"),
    _model("devstral", "Devstral", "llamacpp"),
    _model("qwen3-coder", "Qwen3 Coder", "openrouter"),
    _model("glm-5-3", "GLM 5.3", "openrouter"),
]


def _config() -> dict[str, Any]:
    return {
        "activeModel": _DEFAULT,
        "activeModelPinned": False,
        "defaultModelAlias": _DEFAULT["alias"],
        "models": _MODELS,
    }


handshake = {
    "config/read": {"config": _config()},
    "runtime/read": {"runtime": {"config": _config()}},
}

# Filter by name, leave the field, clear, filter by provider, find nothing, then pick a match.
timeline: Timeline = [
    "/model",
    "\r",
    "/",
    "large",
    "\x1b",
    "\x1b",
    "/",
    "openrouter",
    "zzz",
    "\x7f\x7f\x7f",
    "\x1b[B",
    "\r",
]
capture_steps = {1, 3, 4, 5, 7, 8, 10, 11}
