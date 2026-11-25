"""A slash command that rewrites the history, submitted during a turn, is scheduled for its end, not refused."""

from __future__ import annotations

from e2e.app_server.events import assistant_msg, turn_started, user_msg
from e2e.app_server.scenario import Timeline, take_snapshot

screen_contains = ("/resume will run when the current turn finishes",)
screen_excludes = ("cannot be queued",)

timeline: Timeline = [
    "first\r",
    turn_started(),
    user_msg("first"),
    assistant_msg("Working on it."),
    {"release": 4},
    "/resume",
    "\r",
    take_snapshot(),
]
