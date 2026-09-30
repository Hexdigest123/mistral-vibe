from __future__ import annotations

import pytest

from vibe.core.config.default_orchestrator import build_default_orchestrator
from vibe.core.config.layers.model_catalog import ModelCatalogLayer


@pytest.mark.asyncio
async def test_empty_layer_contributes_nothing() -> None:
    layer = ModelCatalogLayer()
    snapshot = await layer.load()
    assert snapshot.model_dump() == {}


@pytest.mark.asyncio
async def test_layer_emits_models_map() -> None:
    layer = ModelCatalogLayer()
    layer.set_models({"m": {"name": "m", "provider": "p", "alias": "m"}})
    snapshot = await layer.load()
    assert snapshot.model_dump() == {
        "models": {"m": {"name": "m", "provider": "p", "alias": "m"}}
    }


@pytest.mark.asyncio
async def test_layer_snapshot_is_copied_not_aliased() -> None:
    layer = ModelCatalogLayer()
    layer.set_models({"m": {"name": "m"}})
    discovered = layer.discovered()
    discovered["m"]["name"] = "mutated"
    assert layer.discovered()["m"]["name"] == "m"


@pytest.mark.asyncio
async def test_layer_is_present_in_default_stack() -> None:
    orchestrator = await build_default_orchestrator()
    layer = orchestrator.get_layer(ModelCatalogLayer.NAME)
    assert isinstance(layer, ModelCatalogLayer)


@pytest.mark.asyncio
async def test_layer_sits_below_user_toml() -> None:
    orchestrator = await build_default_orchestrator()
    names = [layer.name for layer in orchestrator.layers]
    assert names.index(ModelCatalogLayer.NAME) < names.index("user-toml")


@pytest.mark.asyncio
async def test_discovered_models_reach_available_models() -> None:
    orchestrator = await build_default_orchestrator()
    layer = orchestrator.get_layer(ModelCatalogLayer.NAME)
    assert isinstance(layer, ModelCatalogLayer)
    layer.set_models({
        "discovered-model": {
            "name": "discovered-model",
            "provider": "mistral",
            "alias": "discovered-model",
        }
    })
    await orchestrator.reload()
    assert "discovered-model" in orchestrator.config.available_models()
