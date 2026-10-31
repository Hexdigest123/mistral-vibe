from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from vibe.core.models.catalog import (
    DiscoveredModel,
    fetch_provider_models,
    models_endpoint,
    parse_models,
)

OPENROUTER = "https://openrouter.ai/api/v1/models"


def _ids(*ids: str) -> dict[str, Any]:
    return {"data": [{"id": model_id} for model_id in ids]}


def test_parse_sorts_and_deduplicates_bare_ids() -> None:
    models = parse_models(_ids("z-model", "a-model", "a-model"))
    assert [model.id for model in models] == ["a-model", "z-model"]
    assert models[0] == DiscoveredModel(id="a-model")


@pytest.mark.parametrize(
    "payload", [None, [], {"data": "nope"}, {"data": [1, None, {"id": ""}, {"id": 3}]}]
)
def test_parse_ignores_malformed_bodies(payload: Any) -> None:
    assert parse_models(payload) == []


def test_parse_reads_mistral_capabilities() -> None:
    payload = {
        "data": [
            {
                "id": "mistral-large-latest",
                "name": "mistral-large-latest",
                "max_context_length": 131072,
                "capabilities": {
                    "completion_chat": True,
                    "function_calling": True,
                    "vision": True,
                },
            },
            {
                "id": "mistral-embed",
                "capabilities": {"completion_chat": False, "function_calling": False},
            },
            {
                "id": "chat-no-tools",
                "capabilities": {"completion_chat": True, "function_calling": False},
            },
        ]
    }
    assert parse_models(payload) == [
        DiscoveredModel(
            id="mistral-large-latest", supports_images=True, max_context_length=131072
        )
    ]


def test_parse_reads_openrouter_metadata() -> None:
    payload = {
        "data": [
            {
                "id": "anthropic/claude-sonnet-4.5",
                "name": "Anthropic: Claude Sonnet 4.5",
                "context_length": 1000000,
                "architecture": {"input_modalities": ["text", "image"]},
                "supported_parameters": ["tools", "temperature"],
            },
            {
                "id": "some/text-only",
                "architecture": {"input_modalities": ["text"]},
                "top_provider": {"context_length": 32768},
                "supported_parameters": ["tools"],
            },
            {"id": "some/no-tools", "supported_parameters": ["temperature"]},
        ]
    }
    assert parse_models(payload) == [
        DiscoveredModel(
            id="anthropic/claude-sonnet-4.5",
            display_name="Anthropic: Claude Sonnet 4.5",
            supports_images=True,
            max_context_length=1000000,
        ),
        DiscoveredModel(
            id="some/text-only", supports_images=False, max_context_length=32768
        ),
    ]


def test_parse_reads_anthropic_display_name() -> None:
    payload = {"data": [{"id": "claude-x", "display_name": "Claude X"}]}
    assert parse_models(payload)[0].display_name == "Claude X"


def test_models_endpoint() -> None:
    assert models_endpoint("https://openrouter.ai/api/v1/") == OPENROUTER
    for base in ("https://api.anthropic.com", "https://api.anthropic.com/v1/"):
        assert (
            models_endpoint(base, "anthropic")
            == "https://api.anthropic.com/v1/models?limit=1000"
        )


@pytest.mark.asyncio
async def test_fetch_parses_and_sends_headers(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(OPENROUTER).mock(
        return_value=httpx.Response(200, json=_ids("b", "a"))
    )
    result = await fetch_provider_models(
        "openrouter", OPENROUTER, {"Authorization": "Bearer key"}
    )
    assert result.ok
    assert result.model_ids == ["a", "b"]
    assert result.endpoint == OPENROUTER
    assert result.fetched_at > 0
    assert route.calls.last.request.headers["Authorization"] == "Bearer key"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 404, 500])
async def test_fetch_reports_http_error(
    respx_mock: respx.MockRouter, status_code: int
) -> None:
    respx_mock.get(OPENROUTER).mock(return_value=httpx.Response(status_code))
    result = await fetch_provider_models("openrouter", OPENROUTER, {})
    assert not result.ok
    assert result.error == f"HTTP {status_code}"


@pytest.mark.asyncio
async def test_fetch_reports_unreachable_endpoint(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(OPENROUTER).mock(side_effect=httpx.ConnectError("refused"))
    result = await fetch_provider_models("openrouter", OPENROUTER, {})
    assert not result.ok
    assert result.models == []


@pytest.mark.asyncio
async def test_fetch_reports_a_list_without_chat_models(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(OPENROUTER).mock(return_value=httpx.Response(200, json={"data": []}))
    result = await fetch_provider_models("openrouter", OPENROUTER, {})
    assert result.error == "the endpoint listed no chat models"
