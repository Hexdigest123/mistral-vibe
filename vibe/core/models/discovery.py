"""Model discovery for the providers flagged ``discover = true``.

A provider's list comes from this boot's cache when it holds one for the
provider's endpoint and key, and from the provider's ``/models`` endpoint
otherwise or when a refresh is asked for. Fetches run concurrently, and what
they return is cached for the rest of the boot (``vibe.core.models.cache``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from vibe.core.models.cache import (
    CachedProvider,
    DiscoveryCache,
    key_fingerprint,
    load_cache,
    locked,
    save_cache,
)
from vibe.core.models.catalog import (
    ModelCatalogResult,
    fetch_provider_models,
    models_endpoint,
)
from vibe.utils.api_keys import resolve_api_key
from vibe.utils.http import with_user_agent
from vibe.utils.oidc_marker import is_oidc_marker

if TYPE_CHECKING:
    from vibe.core.config.models import ProviderConfig

_AUTH_HEADERS = frozenset({"authorization", "x-api-key"})


async def discover(
    providers: Sequence[ProviderConfig], *, refresh: bool = False
) -> list[ModelCatalogResult]:
    """Each provider's models, in ``providers`` order.

    A refresh fetches every provider; one that fails keeps what this boot
    cached for it, with the failure in ``error``.
    """
    if not providers:
        return []
    # One thread for all: keyring backends are not all safe to call in parallel.
    keys = await asyncio.to_thread(lambda: [_api_key(p) for p in providers])
    async with locked():
        cache = await asyncio.to_thread(load_cache)
        cached = [_cached(cache, p, k) for p, k in zip(providers, keys, strict=True)]
        targets = [i for i, hit in enumerate(cached) if refresh or hit is None]
        fetched = await asyncio.gather(
            *(_fetch(providers[i], keys[i]) for i in targets)
        )
        results: list[ModelCatalogResult | None] = list(cached)
        for i, result in zip(targets, fetched, strict=True):
            if result.ok:
                cache.providers[providers[i].name] = CachedProvider(
                    endpoint=result.endpoint,
                    key=key_fingerprint(keys[i]),
                    fetched_at=result.fetched_at,
                    models=result.models,
                )
            elif (hit := cached[i]) is not None:
                hit.error = result.error
                result = hit
            results[i] = result
        if any(result.ok for result in fetched):
            await asyncio.to_thread(save_cache, cache)
    return [result for result in results if result is not None]


def models_payload(
    results: Sequence[ModelCatalogResult], taken: Mapping[str, str]
) -> dict[str, dict[str, Any]]:
    """The deep-mergeable ``models`` map for the provider-models layer.

    A model's alias is its id, unless ``taken`` (alias -> provider of the
    models other layers define) or an earlier provider already gives that
    alias to another provider: it is then namespaced as ``provider/id``.
    An explicit ``[[models]]`` entry of the same provider and alias wins field
    by field over what discovery fills in.
    """
    owners = dict(taken)
    payload: dict[str, dict[str, Any]] = {}
    for result in results:
        provider = result.provider_name
        for model in result.models:
            alias = model.id
            if owners.get(alias, provider) != provider:
                alias = f"{provider}/{model.id}"
            if alias in payload:
                continue
            owners.setdefault(alias, provider)
            entry = {
                "name": model.id,
                "provider": provider,
                "alias": alias,
                "display_name": model.display_name,
                "supports_images": model.supports_images,
                "max_context_length": model.max_context_length,
            }
            payload[alias] = {k: v for k, v in entry.items() if v is not None}
    return payload


def _cached(
    cache: DiscoveryCache, provider: ProviderConfig, key: str | None
) -> ModelCatalogResult | None:
    entry = cache.providers.get(provider.name)
    endpoint = models_endpoint(provider.api_base, provider.api_style)
    if (
        entry is None
        or not entry.models
        or entry.endpoint != endpoint
        or entry.key != key_fingerprint(key)
    ):
        return None
    return ModelCatalogResult(
        provider.name,
        endpoint,
        models=list(entry.models),
        fetched_at=entry.fetched_at,
        from_cache=True,
    )


async def _fetch(provider: ProviderConfig, key: str | None) -> ModelCatalogResult:
    if not provider.api_base:
        return ModelCatalogResult(provider.name, "", error="provider has no api_base")
    endpoint = models_endpoint(provider.api_base, provider.api_style)
    try:
        headers = await _headers(provider, key)
    except Exception as exc:
        return ModelCatalogResult(provider.name, endpoint, error=str(exc))
    return await fetch_provider_models(provider.name, endpoint, headers)


def _api_key(provider: ProviderConfig) -> str | None:
    # Blocking: resolution can read the keyring and the environment file.
    if not provider.api_key_env_var:
        return None
    return resolve_api_key(provider.api_key_env_var)


async def _headers(provider: ProviderConfig, key: str | None) -> dict[str, str]:
    """The provider's own headers plus the credential its scheme takes."""
    headers = with_user_agent(provider.extra_headers, provider.backend)
    if not key or any(name.lower() in _AUTH_HEADERS for name in headers):
        return headers
    if is_oidc_marker(key):
        from vibe.setup.auth._oidc_runtime import oidc_headers

        return {**headers, **await oidc_headers(provider.api_base)}
    if provider.api_style == "anthropic":
        from mistralai_vibe_local_harness.vibe.completion_profile import (
            ANTHROPIC_VERSION,
        )

        return {**headers, "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    return {**headers, "Authorization": f"Bearer {key}"}
