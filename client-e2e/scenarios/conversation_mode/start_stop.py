"""Ctrl+X t forces smart-approve and starts the voice session; its phase and speech show; Ctrl+X t ends it."""

from __future__ import annotations

from e2e.app_server.events import conversation_state, conversation_transcript
from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.conversation_mode._setup import CTRL_X, handshake

__all__ = ["handshake"]

# The voice session starts listening, hears a request, answers and speaks.
on_request = {
    "conversation/start": [
        conversation_state("listening"),
        conversation_transcript("user", "what is in this repo"),
        conversation_transcript("assistant", "Let me look."),
        conversation_state("speaking"),
    ]
}
request_methods = {"session/approvalPolicy/update", "conversation/start", "conversation/stop"}
screen_contains = ("Conversation mode off.",)
screen_excludes = ("Failed",)

timeline: Timeline = [
    CTRL_X,
    "t",
    take_snapshot("speaking"),
    CTRL_X,
    "t",
    take_snapshot("ended"),
]
