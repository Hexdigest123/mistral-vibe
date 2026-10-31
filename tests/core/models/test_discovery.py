from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from vibe.core.config.models import ProviderConfig
from vibe.core.models.cache import load_cache
from vibe.core.models.catalog import DiscoveredModel, ModelCatalogResult
from vibe.core.models.discovery import discover, models_payload

OPENROUTER = ProviderConfig(
    name="openrouter",
    api_base="https://openrouter.ai/api/v1",
    api_key_env_var="OPENROUTER_API_KEY",
    discover=True,
)
LOCAL = ProviderConfig(name="local", api_base="http://127.0.0.1:1234/v1", discover=True)


def _ids(*ids: str) -> dict[str, Any]:
    return {"data": [{"id": model_id} for model_id in ids]}


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")


@pytest.mark.asyncio
async def test_a_cold_start_fetches_and_caches(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json=_ids("b", "a"))
    )
    [result] = await discover([OPENROUTER])
    assert result.ok and not result.from_cache
    assert result.model_ids == ["a", "b"]
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-or-test"
    entry = load_cache().providers["openrouter"]
    assert [m.id for m in entry.models] == ["a", "b"]
    assert "sk-or-test" not in entry.model_dump_json()


@pytest.mark.asyncio
async def test_a_warm_start_sends_no_request(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json=_ids("a"))
    )
    await discover([OPENROUTER])
    [result] = await discover([OPENROUTER])
    assert route.call_count == 1
    assert result.from_cache and result.model_ids == ["a"]


@pytest.mark.asyncio
async def test_only_uncached_providers_are_fetched(
    respx_mock: respx.MockRouter,
) -> None:
    openrouter = respx_mock.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json=_ids("a"))
    )
    local = respx_mock.get("http://127.0.0.1:1234/v1/models").mock(
        return_value=httpx.Response(200, json=_ids("qwen"))
    )
    await discover([OPENROUTER])
    results = await discover([OPENROUTER, LOCAL])
    assert [r.provider_name for r in results] == ["openrouter", "local"]
    assert (openrouter.call_count, local.call_count) == (1, 1)
    assert "Authorization" not in local.calls.last.request.headers


@pytest.mark.asyncio
async def test_a_new_key_or_endpoint_refetches(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = respx_mock.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json=_ids("a"))
    )
    other = respx_mock.get("https://proxy.example/v1/models").mock(
        return_value=httpx.Response(200, json=_ids("b"))
    )
    await discover([OPENROUTER])
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-other")
    await discover([OPENROUTER])
    assert route.call_count == 2
    moved = OPENROUTER.model_copy(update={"api_base": "https://proxy.example/v1"})
    [result] = await discover([moved])
    assert other.called and result.model_ids == ["b"]


@pytest.mark.asyncio
async def test_a_refresh_refetches_and_a_failure_keeps_the_cache(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.get("https://openrouter.ai/api/v1/models")
    route.mock(return_value=httpx.Response(200, json=_ids("a")))
    await discover([OPENROUTER])
    route.mock(return_value=httpx.Response(200, json=_ids("a", "new")))
    [result] = await discover([OPENROUTER], refresh=True)
    assert result.model_ids == ["a", "new"] and result.ok
    route.mock(return_value=httpx.Response(503))
    [result] = await discover([OPENROUTER], refresh=True)
    assert result.error == "HTTP 503"
    assert result.from_cache and result.model_ids == ["a", "new"]


@pytest.mark.asyncio
async def test_a_failure_is_not_cached(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://openrouter.ai/api/v1/models")
    route.mock(return_value=httpx.Response(500))
    [result] = await discover([OPENROUTER])
    assert result.error == "HTTP 500" and result.models == []
    route.mock(return_value=httpx.Response(200, json=_ids("a")))
    [result] = await discover([OPENROUTER])
    assert result.ok and route.call_count == 2


@pytest.mark.asyncio
async def test_anthropic_style_providers_send_their_key_header(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    route = respx_mock.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(200, json=_ids("claude-x"))
    )
    provider = ProviderConfig(
        name="anthropic",
        api_base="https://api.anthropic.com/v1",
        api_key_env_var="ANTHROPIC_API_KEY",
        api_style="anthropic",
        discover=True,
    )
    [result] = await discover([provider])
    headers = route.calls.last.request.headers
    assert result.ok
    assert headers["x-api-key"] == "sk-ant" and "anthropic-version" in headers
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_a_configured_auth_header_is_left_alone(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json=_ids("a"))
    )
    provider = OPENROUTER.model_copy(
        update={"extra_headers": {"Authorization": "Token custom"}}
    )
    await discover([provider])
    assert route.calls.last.request.headers["Authorization"] == "Token custom"


def _result(provider: str, *models: DiscoveredModel) -> ModelCatalogResult:
    return ModelCatalogResult(provider, "", models=list(models))


def test_payload_maps_metadata_and_drops_unknowns() -> None:
    payload = models_payload(
        [
            _result(
                "openrouter",
                DiscoveredModel(
                    id="x/vision",
                    display_name="X Vision",
                    supports_images=True,
                    max_context_length=128000,
                ),
                DiscoveredModel(id="x/plain"),
            )
        ],
        taken={},
    )
    assert payload == {
        "x/vision": {
            "name": "x/vision",
            "provider": "openrouter",
            "alias": "x/vision",
            "display_name": "X Vision",
            "supports_images": True,
            "max_context_length": 128000,
        },
        "x/plain": {"name": "x/plain", "provider": "openrouter", "alias": "x/plain"},
    }


def test_payload_namespaces_an_alias_another_provider_owns() -> None:
    qwen = DiscoveredModel(id="qwen")
    payload = models_payload(
        [_result("ollama", qwen), _result("lmstudio", qwen), _result("mistral", qwen)],
        taken={"qwen": "ollama", "mistral-medium-3.5": "mistral"},
    )
    assert sorted(payload) == ["lmstudio/qwen", "mistral/qwen", "qwen"]
    assert payload["qwen"]["provider"] == "ollama"
    assert payload["lmstudio/qwen"]["name"] == "qwen"


@pytest.mark.asyncio
async def test_racing_cold_starts_fetch_once(respx_mock: respx.MockRouter) -> None:
    import asyncio

    route = respx_mock.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json=_ids("a"))
    )
    first, second = await asyncio.gather(discover([OPENROUTER]), discover([OPENROUTER]))
    assert route.call_count == 1
    assert first[0].model_ids == second[0].model_ids == ["a"]
