from __future__ import annotations

import pytest

from vibe.core.config.default_orchestrator import build_default_orchestrator
from vibe.core.config.layers.model_catalog import ModelCatalogLayer
from vibe.core.models import refresh_models, user_declared_model_aliases

OPENROUTER_PROVIDER = {"name": "openrouter", "api_base": "https://openrouter.ai/api/v1"}


async def _orchestrator_with_user_model(monkeypatch: pytest.MonkeyPatch):
    """Build an orchestrator whose user TOML layer declares [[model]] blocks."""
    import tomli_w

    from vibe.core.config.harness_files import HarnessFilesManager
    from vibe.core.paths import VIBE_HOME

    config = VIBE_HOME.path / "config.toml"
    config.write_text(
        tomli_w.dumps({
            "providers": [OPENROUTER_PROVIDER],
            "models": [
                {"name": "openai/gpt-4o", "provider": "openrouter", "alias": "gpt-4o"}
            ],
        }),
        encoding="utf-8",
    )
    manager = HarnessFilesManager(sources=("user", "project"))
    return await build_default_orchestrator(harness_files=manager)


@pytest.mark.asyncio
async def test_user_declared_model_aliases_empty_without_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vibe.core.paths import VIBE_HOME

    (VIBE_HOME.path / "config.toml").write_text("", encoding="utf-8")
    orchestrator = await build_default_orchestrator()
    assert await user_declared_model_aliases(orchestrator) == set()


@pytest.mark.asyncio
async def test_user_declared_model_aliases_reads_toml_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = await _orchestrator_with_user_model(monkeypatch)
    assert await user_declared_model_aliases(orchestrator) == {"gpt-4o"}


@pytest.mark.asyncio
async def test_refresh_targets_only_declared_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = await _orchestrator_with_user_model(monkeypatch)
    declared = await user_declared_model_aliases(orchestrator)

    async def fake_discover(provider):
        from vibe.core.models.catalog import ModelCatalogResult

        assert provider.name == "openrouter"
        return ModelCatalogResult(
            provider_name=provider.name,
            endpoint="https://openrouter.ai/api/v1/models",
            model_ids=["openai/gpt-4o-mini"],
            fetched_at=1.0,
        )

    monkeypatch.setattr(
        "vibe.core.models.config_bridge.discover_provider_models", fake_discover
    )
    report = await refresh_models(orchestrator, declared_aliases=declared)
    assert report.ok
    assert report.total_models == 1
    await orchestrator.reload()
    assert "openai/gpt-4o-mini" in orchestrator.config.models


@pytest.mark.asyncio
async def test_refresh_with_no_targets_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = await build_default_orchestrator()
    report = await refresh_models(orchestrator, declared_aliases=set())
    assert report.results == []


@pytest.mark.asyncio
async def test_refresh_targets_discover_only_providers_without_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``discover_only`` provider is queried even with no declared models."""
    import tomli_w

    from vibe.core.config.harness_files import HarnessFilesManager
    from vibe.core.paths import VIBE_HOME

    (VIBE_HOME.path / "config.toml").write_text(
        tomli_w.dumps({"providers": [{**OPENROUTER_PROVIDER, "discover_only": True}]}),
        encoding="utf-8",
    )
    manager = HarnessFilesManager(sources=("user", "project"))
    orchestrator = await build_default_orchestrator(harness_files=manager)

    async def fake_discover(provider):
        from vibe.core.models.catalog import ModelCatalogResult

        assert provider.name == "openrouter"
        return ModelCatalogResult(
            provider_name=provider.name,
            endpoint="https://openrouter.ai/api/v1/models",
            model_ids=["openai/gpt-4o-mini"],
            fetched_at=1.0,
        )

    monkeypatch.setattr(
        "vibe.core.models.config_bridge.discover_provider_models", fake_discover
    )
    report = await refresh_models(orchestrator, declared_aliases=set())
    assert report.ok
    await orchestrator.reload()
    assert "openai/gpt-4o-mini" in orchestrator.config.models


@pytest.mark.asyncio
async def test_refresh_falls_back_to_cache_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vibe.core.models.catalog import ModelCatalogResult

    orchestrator = await _orchestrator_with_user_model(monkeypatch)

    async def failing(provider):
        return ModelCatalogResult(
            provider_name=provider.name,
            endpoint="https://openrouter.ai/api/v1/models",
            error="HTTP 500",
        )

    def fake_cached(provider):
        return ModelCatalogResult(
            provider_name=provider.name,
            endpoint="https://openrouter.ai/api/v1/models",
            model_ids=["cached-model"],
            fetched_at=1.0,
            from_cache=True,
        )

    monkeypatch.setattr(
        "vibe.core.models.config_bridge.discover_provider_models", failing
    )
    monkeypatch.setattr(
        "vibe.core.models.config_bridge.cached_provider_models", fake_cached
    )
    report = await refresh_models(orchestrator)
    assert report.results[0].error == "HTTP 500"
    await orchestrator.reload()
    assert "cached-model" in orchestrator.config.models


@pytest.mark.asyncio
async def test_catalog_layer_merge_user_model_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = await _orchestrator_with_user_model(monkeypatch)
    layer = orchestrator.get_layer(ModelCatalogLayer.NAME)
    assert isinstance(layer, ModelCatalogLayer)
    # Same alias as the user's [[model]] entry: the durable layer must win.
    layer.set_models({"gpt-4o": {"provider": "openrouter", "name": "discovered-id"}})
    await orchestrator.reload()
    model = orchestrator.config.models["gpt-4o"]
    assert model.name == "openai/gpt-4o"
