"""Ctrl+X s stashes the draft and clears the prompt; Ctrl+X p puts it back at the cursor."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, take_snapshot

CTRL_X = "\x18"

screen_contains = ("> fix the login bug",)
screen_excludes = ("Nothing to stash",)

timeline: Timeline = [
    "fix the login bug",
    CTRL_X,
    "s",
    take_snapshot("stashed"),
    CTRL_X,
    "p",
    take_snapshot("popped"),
]
