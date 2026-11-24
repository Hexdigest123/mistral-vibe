"""A picker narrower than its footer wraps the hints between pairs and grows the box, so Esc cancel stays visible."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, resize, take_snapshot

timeline: Timeline = [resize(30, 40), "/model\r", take_snapshot()]

# Fork feature (AGENTS.md): the picker's search hint sits after navigation.
screen_contains = (
    "navigate",
    "/ search",
    "Enter save",
    "Esc cancel",
)
