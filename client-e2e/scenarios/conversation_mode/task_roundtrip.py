"""The voice agent hands over a task: it runs as a prompt, and the finished turn's answer goes back to it."""

from __future__ import annotations

from e2e.app_server.events import (
    assistant_msg,
    conversation_state,
    conversation_task_request,
    turn_completed,
    turn_started,
    user_msg,
)
from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.conversation_mode._setup import CTRL_X, handshake

__all__ = ["handshake"]

# The voice agent asks for a task as it starts: it runs as a queued prompt.
on_request = {
    "conversation/start": [
        conversation_state("listening"),
        conversation_task_request("run", "task0001", "run the tests"),
    ]
}
request_methods = {"session/turn/enqueue", "conversation/taskResult"}
screen_contains = ("run the tests", "All tests pass.")

timeline: Timeline = [
    CTRL_X,
    "t",
    turn_started(),
    user_msg("run the tests"),
    assistant_msg("All tests pass."),
    turn_completed(),
    take_snapshot("done"),
]
