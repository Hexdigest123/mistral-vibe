"""A tab nothing was run in is dropped from the bar when the user leaves it, as the server drops its session."""

from __future__ import annotations

from e2e.app_server.events import turn_completed, turn_started
from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.session_tabs._tabs import (
    CTRL_X,
    SECOND_ID,
    START,
    THIRD_ID,
    answer,
    exchange,
)

_second = exchange(SECOND_ID, "hello", "Hi.")

handshake = {
    "session/start": [START, answer(SECOND_ID), answer(THIRD_ID)],
    "session/resume#" + SECOND_ID: answer(SECOND_ID, *_second),
}
request_methods = {"session/start", "session/resume"}
screen_contains = ("Hi.", "Closed the empty tab 2")
screen_excludes = ("Ctrl+X tabs", "00000004", "Failed")

timeline: Timeline = [
    # The never-used first tab is replaced by the new one: the bar has one tab, so it hides.
    "/tab new\r",
    take_snapshot("first_tab_dropped"),
    "hello\r",
    turn_started(SECOND_ID),
    *_second,
    turn_completed(session_id=SECOND_ID),
    # A second tab nothing is run in: back on the first, it is dropped too.
    "/tab new\r",
    take_snapshot("second_tab_open"),
    CTRL_X,
    "1",
    take_snapshot("empty_second_dropped"),
    # The tab it was is gone: the chord does nothing.
    CTRL_X,
    "2",
]
