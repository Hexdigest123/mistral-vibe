"""Fork feature (AGENTS.md "Fork features"): the ``disable_all_telemetry`` kill switch.

On by default in this fork: every telemetry channel is gated by
``telemetry_active`` (``enable_telemetry`` and no kill switch), the setting is
flagged dangerous in ``config/fields/read``, a project/agent layer may arm it
but never disarm it, and arming it purges the telemetry stored on disk.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import build_test_vibe_config
from vibe.app_server._config_introspect import build_field_wires
from vibe.core.config._self_hosted import crash_reports_allowed, experiments_allowed
from vibe.core.config._telemetry_kill_switch import (
    DANGEROUS_SETTINGS,
    KILL_SWITCH_FIELD,
    disarms_kill_switch_off_only,
    purge_local_telemetry,
    telemetry_active,
    telemetry_kill_switch_active,
    without_kill_switch_disarms,
)
from vibe.core.config.vibe_schema import VibeConfigSchema
from vibe.core.paths import (
    EXPERIMENT_EVAL_CACHE_FILE,
    EXPERIMENT_HELD_EVAL_CACHE_FILE,
    LOG_FILE,
)
from vibe.core.telemetry.send import TelemetryClient

_original_send_telemetry_event = TelemetryClient.send_telemetry_event


def _run_telemetry_tasks() -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(asyncio.sleep(0))
    finally:
        loop.close()


def test_the_kill_switch_defaults_off_and_is_a_dangerous_setting() -> None:
    # Off by default: installing this fork never risks a ban on its own.
    field = VibeConfigSchema.model_fields[KILL_SWITCH_FIELD]
    assert field.default is False
    assert DANGEROUS_SETTINGS == frozenset({KILL_SWITCH_FIELD})
    assert not telemetry_kill_switch_active(build_test_vibe_config())
    assert telemetry_kill_switch_active(
        build_test_vibe_config(disable_all_telemetry=True)
    )


def test_kill_switch_gates_every_telemetry_check() -> None:
    config = build_test_vibe_config(enable_telemetry=True, disable_all_telemetry=True)
    assert not telemetry_active(config)
    assert not crash_reports_allowed(config)
    assert not experiments_allowed(config)
    on = build_test_vibe_config(enable_telemetry=True, disable_all_telemetry=False)
    assert telemetry_active(on)


def test_telemetry_client_sends_nothing_with_the_kill_switch_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
    )
    config = build_test_vibe_config(enable_telemetry=True, disable_all_telemetry=True)
    env_key = config.get_active_provider().api_key_env_var
    monkeypatch.setenv(env_key, "sk-test")
    client = TelemetryClient(config_getter=lambda: config)
    client._client = MagicMock()
    client._client.post = AsyncMock()

    client.send_telemetry_event("vibe.test", {})
    _run_telemetry_tasks()

    assert not client.is_active()
    client._client.post.assert_not_called()


def test_project_and_agent_layers_may_not_disarm_the_kill_switch() -> None:
    assert disarms_kill_switch_off_only("project-toml", {KILL_SWITCH_FIELD: False})
    assert disarms_kill_switch_off_only("agent-profile", {KILL_SWITCH_FIELD: False})
    assert not disarms_kill_switch_off_only("project-toml", {KILL_SWITCH_FIELD: True})
    assert not disarms_kill_switch_off_only("user-toml", {KILL_SWITCH_FIELD: False})
    layers = [("project-toml", {KILL_SWITCH_FIELD: False, "theme": "dark"})]
    assert without_kill_switch_disarms(layers) == [("project-toml", {"theme": "dark"})]


def test_prepare_layers_drops_a_projects_kill_switch_disarm() -> None:
    layers = VibeConfigSchema.prepare_layers([
        ("default", {KILL_SWITCH_FIELD: False}),
        ("user-toml", {KILL_SWITCH_FIELD: True}),
        ("project-toml", {KILL_SWITCH_FIELD: False, "theme": "dark"}),
    ])
    # The user's own layer may arm the switch; a cloned repo's may not disarm it.
    assert ("user-toml", {KILL_SWITCH_FIELD: True}) in layers
    assert ("project-toml", {"theme": "dark"}) in layers


def test_fields_read_flags_the_kill_switch_dangerous() -> None:
    config = build_test_vibe_config()
    by_name = {wire.name: wire for wire in build_field_wires(config, {})}
    assert by_name[KILL_SWITCH_FIELD].dangerous
    assert not by_name["enable_telemetry"].dangerous


def test_purge_deletes_stored_telemetry_only_when_armed() -> None:
    # The autouse config_dir fixture points VIBE_HOME at an isolated tmp dir.
    eval_cache = EXPERIMENT_EVAL_CACHE_FILE.path
    held_cache = EXPERIMENT_HELD_EVAL_CACHE_FILE.path
    log_file = LOG_FILE.path
    eval_cache.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    eval_cache.write_text('{"key": {}}', encoding="utf-8")
    held_cache.write_text('{"key": {}}', encoding="utf-8")
    log_file.write_text(
        "2026-01-01 info starting\n"
        '2026-01-01 debug telemetry event=vibe.test properties={"a": 1}\n'
        "2026-01-01 info done\n",
        encoding="utf-8",
    )

    armed = build_test_vibe_config(disable_all_telemetry=True)
    assert purge_local_telemetry(armed) is True
    assert not eval_cache.exists()
    assert not held_cache.exists()
    remaining = log_file.read_text(encoding="utf-8")
    assert "telemetry event=" not in remaining
    assert "starting" in remaining and "done" in remaining

    # Re-arm: nothing left to delete, still armed.
    assert purge_local_telemetry(armed) is True
    disarmed = build_test_vibe_config(disable_all_telemetry=False)
    assert purge_local_telemetry(disarmed) is False
