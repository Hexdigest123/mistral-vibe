"""A tab switch whose resume answers session_not_found removes the dead tab and says so."""

from __future__ import annotations

import json

from e2e.app_server.config import FIXTURE_PATH
from e2e.app_server.events import cleared_state
from e2e.app_server.scenario import Timeline, take_snapshot

_fixture = json.loads(FIXTURE_PATH.read_text())
_START = _fixture["handshake"]["session/start"]
_NEW_TAB = {"lastEventId": 0, "state": cleared_state()}

_GONE_ID = "00000000-0000-4000-8000-000000000001"
_GONE = {
    "error": {
        "code": "not_found",
        "message": f"Session not found: {_GONE_ID}",
        "data": {"harnessCode": "session_not_found", "sessionId": _GONE_ID},
    }
}

handshake = {"session/start": [_START, _NEW_TAB], "session/resume": _GONE}
request_methods = {"session/start", "session/resume"}
# The dead tab is gone (one tab left, so the bar hides) and the notice is the
# friendly one, not the raw server message.
screen_contains = ("That session no longer exists.",)
screen_excludes = ("Failed to resume session", "00000001", "Ctrl+X tabs")

_CTRL_X = "\x18"

timeline: Timeline = [
    "/tab new\r",
    _CTRL_X,
    "1",
    take_snapshot("dead_tab_removed"),
]
