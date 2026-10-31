"""Fork feature: ``discover = true`` providers reach every config build."""

from __future__ import annotations

import httpx
import pytest
import respx
import tomli_w

from vibe.app_server._cached_layers import apply_cached_layers
from vibe.app_server._session_config_cache import session_config_inputs
from vibe.core.config.default_orchestrator import build_default_orchestrator
from vibe.core.config.harness_files import HarnessFilesManager
from vibe.core.models.cache import cache_path
from vibe.core.paths import VIBE_HOME

MODELS_URL = "https://openrouter.ai/api/v1/models"


def _write_config() -> HarnessFilesManager:
    (VIBE_HOME.path / "config.toml").write_text(
        tomli_w.dumps({
            "providers": [
                {
                    "name": "openrouter",
                    "api_base": "https://openrouter.ai/api/v1",
                    "discover": True,
                }
            ]
        }),
        encoding="utf-8",
    )
    return HarnessFilesManager(sources=("user", "project"))


async def _build(manager: HarnessFilesManager):
    orchestrator = await build_default_orchestrator(harness_files=manager)
    await apply_cached_layers(orchestrator, None)
    return orchestrator


@pytest.mark.asyncio
async def test_the_first_build_fetches_and_later_builds_read_the_boot_cache(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.get(MODELS_URL).mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "moonshotai/kimi-k3"}, {"id": "z-ai/glm-5"}]}
        )
    )
    manager = _write_config()
    first = await _build(manager)
    second = await _build(manager)
    assert route.call_count == 1
    for orchestrator in (first, second):
        assert {"moonshotai/kimi-k3", "z-ai/glm-5"} <= set(orchestrator.config.models)
        assert orchestrator.config.models["z-ai/glm-5"].provider == "openrouter"


@pytest.mark.asyncio
async def test_an_unreachable_provider_never_fails_the_build(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(MODELS_URL).mock(side_effect=httpx.ConnectError("offline"))
    orchestrator = await _build(_write_config())
    assert not any(
        m.provider == "openrouter" for m in orchestrator.config.models.values()
    )


def test_session_builds_follow_the_cache_file() -> None:
    inputs = session_config_inputs(_write_config())
    assert isinstance(inputs, tuple)
    assert str(cache_path()) in {path for path, _ in inputs[0]}
