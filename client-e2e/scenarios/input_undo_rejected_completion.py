"""Undo restores the partial slash command after its completed submission is rejected by a held queue."""

from __future__ import annotations

from e2e.app_server.events import (
    assistant_msg,
    discard_entry,
    queued_turn,
    turn_interrupted,
    turn_queue_updated,
    turn_started,
    user_msg,
)
from e2e.app_server.scenario import Timeline

# The interrupt holds the queued prompt: a history command then waits for the user, so it is refused.
held = [queued_turn(2, "second")]
on_request = {
    "turn/interrupt": [
        discard_entry("partial", cause="interrupt"),
        turn_interrupted(),
        turn_queue_updated(held, paused=True),
    ]
}
request_methods = {"telemetry/record"}
expected_clipboard = "comp"

timeline: Timeline = [
    "first\r",
    turn_started(),
    user_msg("first"),
    assistant_msg("Let me che", entry_id="partial", generation_status="in_progress"),
    {"release": 4},
    "second\r",
    "\x1b",
    "/comp",
    "\r",
    "\x1b[122;9u",
    "\x1b[18~\x1b[99;9u",
]
