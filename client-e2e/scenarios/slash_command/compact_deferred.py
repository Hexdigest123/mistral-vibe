"""A `/compact` typed while a turn runs is scheduled, then runs once the turn ends."""

from __future__ import annotations

from e2e.app_server.events import (
    SESSION_ID,
    assistant_msg,
    cleared_state,
    turn_completed,
    turn_started,
    user_msg,
)
from e2e.app_server.scenario import Timeline, take_snapshot

# The same-session compaction answer: the live id stays.
_state = cleared_state()
_state["session"]["id"] = SESSION_ID
handshake = {
    "session/compact": {
        "summary": "Compacted summary.",
        "state": _state,
        "sessionLog": {"enabled": False},
    }
}
request_methods = {"session/compact"}
screen_excludes = ("cannot be queued", "will run when")

timeline: Timeline = [
    "hello\r",
    turn_started(),
    user_msg("hello"),
    assistant_msg("Working on it.", generation_status="in_progress"),
    turn_completed(),
    {"release_after": 4},
    # The turn still runs: the command waits, shown as a notice, and the composer clears.
    "/compact\r",
    take_snapshot("scheduled"),
    # The turn ends: the command runs by itself.
    {"release": 1},
    take_snapshot("ran_when_idle"),
]
