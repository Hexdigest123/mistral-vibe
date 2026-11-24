"""`/tab new` opens a fresh session in a second tab; Shift+Tab and Tab switch between the tabs."""

from __future__ import annotations

import json

from e2e.app_server.config import FIXTURE_PATH
from e2e.app_server.events import cleared_state
from e2e.app_server.scenario import Timeline, take_snapshot

_fixture = json.loads(FIXTURE_PATH.read_text())
_START = _fixture["handshake"]["session/start"]
_NEW_TAB = {"lastEventId": 0, "state": cleared_state()}

# Ordered answers: startup start, the `/tab new` start, then the switch-back
# resume (a resume naming the live session re-answers with `session/start`).
handshake = {"session/start": [_START, _NEW_TAB, _START]}
request_methods = {"session/start", "session/resume"}
screen_contains = ("1 00000001", "2 00000003", "Tab switch tab")
screen_excludes = ("Opening session",)

timeline: Timeline = [
    "/tab new\r",
    take_snapshot("two_tabs"),
    "\x1b[Z",
    take_snapshot("back_on_first"),
    "\t",
    take_snapshot("forward_again"),
]
