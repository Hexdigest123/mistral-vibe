"""Fork feature: `/model` fzf terms all match, across name and provider, and `!term` excludes."""

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
    _model("mistral-large-4", "Mistral Large 4", "mistral"),
    _model("qwen/qwen3-coder", "Qwen3 Coder", "openrouter"),
    _model("qwen3-coder", "Qwen3 Coder", "local"),
    _model("openai/gpt-5", "OpenAI: GPT-5", "openrouter"),
    _model("openai/gpt-5-mini", "OpenAI: GPT-5 Mini", "openrouter"),
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

# Terms span fields, then a negated term, then an exact prefix; Esc leaves and clears each.
timeline: Timeline = [
    "/model",
    "\r",
    "/",
    "coder openrouter",
    "\x1b",
    "\x1b",
    "/",
    "gpt !mini",
    "\x1b",
    "\x1b",
    "/",
    "^mistral large",
]
capture_steps = {3, 7, 11}
