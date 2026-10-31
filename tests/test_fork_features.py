"""Fork features must survive every upstream merge (AGENTS.md "Fork features").

A failure here means a merge or an edit dropped or broke a fork feature:
restore it, or re-implement it on the code upstream replaced it with. Never
delete, skip or weaken these tests, and never shorten ``GUARD_TESTS``.
"""

from __future__ import annotations

import inspect
from pathlib import Path
import tempfile

import pytest

from vibe.app_server import _cached_layers
from vibe.app_server.config import ModelConfigView
from vibe.app_server.protocol import SERVER_METHODS
from vibe.core.config import ModelConfig, ProviderConfig, VibeConfigSchema
from vibe.core.models import cache

REPO = Path(__file__).resolve().parents[1]

# The behavior tests behind each fork feature; each must keep existing.
GUARD_TESTS = (
    "tests/core/models/test_catalog.py",
    "tests/core/models/test_cache.py",
    "tests/core/models/test_discovery.py",
    "tests/core/models/test_config_bridge.py",
    "tests/core/config/test_provider_models_layer.py",
    "tests/app_server/test_provider_model_discovery.py",
    "tests/app_server/test_image_read_hooks.py",
    "tests/app_server/test_vision.py",
    "vibe/cli-rust/tests/units/fork_features.rs",
    "vibe/cli-rust/tests/units/fzf_rank.rs",
    "vibe/cli-rust/tests/units/config_filter.rs",
    "vibe/cli-rust/tests/units/model_picker_search.rs",
    "vibe/cli-rust/tests/units/model_refresh.rs",
    "vibe/cli-rust/tests/units/paste_image.rs",
    "client-e2e/scenarios/model/model_search.py",
    "client-e2e/scenarios/model/model_fzf_terms.py",
    "client-e2e/scenarios/model/model_refresh.py",
    "client-e2e/scenarios/model/model_refresh_unconfigured.py",
    "client-e2e/scenarios/slash_command/resume_search.py",
    "client-e2e/scenarios/slash_command/config_edit_choice_search.py",
)


def _dropped(feature: str) -> str:
    return f"Fork feature dropped or broken: {feature}. See AGENTS.md 'Fork features'."


@pytest.mark.parametrize("path", GUARD_TESTS)
def test_the_guard_tests_still_exist(path: str) -> None:
    assert (REPO / path).is_file(), _dropped(f"guard test {path} is gone")


def test_the_rust_guard_tests_are_registered() -> None:
    units = (REPO / "vibe/cli-rust/tests/units.rs").read_text(encoding="utf-8")
    for module in ("fork_features", "fzf_rank", "model_refresh", "paste_image"):
        assert f"mod {module};" in units, _dropped(f"Rust units module {module}")


def test_providers_take_a_discover_flag() -> None:
    field = ProviderConfig.model_fields.get("discover")
    assert field is not None and field.default is False, _dropped(
        "[[providers]] discover = true"
    )


def test_discovered_models_cache_until_reboot_under_the_temp_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache, "_CACHE_DIR", None)
    assert cache.cache_path().is_relative_to(Path(tempfile.gettempdir())), _dropped(
        "the discovery cache lives under the system temp dir"
    )
    assert "boot_id" in cache.DiscoveryCache.model_fields, _dropped(
        "the discovery cache is scoped to one boot"
    )


def test_every_config_build_applies_discovered_models() -> None:
    source = inspect.getsource(_cached_layers.apply_cached_layers)
    assert "_apply_discovered_models(orchestrator)" in source, _dropped(
        "config builds apply the discover providers' models"
    )


def test_the_model_refresh_method_and_provider_column_stay() -> None:
    assert "models/refresh" in SERVER_METHODS, _dropped("models/refresh")
    assert "provider" in ModelConfigView.model_fields, _dropped(
        "the /model provider column"
    )


def test_image_reads_are_described_for_blind_models() -> None:
    from vibe.app_server._image_read_hooks import image_describe_hook_handlers

    assert image_describe_hook_handlers().post_tool_call, _dropped(
        "the builtin:image_describe hook"
    )


def test_a_blind_model_on_any_provider_falls_back_to_the_vision_model() -> None:
    large = ModelConfig(
        name="mistral-large-4-0",
        provider="mistral",
        alias="mistral-large-4",
        supports_images=True,
    )
    blind = ModelConfig(name="text/only", provider="openrouter", alias="text/only")
    config = VibeConfigSchema.model_validate({
        "active_model": "text/only",
        "providers": [
            ProviderConfig(name="mistral", api_base="https://api.mistral.ai/v1"),
            ProviderConfig(
                name="openrouter",
                api_base="https://openrouter.ai/api/v1",
                discover=True,
            ),
        ],
        "models": [large, blind],
        "vision_model": large,
    })
    assert config.get_vision_fallback_model() == large, _dropped(
        "vision_model describes images for a blind active model"
    )


def test_make_build_installs_the_vibes_wrapper() -> None:
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    assert "$(LOCAL_BIN_DIR)/vibes" in makefile, _dropped("make build -> vibes")
