"""Ctrl+X then n opens a second tab even when only one tab exists yet."""

from __future__ import annotations

from e2e.app_server.events import turn_completed, turn_started
from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.session_tabs._tabs import CTRL_X, FIRST_ID, SECOND_ID, START, answer, exchange

# Startup start, then the Ctrl+X n start.
handshake = {"session/start": [START, answer(SECOND_ID)]}
request_methods = {"session/start"}
screen_contains = ("1 00000001", "2 00000003", "Ctrl+X tabs")
screen_excludes = ("Opening session",)

timeline: Timeline = [
    # The first tab is used: a tab nothing was run in would be dropped for the new one.
    "hi\r",
    turn_started(),
    *exchange(FIRST_ID, "hi", "Hello."),
    turn_completed(),
    CTRL_X,
    take_snapshot("chord_armed"),
    "n",
    take_snapshot("second_tab_opened"),
]
