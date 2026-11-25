"""Switching back to a tab whose turn still runs re-attaches it live: the loader shows and no poll is needed."""

from __future__ import annotations

from e2e.app_server.events import assistant_msg, turn_completed, turn_started, user_msg
from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.session_tabs._tabs import (
    CTRL_X,
    FIRST_ID,
    SECOND_ID,
    START,
    answer,
    exchange,
)

_first = exchange(FIRST_ID, "hi", "Working on it.")
_second = exchange(SECOND_ID, "second", "Hi.")

handshake = {
    "session/start": [START, answer(SECOND_ID)],
    # The parked session still runs: its resume answers with the running turn.
    "session/resume#" + FIRST_ID: answer(FIRST_ID, *_first, running=True),
    "session/resume#" + SECOND_ID: answer(SECOND_ID, *_second),
}
request_methods = {"session/start", "session/resume"}
screen_contains = ("1 ● 00000001", "2 00000003", "Hi.")
screen_excludes = ("Opening session", "Failed")

timeline: Timeline = [
    "hi\r",
    turn_started(),
    user_msg("hi"),
    assistant_msg("Working on it.", generation_status="in_progress"),
    "/tab new\r",
    "second\r",
    turn_started(SECOND_ID),
    *_second,
    turn_completed(session_id=SECOND_ID),
    CTRL_X,
    "1",
    take_snapshot("back_on_running_tab"),
    # And away again while it runs: the second tab re-attaches idle.
    CTRL_X,
    "2",
    take_snapshot("away_again"),
]
