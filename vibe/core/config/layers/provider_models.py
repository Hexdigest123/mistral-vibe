from __future__ import annotations

import copy
from typing import Any

from vibe.core.config.fingerprint import create_dict_fingerprint
from vibe.core.config.layer import ConfigLayer, RawConfig
from vibe.core.config.types import EMPTY_CONFIG_SNAPSHOT, LayerConfigSnapshot


class ProviderModelsLayer(ConfigLayer[RawConfig]):
    """Lowest-priority in-memory layer feeding models discovered from providers.

    ``[[model]]`` blocks in user or project TOML land in higher layers and win
    per-model (the ``models`` field deep-merges by alias), so discovery only
    fills gaps: a catalog id that has no explicit entry becomes selectable in
    the model picker, and any explicit ``[[model]]`` keeps its configured
    pricing, thinking level, and vision flags. It sits below the Mistral
    model-catalog layer, so a curated entry also wins over a bare discovered id.
    """

    NAME = "provider-models"

    def __init__(self, *, name: str = NAME) -> None:
        super().__init__(name=name)
        self._models: dict[str, dict[str, Any]] = {}

    def set_models(self, models: dict[str, dict[str, Any]]) -> None:
        """Replace the discovered models; call ``orchestrator.reload()`` after."""
        self._models = copy.deepcopy(models)

    def discovered(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._models)

    async def _check_trust(self) -> bool:
        return True

    async def _build_config_snapshot(self) -> LayerConfigSnapshot:
        if not self._models:
            return EMPTY_CONFIG_SNAPSHOT
        data = {"models": copy.deepcopy(self._models)}
        return LayerConfigSnapshot(data=data, fingerprint=create_dict_fingerprint(data))

    async def _save_to_store(self, _next_config: RawConfig) -> str:
        raise NotImplementedError("ProviderModelsLayer is populated by discovery only")
