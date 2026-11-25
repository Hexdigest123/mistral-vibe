"""`/model` opens its picker while a turn runs, like every command that does not rewrite history."""

from __future__ import annotations

from e2e.app_server.events import assistant_msg, turn_started, user_msg
from e2e.app_server.scenario import Timeline, take_snapshot

screen_contains = ("Working on it.", "Select Model")
screen_excludes = ("cannot be queued",)

timeline: Timeline = [
    "first\r",
    turn_started(),
    user_msg("first"),
    assistant_msg("Working on it.", generation_status="in_progress"),
    "/model\r",
    take_snapshot("picker_while_busy"),
]
