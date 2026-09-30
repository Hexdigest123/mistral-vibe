from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from vibe.core.models.catalog import (
    MODELS_CACHE_VERSION,
    fetch_provider_models,
    load_catalog_cache,
    models_endpoint,
    read_cached_catalog,
    store_catalog_result,
)
from vibe.core.models.config_bridge import CatalogRefreshReport
from vibe.core.models.discovery import discovered_models_payload


def _models_payload(*ids: str) -> dict[str, object]:
    return {"data": [{"id": model_id} for model_id in ids]}


@pytest.mark.asyncio
async def test_fetch_parses_and_sorts_model_ids(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(
            200, json=_models_payload("z-model", "a-model", "a-model")
        )
    )
    result = await fetch_provider_models("openrouter", "https://openrouter.ai/api/v1")
    assert route.called
    assert result.ok
    assert result.model_ids == ["a-model", "z-model"]
    assert result.endpoint == "https://openrouter.ai/api/v1/models"
    assert result.fetched_at > 0


@pytest.mark.asyncio
async def test_fetch_sends_bearer_token(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json=_models_payload("m"))
    )
    await fetch_provider_models("openrouter", "https://openrouter.ai/api/v1", "key")
    assert route.calls.last.request.headers["Authorization"] == "Bearer key"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 404, 500])
async def test_fetch_reports_http_error(
    respx_mock: respx.MockRouter, status_code: int
) -> None:
    respx_mock.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(status_code)
    )
    result = await fetch_provider_models("openrouter", "https://openrouter.ai/api/v1")
    assert not result.ok
    assert result.error == f"HTTP {status_code}"


@pytest.mark.asyncio
async def test_fetch_reports_empty_catalog(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    result = await fetch_provider_models("openrouter", "https://openrouter.ai/api/v1")
    assert not result.ok
    assert "no model ids" in (result.error or "")


def test_models_endpoint_joins_base() -> None:
    assert (
        models_endpoint("https://openrouter.ai/api/v1/")
        == "https://openrouter.ai/api/v1/models"
    )


class TestCache:
    def test_missing_cache_is_empty(self, config_dir: Path) -> None:
        assert load_catalog_cache().providers == {}

    def test_round_trip(self, config_dir: Path) -> None:
        result = fetch_result_ok("openrouter", ["a", "b"])
        store_catalog_result(result)
        cache = load_catalog_cache()
        assert cache.version == MODELS_CACHE_VERSION
        assert cache.providers["openrouter"].model_ids == ["a", "b"]
        assert cache.providers["openrouter"].endpoint == result.endpoint

    def test_read_cached_requires_matching_endpoint(self, config_dir: Path) -> None:
        store_catalog_result(fetch_result_ok("openrouter", ["a"]))
        assert read_cached_catalog("openrouter", "https://x/v1/models").ok
        assert not read_cached_catalog("openrouter", "https://other/v1/models").ok
        assert not read_cached_catalog("other", "https://x/v1/models").ok

    def test_invalid_cache_is_ignored(self, config_dir: Path) -> None:
        (config_dir / "model_catalog_cache.json").write_text(
            "{not json", encoding="utf-8"
        )
        assert load_catalog_cache().providers == {}

    def test_stale_version_is_ignored(self, config_dir: Path) -> None:
        payload = {"version": 999, "providers": {"openrouter": {}}}
        (config_dir / "model_catalog_cache.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        assert load_catalog_cache().providers == {}


def fetch_result_ok(provider: str, model_ids: list[str]):
    from vibe.core.models.catalog import ModelCatalogResult

    return ModelCatalogResult(
        provider_name=provider,
        endpoint="https://x/v1/models",
        model_ids=model_ids,
        fetched_at=123.0,
    )


def test_discovered_models_payload_caps_entries() -> None:
    result = fetch_result_ok("openrouter", [f"m{i}" for i in range(300)])
    payload = discovered_models_payload(result)
    assert len(payload) == 100
    assert payload["m0"] == {
        "name": "m0",
        "provider": "openrouter",
        "alias": "m0",
        "display_name": None,
    }


def test_discovered_models_payload_skips_failed_results() -> None:
    from vibe.core.models.catalog import ModelCatalogResult

    failed = ModelCatalogResult(
        provider_name="openrouter", endpoint="https://x/v1/models", error="HTTP 500"
    )
    assert discovered_models_payload(failed) == {}


def test_report_summary_lists_providers() -> None:
    from vibe.core.models.catalog import ModelCatalogResult

    report = CatalogRefreshReport(
        results=[
            ModelCatalogResult(
                provider_name="openrouter",
                endpoint="https://x/v1/models",
                model_ids=["a", "b"],
                from_cache=True,
            ),
            ModelCatalogResult(
                provider_name="other", endpoint="https://y/v1/models", error="HTTP 401"
            ),
        ]
    )
    assert report.ok
    assert report.total_models == 2
    assert "openrouter: 2 models (cache)" in report.summary()
    assert "other: unavailable (HTTP 401)" in report.summary()
