"""The voice agent hears needs_approval once, then running as soon as the user answered the approval."""

from __future__ import annotations

from e2e.app_server.events import (
    conversation_state,
    conversation_task_request,
    tool_approval,
    tool_approval_added,
    turn_started,
    user_msg,
)
from e2e.app_server.scenario import Timeline
from scenarios.conversation_mode._setup import CTRL_X, handshake as _handshake

env = {"VIBE_INPUT_GRACE_PERIOD_MS": "0", "VIBE_TYPING_GRACE_PERIOD_MS": "0"}
handshake = {**_handshake, "callback/result": {"accepted": True}}
on_request = {
    "conversation/start": [
        conversation_state("listening"),
        conversation_task_request("run", "task0001", "search the news"),
    ]
}
request_methods = {"conversation/taskResult", "callback/result"}

_COMMAND = {"command": "curl example.com"}

timeline: Timeline = [
    CTRL_X,
    "t",
    turn_started(),
    user_msg("search the news"),
    tool_approval_added("bash", "shell", _COMMAND),
    tool_approval("bash", "shell", _COMMAND),
    "\r",
]
