"""Shared builders for the session tab scenarios."""

from __future__ import annotations

import json
from typing import Any

from e2e.app_server.config import FIXTURE_PATH
from e2e.app_server.events import SESSION_ID, TURN_ID, assistant_msg, user_msg
from e2e.app_server.scenario import AppServerEvent

_fixture = json.loads(FIXTURE_PATH.read_text())
START = _fixture["handshake"]["session/start"]
CTRL_X = "\x18"
SECOND_ID = "00000000-0000-4000-8000-000000000003"
THIRD_ID = "00000000-0000-4000-8000-000000000004"
FIRST_ID = SESSION_ID


def answer(
    session_id: str, *added: AppServerEvent, running: bool = False
) -> dict[str, Any]:
    """A `session/start` or `session/resume` answer for `session_id` holding the `added` entries."""
    state = json.loads(json.dumps(START["state"]))
    state["session"]["id"] = session_id
    state["history"] = [event["params"]["entry"] for event in added]
    if running:
        state["session"]["status"] = {"type": "running", "activeTurnId": TURN_ID}
    return {"lastEventId": START["lastEventId"], "state": state}


def exchange(session_id: str, text: str, reply: str) -> list[AppServerEvent]:
    """The user message and the answer a turn of `session_id` adds."""
    return [
        user_msg(text, session_id=session_id),
        assistant_msg(reply, session_id=session_id),
    ]


def listed(*rows: tuple[str, str]) -> dict[str, Any]:
    """A `session/list` answer: one `(session id, status type)` row each."""
    items = [
        {
            "id": session_id,
            "rootSessionId": session_id,
            "parentSessionId": None,
            "title": "",
            "preview": "",
            "status": {"type": status},
            "createdAt": 1_787_593_260_000,
            "updatedAt": 1_787_593_260_000,
            "cwd": "/workspace",
        }
        for session_id, status in rows
    ]
    return {"items": items, "nextCursor": None, "previousCursor": None}
