"""`/cd` while a turn runs is sent at once; the server's busy refusal is shown, not hidden by the client."""

from __future__ import annotations

from e2e.app_server.events import assistant_msg, turn_started, user_msg
from e2e.app_server.scenario import Timeline
from scenarios.cd._dirs import CLIENT_ARGS, REQUEST_METHODS, handshake

handshake = {
    **handshake(),
    "workspace/prompt/prepare": {"prompt": {"promptText": None}},
    "session/relocate": {
        "error": {
            "code": "conflict",
            "message": "A turn is already running: turn-1",
            "data": {"activeTurnId": "turn-1"},
        }
    },
}
client_args = CLIENT_ARGS
request_methods = REQUEST_METHODS
screen_contains = (
    "The session can't move while a turn runs — try /cd again once it ends.",
)
screen_excludes = ("Moved to", "cannot be queued")

timeline: Timeline = [
    "long task\r",
    turn_started(),
    user_msg("long task"),
    assistant_msg("Working on it."),
    {"release": 4},
    "/cd alpha\r",
]
