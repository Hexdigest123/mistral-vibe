"""Discovered models into the provider-models config layer.

Every config build and host read applies them (``apply_cached_layers``): this
boot's cache answers at once, and a provider it holds nothing for is fetched
then, within ``MODELS_LIST_TIMEOUT``. ``/model refresh`` asks every provider
again (``refresh=True``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vibe.core.config.layers.provider_models import ProviderModelsLayer
from vibe.core.config.orchestrator import ConfigOrchestrator
from vibe.core.config.vibe_schema import VibeConfigSchema
from vibe.core.models.catalog import ModelCatalogResult
from vibe.core.models.discovery import discover, models_payload
from vibe.observability.logging import logger


@dataclass(slots=True)
class DiscoveryReport:
    """What one discovery pass found, per provider, and whether config moved."""

    results: list[ModelCatalogResult] = field(default_factory=list)
    changed: bool = False

    @property
    def total_models(self) -> int:
        return sum(len(result.models) for result in self.results)

    @property
    def errors(self) -> list[str]:
        return [f"{r.provider_name}: {r.error}" for r in self.results if not r.ok]


def discover_provider_names(config: VibeConfigSchema) -> list[str]:
    """Providers flagged ``discover = true``, in config order."""
    return [provider.name for provider in config.providers if provider.discover]


async def apply_discovered_models(
    orchestrator: ConfigOrchestrator[VibeConfigSchema], *, refresh: bool = False
) -> DiscoveryReport:
    """Set the provider-models layer from discovery; the caller reloads when
    ``changed``. Without a ``discover`` provider this sends no request.
    """
    try:
        layer = orchestrator.get_layer(ProviderModelsLayer.NAME)
    except KeyError:
        return DiscoveryReport()
    if not isinstance(layer, ProviderModelsLayer):
        return DiscoveryReport()
    config = orchestrator.config
    previous = layer.discovered()
    providers = [provider for provider in config.providers if provider.discover]
    results = await discover(providers, refresh=refresh)
    # Aliases this layer gave are recomputed; every other layer's are taken.
    taken = {
        alias: model.provider
        for alias, model in config.models.items()
        if alias not in previous
    }
    models = models_payload(results, taken)
    if models == previous:
        return DiscoveryReport(results=results)
    layer.set_models(models)
    logger.info(
        "Discovered models applied providers=%d models=%d", len(results), len(models)
    )
    return DiscoveryReport(results=results, changed=True)
