"""Fork feature (AGENTS.md "Fork features"): the all-telemetry kill switch.

``disable_all_telemetry = true`` turns off every telemetry channel Vibe has —
datalake usage events, Sentry crash reports, OpenTelemetry traces and the
GrowthBook experiment eval — regardless of ``enable_telemetry``, and deletes
the telemetry Vibe keeps on disk. It is off by default, so installing this
fork never changes what is sent; the setting is flagged DANGEROUS in the
settings UI because disabling telemetry may violate the Terms of Service and
can get the account banned. Data already delivered to Mistral's servers is
irremovable from the client; the README documents what is irremovable and how
to block the endpoints at the firewall.

Like ``enable_telemetry``, a project config or an agent profile may only turn
the kill switch on (disable telemetry), never off: their
``disable_all_telemetry = false`` is dropped before the merge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from vibe.core.config.vibe_schema import VibeConfigSchema

KILL_SWITCH_FIELD = "disable_all_telemetry"

# Settings the /config screen flags as dangerous (red row, warning on enable).
DANGEROUS_SETTINGS: frozenset[str] = frozenset({KILL_SWITCH_FIELD})

# Layers that may arm the kill switch but not disarm it, with how a warning
# names them. Mirrors _telemetry_off_only.OFF_ONLY_LAYERS.
KILL_SWITCH_OFF_ONLY_LAYERS: Mapping[str, str] = {
    "project-toml": "The project's .vibe/config.toml",
    "agent-profile": "The active agent profile",
}

# The debug log line `TelemetryClient.send_telemetry_event` writes per event.
_TELEMETRY_LOG_MARKER = "telemetry event="

_BOOL = TypeAdapter(bool)


def telemetry_kill_switch_active(config: VibeConfigSchema) -> bool:
    """Whether *config* arms the kill switch (all telemetry off).

    Strict ``is True``: the schema field is always a real bool, and test doubles
    that leave the attribute unset must read as disarmed.
    """
    return getattr(config, KILL_SWITCH_FIELD, False) is True


def telemetry_active(config: VibeConfigSchema) -> bool:
    """Whether any telemetry may flow: ``enable_telemetry`` and no kill switch."""
    return config.enable_telemetry and not telemetry_kill_switch_active(config)


def ignored_kill_switch_disarm_warning(layer_name: str) -> str:
    return (
        f"{KILL_SWITCH_OFF_ONLY_LAYERS[layer_name]} sets "
        f"{KILL_SWITCH_FIELD} = false, which Vibe ignores: a project or agent "
        "config can turn all telemetry off, never back on."
    )


def disarms_kill_switch_off_only(layer_name: str, data: Mapping[str, Any]) -> bool:
    """Whether ``data``, one layer's raw values, disarms the kill switch from a
    layer that may only arm it. A value that does not read as a boolean is
    left to the schema to refuse.
    """
    if layer_name not in KILL_SWITCH_OFF_ONLY_LAYERS or KILL_SWITCH_FIELD not in data:
        return False
    try:
        return not _BOOL.validate_python(data[KILL_SWITCH_FIELD])
    except ValidationError:
        return False


def without_kill_switch_disarms(
    layers: Sequence[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """``layers`` without an off-only layer's ``disable_all_telemetry = false``."""
    return [
        (
            name,
            {key: value for key, value in data.items() if key != KILL_SWITCH_FIELD}
            if disarms_kill_switch_off_only(name, data)
            else data,
        )
        for name, data in layers
    ]


def purge_local_telemetry(config: VibeConfigSchema) -> bool:
    """Delete the telemetry Vibe stored on disk; ``True`` when the switch is on.

    Removes the GrowthBook eval caches (experiment assignments plus the
    segmentation attributes held for them) and scrubs telemetry payload lines
    from the debug log. Events already sent are server-side and irremovable.
    """
    if not telemetry_kill_switch_active(config):
        return False
    from vibe.core.experiments.cache import clear_cached_eval_responses
    from vibe.core.paths import LOG_FILE

    clear_cached_eval_responses()
    _scrub_telemetry_log_lines(LOG_FILE.path)
    return True


def _scrub_telemetry_log_lines(log_path: Path) -> None:
    """Drop the per-event telemetry payload lines from the debug log."""
    from vibe.utils.io import atomic_write_bytes

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    lines = text.splitlines(keepends=True)
    kept = [line for line in lines if _TELEMETRY_LOG_MARKER not in line]
    if len(kept) == len(lines):
        return
    try:
        atomic_write_bytes(log_path, "".join(kept).encode("utf-8"))
    except OSError:
        pass
