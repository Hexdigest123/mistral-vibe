"""`/tab new` opens a fresh session in a second tab; Ctrl+X then 1/2 switch between the used tabs."""

from __future__ import annotations

from e2e.app_server.events import turn_completed, turn_started
from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.session_tabs._tabs import (
    CTRL_X,
    FIRST_ID,
    SECOND_ID,
    START,
    answer,
    exchange,
)

# A tab nothing was run in is dropped when left, so each tab gets a turn first.
_first = exchange(FIRST_ID, "hi", "Hello.")
_second = exchange(SECOND_ID, "second", "Hi again.")

handshake = {
    "session/start": [START, answer(SECOND_ID)],
    "session/resume#" + FIRST_ID: answer(FIRST_ID, *_first),
    "session/resume#" + SECOND_ID: answer(SECOND_ID, *_second),
}
request_methods = {"session/start", "session/resume"}
screen_contains = ("1 00000001", "2 00000003", "Ctrl+X tabs", "Hi again.")
screen_excludes = ("Opening session", "Failed")

timeline: Timeline = [
    "hi\r",
    turn_started(),
    *_first,
    turn_completed(),
    "/tab new\r",
    take_snapshot("two_tabs"),
    "second\r",
    turn_started(SECOND_ID),
    *_second,
    turn_completed(session_id=SECOND_ID),
    CTRL_X,
    "1",
    take_snapshot("back_on_first"),
    CTRL_X,
    "2",
    take_snapshot("forward_again"),
]
