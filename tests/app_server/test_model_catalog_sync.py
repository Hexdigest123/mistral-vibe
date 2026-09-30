from __future__ import annotations

import asyncio
import json

import pytest
import tomli_w

from vibe.app_server._runtime import _MODEL_CATALOG_TASKS, _start_model_catalog_sync
from vibe.core.config.default_orchestrator import build_default_orchestrator
from vibe.core.config.harness_files import HarnessFilesManager
from vibe.core.paths import VIBE_HOME

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


def _seed_catalog_cache(model_ids: list[str]) -> None:
    from vibe.core.models.catalog import MODELS_CACHE_VERSION, models_endpoint

    cache = {
        "version": MODELS_CACHE_VERSION,
        "providers": {
            "openrouter": {
                "endpoint": models_endpoint(OPENROUTER_API_BASE),
                "model_ids": model_ids,
                "fetched_at": 1.0,
            }
        },
    }
    (VIBE_HOME.path / "model_catalog_cache.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_startup_sync_surfaces_cached_catalog_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (VIBE_HOME.path / "config.toml").write_text(
        tomli_w.dumps({
            "providers": [
                {
                    "name": "openrouter",
                    "api_base": OPENROUTER_API_BASE,
                    "discover_only": True,
                }
            ]
        }),
        encoding="utf-8",
    )
    _seed_catalog_cache(["moonshotai/kimi-k3", "moonshotai/kimi-k3:batch"])
    manager = HarnessFilesManager(sources=("user", "project"))
    orchestrator = await build_default_orchestrator(harness_files=manager)

    refresh_calls: list[object | None] = []

    async def fake_refresh(_orchestrator, **kwargs):
        refresh_calls.append(kwargs)
        from vibe.core.models.config_bridge import CatalogRefreshReport

        return CatalogRefreshReport()

    monkeypatch.setattr("vibe.app_server._runtime.refresh_models", fake_refresh)

    await _start_model_catalog_sync(orchestrator)

    assert "moonshotai/kimi-k3" in orchestrator.config.models
    assert "moonshotai/kimi-k3:batch" in orchestrator.config.models

    # The background refresh task still runs, but the cached models were
    # already visible before it completed.
    await asyncio.gather(*list(_MODEL_CATALOG_TASKS))
    assert refresh_calls, "background catalog refresh was not scheduled"
