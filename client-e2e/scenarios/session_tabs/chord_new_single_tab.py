"""Ctrl+X then n opens a second tab even when only one tab exists yet."""

from __future__ import annotations

import json

from e2e.app_server.config import FIXTURE_PATH
from e2e.app_server.events import cleared_state
from e2e.app_server.scenario import Timeline, take_snapshot

_fixture = json.loads(FIXTURE_PATH.read_text())
_START = _fixture["handshake"]["session/start"]
_NEW_TAB = {"lastEventId": 0, "state": cleared_state()}

# Startup start, then the Ctrl+X n start.
handshake = {"session/start": [_START, _NEW_TAB]}
request_methods = {"session/start"}
screen_contains = ("1 00000001", "2 00000003", "Ctrl+X tabs")
screen_excludes = ("Opening session",)

_CTRL_X = "\x18"

timeline: Timeline = [
    _CTRL_X,
    take_snapshot("chord_armed"),
    "n",
    take_snapshot("second_tab_opened"),
]
