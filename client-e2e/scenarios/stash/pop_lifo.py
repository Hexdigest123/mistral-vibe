"""`/pop` puts the latest stashed prompt in the prompt, then the one before it."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, take_snapshot

screen_contains = ("> first prompt",)
screen_excludes = ("second prompt",)

timeline: Timeline = [
    "/stash first prompt\r",
    "/stash second prompt\r",
    "/pop\r",
    take_snapshot("latest"),
    "\x15",
    "/pop\r",
    take_snapshot("earlier"),
]
