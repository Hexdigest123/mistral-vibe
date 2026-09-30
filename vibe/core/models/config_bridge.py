from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vibe.core.config.layers.model_catalog import ModelCatalogLayer
from vibe.core.config.orchestrator import ConfigOrchestrator
from vibe.core.config.vibe_schema import VibeConfigSchema
from vibe.core.models.catalog import ModelCatalogResult
from vibe.core.models.discovery import (
    cached_provider_models,
    discover_provider_models,
    discovered_models_payload,
)
from vibe.observability.logging import logger


@dataclass(slots=True)
class CatalogRefreshReport:
    """What one discovery pass found, per provider, for user feedback."""

    results: list[ModelCatalogResult] = field(default_factory=list)
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return any(result.ok for result in self.results)

    @property
    def total_models(self) -> int:
        return sum(len(result.model_ids) for result in self.results if result.ok)

    def summary(self) -> str:
        lines = []
        for result in self.results:
            if result.ok:
                source = "cache" if result.from_cache else "endpoint"
                lines.append(
                    f"{result.provider_name}: {len(result.model_ids)} models ({source})"
                )
            else:
                lines.append(f"{result.provider_name}: unavailable ({result.error})")
        return "\n".join(lines)


async def user_declared_model_aliases(
    orchestrator: ConfigOrchestrator[VibeConfigSchema],
) -> set[str]:
    """Model aliases declared in a user-authored TOML layer ([[model]] blocks).

    ``durable_model_aliases`` includes the schema defaults, which would make
    every session a discovery target; auto-discovery must only run when the
    user actually wrote a [[model]] block in their config.toml.
    """
    aliases: set[str] = set()
    for layer in orchestrator.layers:
        if layer.name not in {"user-toml", "project-toml"}:
            continue
        try:
            snapshot = await layer.load()
        except Exception:
            continue
        models = snapshot.model_dump().get("models")
        if isinstance(models, dict):
            aliases.update(models)
    return aliases


def _catalog_layer(
    orchestrator: ConfigOrchestrator[VibeConfigSchema],
) -> ModelCatalogLayer | None:
    try:
        layer = orchestrator.get_layer(ModelCatalogLayer.NAME)
    except KeyError:
        return None
    return layer if isinstance(layer, ModelCatalogLayer) else None


def discover_only_provider_names(config: VibeConfigSchema) -> set[str]:
    """Names of providers flagged ``discover_only`` in the merged config."""
    return {provider.name for provider in config.providers if provider.discover_only}


def _discovery_targets(
    config: VibeConfigSchema, declared_aliases: set[str] | None = None
) -> list[Any]:
    """Providers referenced by the models that triggered discovery.

    With ``declared_aliases`` (the startup gate), only the providers of the
    user-declared [[model]] blocks are queried; a plain refresh covers every
    provider referenced by a configured model, so a catalog fetched once keeps
    refreshing after the entry that introduced it is edited. Providers flagged
    ``discover_only`` are always targets: their models exist only through
    discovery, so no [[model]] block can gate them.
    """
    providers = {provider.name: provider for provider in config.providers}
    names = discover_only_provider_names(config)
    models = list(config.models.values())
    if declared_aliases is not None:
        models = [m for m in models if m.alias in declared_aliases]
    names |= {model.provider for model in models}
    return [providers[name] for name in sorted(names) if name in providers]


def load_cached_models(
    orchestrator: ConfigOrchestrator[VibeConfigSchema],
    *,
    declared_aliases: set[str] | None = None,
) -> CatalogRefreshReport:
    """Populate the catalog layer from the on-disk cache, synchronously."""
    layer = _catalog_layer(orchestrator)
    if layer is None:
        return CatalogRefreshReport()
    models: dict[str, dict[str, Any]] = {}
    results: list[ModelCatalogResult] = []
    for provider in _discovery_targets(orchestrator.config, declared_aliases):
        cached = cached_provider_models(provider)
        results.append(cached)
        if cached.ok:
            models.update(discovered_models_payload(cached))
    layer.set_models(models)
    logger.info(
        "Model catalog loaded from cache providers=%d models=%d",
        len(results),
        len(models),
    )
    return CatalogRefreshReport(results=results, from_cache=True)


async def refresh_models(
    orchestrator: ConfigOrchestrator[VibeConfigSchema],
    *,
    declared_aliases: set[str] | None = None,
) -> CatalogRefreshReport:
    """Fetch fresh catalogs for target providers and persist them to the cache."""
    layer = _catalog_layer(orchestrator)
    if layer is None:
        return CatalogRefreshReport()
    models: dict[str, dict[str, Any]] = {}
    results: list[ModelCatalogResult] = []
    for provider in _discovery_targets(orchestrator.config, declared_aliases):
        result = await discover_provider_models(provider)
        results.append(result)
        if result.ok:
            models.update(discovered_models_payload(result))
        else:
            cached = cached_provider_models(provider)
            if cached.ok:
                models.update(discovered_models_payload(cached))
    layer.set_models(models)
    logger.info(
        "Model catalog refreshed providers=%d models=%d", len(results), len(models)
    )
    return CatalogRefreshReport(results=results)
