from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
import tomli_w

from vibe.core.config.default_orchestrator import build_default_orchestrator
from vibe.core.config.harness_files import HarnessFilesManager
from vibe.core.models import apply_discovered_models, discover_provider_names
from vibe.core.paths import VIBE_HOME

OPENROUTER = {
    "name": "openrouter",
    "api_base": "https://openrouter.ai/api/v1",
    "discover": True,
}
MODELS_URL = "https://openrouter.ai/api/v1/models"


async def _orchestrator(config: dict[str, Any]):
    (VIBE_HOME.path / "config.toml").write_text(tomli_w.dumps(config), encoding="utf-8")
    manager = HarnessFilesManager(sources=("user", "project"))
    return await build_default_orchestrator(harness_files=manager)


def _listing(*entries: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(entries)})


@pytest.mark.asyncio
async def test_without_a_discover_provider_nothing_is_sent(
    respx_mock: respx.MockRouter,
) -> None:
    orchestrator = await _orchestrator({
        "providers": [{**OPENROUTER, "discover": False}]
    })
    report = await apply_discovered_models(orchestrator)
    assert report.results == [] and not report.changed
    assert not respx_mock.calls


@pytest.mark.asyncio
async def test_discovered_models_join_the_config(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(MODELS_URL).mock(
        return_value=_listing({
            "id": "openai/gpt-5",
            "name": "OpenAI: GPT-5",
            "context_length": 400000,
            "architecture": {"input_modalities": ["text", "image"]},
        })
    )
    orchestrator = await _orchestrator({"providers": [OPENROUTER]})
    assert discover_provider_names(orchestrator.config) == ["openrouter"]
    report = await apply_discovered_models(orchestrator)
    assert report.changed and report.total_models == 1
    await orchestrator.reload()
    model = orchestrator.config.models["openai/gpt-5"]
    assert (model.provider, model.display_name) == ("openrouter", "OpenAI: GPT-5")
    assert model.supports_images is True
    assert model.max_context_length == 400000
    again = await apply_discovered_models(orchestrator)
    assert not again.changed


@pytest.mark.asyncio
async def test_an_explicit_model_wins_field_by_field(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(MODELS_URL).mock(
        return_value=_listing({"id": "openai/gpt-5", "name": "OpenAI: GPT-5"})
    )
    orchestrator = await _orchestrator({
        "providers": [OPENROUTER],
        "models": [
            {
                "name": "openai/gpt-5",
                "provider": "openrouter",
                "alias": "openai/gpt-5",
                "display_name": "Mine",
                "temperature": 0.7,
            }
        ],
    })
    await apply_discovered_models(orchestrator)
    await orchestrator.reload()
    model = orchestrator.config.models["openai/gpt-5"]
    assert (model.display_name, model.temperature) == ("Mine", 0.7)


@pytest.mark.asyncio
async def test_a_discovered_id_never_takes_over_another_providers_alias(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(MODELS_URL).mock(return_value=_listing({"id": "devstral-latest"}))
    orchestrator = await _orchestrator({
        "active_model": "devstral-latest",
        "providers": [OPENROUTER],
        "models": [
            {
                "name": "mistral-vibe-cli-latest",
                "provider": "mistral",
                "alias": "devstral-latest",
            }
        ],
    })
    await apply_discovered_models(orchestrator)
    await orchestrator.reload()
    models = orchestrator.config.models
    assert models["devstral-latest"].provider == "mistral"
    assert models["openrouter/devstral-latest"].name == "devstral-latest"


@pytest.mark.asyncio
async def test_a_failed_listing_leaves_the_config_alone(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(MODELS_URL).mock(return_value=httpx.Response(401))
    orchestrator = await _orchestrator({"providers": [OPENROUTER]})
    before = set(orchestrator.config.models)
    report = await apply_discovered_models(orchestrator)
    assert report.errors == ["openrouter: HTTP 401"]
    assert not report.changed
    assert set(orchestrator.config.models) == before
