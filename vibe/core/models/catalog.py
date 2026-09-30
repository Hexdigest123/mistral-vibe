from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from vibe.observability.logging import logger
from vibe.utils.http import VibeAsyncHTTPClient, build_ssl_context

MODELS_LIST_TIMEOUT = 10.0
MODELS_CACHE_VERSION = 1


class ProviderCatalogEntry(BaseModel):
    """One provider's cached catalog: the model ids and when they were fetched."""

    model_config = ConfigDict(extra="ignore")

    endpoint: str
    model_ids: list[str] = Field(default_factory=list)
    fetched_at: float = 0.0


class ModelCatalogCache(BaseModel):
    """On-disk cache of auto-discovered model catalogs, keyed by provider name."""

    model_config = ConfigDict(extra="ignore")

    version: int = MODELS_CACHE_VERSION
    providers: dict[str, ProviderCatalogEntry] = Field(default_factory=dict)


@dataclass(slots=True)
class ModelCatalogResult:
    """Outcome of one discovery attempt for a single provider."""

    provider_name: str
    endpoint: str
    model_ids: list[str] = field(default_factory=list)
    fetched_at: float = 0.0
    from_cache: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def models_endpoint(api_base: str) -> str:
    """Return the OpenAI-compatible ``/models`` list URL for a provider base."""
    return f"{api_base.rstrip('/')}/models"


def _parse_model_ids(payload: Any) -> list[str]:
    """Extract sorted unique model ids from an OpenAI-style ``/models`` body."""
    if not isinstance(payload, dict):
        return []
    entries = payload.get("data")
    if not isinstance(entries, list):
        return []
    ids = [entry.get("id") for entry in entries if isinstance(entry, dict)]
    return sorted({
        model_id for model_id in ids if isinstance(model_id, str) and model_id
    })


def _catalog_cache_path() -> Any:
    from vibe.core.paths import MODEL_CATALOG_CACHE_FILE

    return MODEL_CATALOG_CACHE_FILE.path


def load_catalog_cache() -> ModelCatalogCache:
    """Read the catalog cache from disk; a missing or stale file yields empty."""
    path = _catalog_cache_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ModelCatalogCache()
    except OSError as exc:
        logger.debug("Model catalog cache unreadable path=%s error=%s", path, exc)
        return ModelCatalogCache()
    try:
        cache = ModelCatalogCache.model_validate_json(raw)
    except ValueError as exc:
        logger.debug("Model catalog cache invalid, ignoring error=%s", exc)
        return ModelCatalogCache()
    if cache.version != MODELS_CACHE_VERSION:
        return ModelCatalogCache()
    return cache


def save_catalog_cache(cache: ModelCatalogCache) -> None:
    """Persist the catalog cache; failures never break the caller."""
    path = _catalog_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cache.model_dump_json(indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "Could not write model catalog cache path=%s error=%s", path, exc
        )


def read_cached_catalog(provider_name: str, endpoint: str) -> ModelCatalogResult:
    """Return the cached catalog entry for a provider when it matches the endpoint."""
    cache = load_catalog_cache()
    entry = cache.providers.get(provider_name)
    if entry is None or entry.endpoint != endpoint or not entry.model_ids:
        return ModelCatalogResult(
            provider_name=provider_name, endpoint=endpoint, error="not cached"
        )
    return ModelCatalogResult(
        provider_name=provider_name,
        endpoint=endpoint,
        model_ids=list(entry.model_ids),
        fetched_at=entry.fetched_at,
        from_cache=True,
    )


async def fetch_provider_models(
    provider_name: str,
    api_base: str,
    api_key: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> ModelCatalogResult:
    """Fetch ``/models`` from an OpenAI-compatible endpoint.

    Any failure is returned as ``error`` on the result rather than raised, so
    discovery never breaks startup or the ``/models refresh`` command.
    """
    endpoint = models_endpoint(api_base)
    headers = dict(extra_headers or {})
    if api_key:
        headers.setdefault("Authorization", f"Bearer {api_key}")
    try:
        async with VibeAsyncHTTPClient(verify=build_ssl_context()) as client:
            response = await client.get(
                endpoint, headers=headers, timeout=MODELS_LIST_TIMEOUT
            )
            response.raise_for_status()
            model_ids = _parse_model_ids(response.json())
    except httpx.HTTPStatusError as exc:
        return ModelCatalogResult(
            provider_name=provider_name,
            endpoint=endpoint,
            error=f"HTTP {exc.response.status_code}",
        )
    except (httpx.RequestError, ValueError) as exc:
        logger.debug(
            "Model discovery failed provider=%s endpoint=%s error=%s",
            provider_name,
            endpoint,
            exc,
        )
        return ModelCatalogResult(
            provider_name=provider_name, endpoint=endpoint, error=str(exc)
        )
    if not model_ids:
        return ModelCatalogResult(
            provider_name=provider_name,
            endpoint=endpoint,
            error="the endpoint returned no model ids",
        )
    return ModelCatalogResult(
        provider_name=provider_name,
        endpoint=endpoint,
        model_ids=model_ids,
        fetched_at=time.time(),
    )


def store_catalog_result(result: ModelCatalogResult) -> None:
    """Fold one discovery result into the on-disk cache."""
    if not result.ok:
        return
    cache = load_catalog_cache()
    cache.providers[result.provider_name] = ProviderCatalogEntry(
        endpoint=result.endpoint,
        model_ids=list(result.model_ids),
        fetched_at=result.fetched_at or time.time(),
    )
    save_catalog_cache(cache)
