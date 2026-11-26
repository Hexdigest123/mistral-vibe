"""`/stash <text>` stacks prompts; `/stash list` shows them newest first and `/pop` takes the latest back."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, take_snapshot

screen_contains = ("Stash (2)", "1. second prompt", "2. first prompt", "last in, first out")

timeline: Timeline = [
    "/stash first prompt\r",
    "/stash second prompt\r",
    "/stash list\r",
    take_snapshot("list"),
]
