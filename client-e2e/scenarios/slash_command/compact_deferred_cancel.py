"""Esc on the running turn also cancels the history command scheduled for its end."""

from __future__ import annotations

from e2e.app_server.events import assistant_msg, turn_started, user_msg
from e2e.app_server.scenario import Timeline, take_snapshot

request_methods = {"turn/interrupt", "session/compact"}
screen_contains = ("/compact cancelled",)
screen_excludes = ("cannot be queued", "will run when")

timeline: Timeline = [
    "hello\r",
    turn_started(),
    user_msg("hello"),
    assistant_msg("Working on it.", generation_status="in_progress"),
    "/compact\r",
    take_snapshot("scheduled"),
    "\x1b",
    take_snapshot("cancelled"),
]
