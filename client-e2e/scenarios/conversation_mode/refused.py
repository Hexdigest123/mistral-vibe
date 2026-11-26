"""A server that cannot start the voice session ends the mode, restores the policy and shows why."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline
from scenarios.conversation_mode._setup import CTRL_X
from scenarios.conversation_mode._setup import handshake as _base

_NEEDS = "Conversation mode needs a build with the voice-agents feature: run `make features`."

handshake = {**_base, "conversation/start": {"error": {"code": "invalid_params", "message": _NEEDS}}}
request_methods = {"session/approvalPolicy/update", "conversation/start"}
screen_contains = ("voice-agents feature",)
screen_excludes = ("Conversation ·", "Conversation mode on")

timeline: Timeline = [CTRL_X, "t"]
