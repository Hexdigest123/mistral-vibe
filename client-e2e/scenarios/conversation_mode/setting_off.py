"""With the setting off, Ctrl+X t only says where to turn it on and asks the server for nothing."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, take_snapshot

screen_contains = ("Conversation mode is off: turn it on in /voice.",)
screen_excludes = ("Conversation ·",)

timeline: Timeline = ["\x18", "t", take_snapshot()]
