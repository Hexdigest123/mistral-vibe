"""Model discovery for providers flagged ``discover = true`` (fork feature).

Keep it: AGENTS.md "Fork features" lists what this package must keep doing.
"""

from __future__ import annotations

from vibe.core.models.cache import (
    CACHE_VERSION,
    DiscoveryCache,
    boot_id,
    cache_path,
    load_cache,
    save_cache,
)
from vibe.core.models.catalog import (
    DiscoveredModel,
    ModelCatalogResult,
    fetch_provider_models,
    models_endpoint,
    parse_models,
)
from vibe.core.models.config_bridge import (
    DiscoveryReport,
    apply_discovered_models,
    discover_provider_names,
)
from vibe.core.models.discovery import discover, models_payload

__all__ = [
    "CACHE_VERSION",
    "DiscoveredModel",
    "DiscoveryCache",
    "DiscoveryReport",
    "ModelCatalogResult",
    "apply_discovered_models",
    "boot_id",
    "cache_path",
    "discover",
    "discover_provider_names",
    "fetch_provider_models",
    "load_cache",
    "models_endpoint",
    "models_payload",
    "parse_models",
    "save_cache",
]
