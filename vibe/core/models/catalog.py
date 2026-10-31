"""One provider's model list, fetched from its ``/models`` endpoint.

Every OpenAI-compatible endpoint lists ids. Mistral, OpenRouter and Anthropic
add metadata, read here when present: a display name, image input, the
context window, and whether the model can chat with tools at all. The agent
loop needs tool calls, so a model the endpoint marks as unable to make them
(embeddings, OCR, moderation, tool-less chat models) is left out; without
metadata every listed id is kept.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
import time
from typing import Any

import httpx2
from pydantic import BaseModel, ConfigDict

from vibe.observability.logging import logger
from vibe.utils.http import VibeAsyncHTTPClient, build_ssl_context

# Bounds the whole request, not each connection phase: a slow body cannot hold
# a session start for longer.
MODELS_LIST_TIMEOUT = 10.0
# Anthropic pages its list at 20 by default.
_ANTHROPIC_PAGE = "limit=1000"


class DiscoveredModel(BaseModel):
    """One listed model, with what its endpoint said about it."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    display_name: str | None = None
    supports_images: bool | None = None
    max_context_length: int | None = None


@dataclass(slots=True)
class ModelCatalogResult:
    """One provider's discovery outcome.

    A failed refresh can still carry the models this boot cached for the
    provider: ``error`` says the fetch failed, ``models`` what is offered.
    """

    provider_name: str
    endpoint: str
    models: list[DiscoveredModel] = field(default_factory=list)
    fetched_at: float = 0.0
    from_cache: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def model_ids(self) -> list[str]:
        return [model.id for model in self.models]


def models_endpoint(api_base: str, api_style: str = "openai") -> str:
    """The provider's model list URL; Anthropic's sits under ``/v1`` either way."""
    base = api_base.rstrip("/")
    if api_style == "anthropic":
        return f"{base.removesuffix('/v1')}/v1/models?{_ANTHROPIC_PAGE}"
    return f"{base}/models"


def parse_models(payload: Any) -> list[DiscoveredModel]:
    """The chat models of a ``/models`` body, one per id, sorted by id."""
    entries = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(entries, list):
        return []
    models = {
        model.id: model
        for entry in entries
        if isinstance(entry, Mapping) and (model := _parse_entry(entry)) is not None
    }
    return [models[model_id] for model_id in sorted(models)]


def _parse_entry(entry: Mapping[str, Any]) -> DiscoveredModel | None:
    model_id = entry.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    capabilities = _mapping(entry.get("capabilities"))
    # Mistral marks embedding, OCR and moderation models this way.
    if any(
        capabilities.get(name) is False
        for name in ("completion_chat", "function_calling")
    ):
        return None
    # OpenRouter lists the request parameters a model accepts.
    parameters = entry.get("supported_parameters")
    if isinstance(parameters, list) and parameters and "tools" not in parameters:
        return None
    name = entry.get("display_name") or entry.get("name")
    return DiscoveredModel(
        id=model_id,
        display_name=name
        if isinstance(name, str) and name.strip() and name != model_id
        else None,
        supports_images=_supports_images(entry, capabilities),
        max_context_length=_context_length(entry),
    )


def _supports_images(
    entry: Mapping[str, Any], capabilities: Mapping[str, Any]
) -> bool | None:
    if isinstance(vision := capabilities.get("vision"), bool):
        return vision
    modalities = _mapping(entry.get("architecture")).get("input_modalities")
    if isinstance(modalities, list):
        return "image" in modalities
    return None


def _context_length(entry: Mapping[str, Any]) -> int | None:
    candidates = (
        entry.get("max_context_length"),
        entry.get("context_length"),
        entry.get("context_window"),
        _mapping(entry.get("top_provider")).get("context_length"),
    )
    return next(
        (
            value
            for value in candidates
            if isinstance(value, int) and not isinstance(value, bool) and value > 0
        ),
        None,
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


async def fetch_provider_models(
    provider_name: str, endpoint: str, headers: Mapping[str, str]
) -> ModelCatalogResult:
    """GET ``endpoint`` and parse it.

    Never raises: a failure is the result's ``error``, so discovery never
    breaks a session start or ``/model refresh``.
    """
    try:
        async with asyncio.timeout(MODELS_LIST_TIMEOUT):
            async with VibeAsyncHTTPClient(verify=build_ssl_context()) as client:
                response = await client.get(
                    endpoint, headers=dict(headers), timeout=MODELS_LIST_TIMEOUT
                )
                response.raise_for_status()
                models = parse_models(response.json())
    except httpx2.HTTPStatusError as exc:
        return ModelCatalogResult(
            provider_name, endpoint, error=f"HTTP {exc.response.status_code}"
        )
    except (httpx2.RequestError, TimeoutError, ValueError) as exc:
        logger.debug(
            "Model discovery failed provider=%s endpoint=%s error=%r",
            provider_name,
            endpoint,
            exc,
        )
        return ModelCatalogResult(
            provider_name, endpoint, error=str(exc) or type(exc).__name__
        )
    if not models:
        return ModelCatalogResult(
            provider_name, endpoint, error="the endpoint listed no chat models"
        )
    return ModelCatalogResult(
        provider_name, endpoint, models=models, fetched_at=time.time()
    )
