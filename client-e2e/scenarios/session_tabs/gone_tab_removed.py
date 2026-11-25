"""A tab switch whose resume answers session_not_found removes the dead tab and says so."""

from __future__ import annotations

from e2e.app_server.events import turn_completed, turn_started
from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.session_tabs._tabs import CTRL_X, FIRST_ID, SECOND_ID, START, answer, exchange

_GONE = {
    "error": {
        "code": "not_found",
        "message": f"Session not found: {FIRST_ID}",
        "data": {"harnessCode": "session_not_found", "sessionId": FIRST_ID},
    }
}

handshake = {
    "session/start": [START, answer(SECOND_ID)],
    "session/resume#" + FIRST_ID: _GONE,
}
request_methods = {"session/start", "session/resume"}
# The dead tab is gone (one tab left, so the bar hides) and the notice is the
# friendly one, not the raw server message.
screen_contains = ("That session no longer exists.",)
screen_excludes = ("Failed to resume session", "00000001", "Ctrl+X tabs")

timeline: Timeline = [
    # The first tab is used, so it stays in the bar until its resume fails.
    "hi\r",
    turn_started(),
    *exchange(FIRST_ID, "hi", "Hello."),
    turn_completed(),
    "/tab new\r",
    CTRL_X,
    "1",
    take_snapshot("dead_tab_removed"),
]
