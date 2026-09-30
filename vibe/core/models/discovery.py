from __future__ import annotations

from typing import Any

from vibe.core.models.catalog import (
    ModelCatalogResult,
    fetch_provider_models,
    read_cached_catalog,
    store_catalog_result,
)
from vibe.observability.logging import logger
from vibe.utils.api_keys import resolve_api_key

# Discovery stays bounded even for providers with very wide catalogs: enough to
# fill a picker, not enough to drown it or bloat the merged config.
MAX_DISCOVERED_MODELS_PER_PROVIDER = 100


def _model_payload(provider_name: str, model_id: str) -> dict[str, Any]:
    return {
        "name": model_id,
        "provider": provider_name,
        "alias": model_id,
        "display_name": None,
    }


def discovered_models_payload(result: ModelCatalogResult) -> dict[str, Any]:
    """Convert a catalog result into the deep-mergeable ``models`` map shape."""
    if not result.ok:
        return {}
    models = {
        model_id: _model_payload(result.provider_name, model_id)
        for model_id in result.model_ids[:MAX_DISCOVERED_MODELS_PER_PROVIDER]
    }
    return models


def _provider_headers(provider: Any) -> dict[str, str]:
    return dict(getattr(provider, "extra_headers", None) or {})


def _provider_api_key(provider: Any) -> str | None:
    env_var = getattr(provider, "api_key_env_var", "")
    if not env_var:
        return None
    return resolve_api_key(env_var)


def _catalog_result_from_cache(provider: Any) -> ModelCatalogResult:
    from vibe.core.models.catalog import models_endpoint

    return read_cached_catalog(provider.name, models_endpoint(provider.api_base))


async def discover_provider_models(provider: Any) -> ModelCatalogResult:
    """Fetch one provider's catalog and fold it into the cache."""
    api_base = getattr(provider, "api_base", "")
    if not api_base:
        return ModelCatalogResult(
            provider_name=provider.name, endpoint="", error="provider has no api_base"
        )
    result = await fetch_provider_models(
        provider.name,
        api_base,
        api_key=_provider_api_key(provider),
        extra_headers=_provider_headers(provider),
    )
    if result.ok:
        store_catalog_result(result)
    return result


def cached_provider_models(provider: Any) -> ModelCatalogResult:
    """Read one provider's cached catalog, or an empty not-ok result."""
    try:
        return _catalog_result_from_cache(provider)
    except Exception as exc:
        logger.debug(
            "Model catalog cache read failed provider=%s",
            getattr(provider, "name", "?"),
        )
        return ModelCatalogResult(
            provider_name=getattr(provider, "name", ""), endpoint="", error=str(exc)
        )
