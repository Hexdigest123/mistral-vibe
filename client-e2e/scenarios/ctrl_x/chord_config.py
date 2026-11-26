"""Ctrl+X c opens the settings screen, as /config does."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.slash_command._config_fixtures import field, fields_read

handshake = {"config/fields/read": fields_read(field("theme", "str", "dark", category="popular"))}

screen_contains = ("Settings", "Theme")

timeline: Timeline = ["\x18", "c", take_snapshot()]
