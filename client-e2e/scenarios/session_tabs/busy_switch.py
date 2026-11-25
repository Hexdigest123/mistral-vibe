"""A tab opens while a turn runs; the busy tab is marked, then marked done once a poll sees its turn end."""

from __future__ import annotations

from e2e.app_server.events import assistant_msg, turn_completed, turn_started, user_msg
from e2e.app_server.scenario import Timeline, advance, take_snapshot
from scenarios.session_tabs._tabs import (
    CTRL_X,
    FIRST_ID,
    SECOND_ID,
    START,
    answer,
    exchange,
    listed,
)

_first = exchange(FIRST_ID, "hi", "All done.")
_second = exchange(SECOND_ID, "second", "Hi.")

handshake = {
    "session/start": [START, answer(SECOND_ID)],
    "session/resume#" + FIRST_ID: answer(FIRST_ID, *_first),
    # The listing startup reads, then the first poll finds the turn running, the second finds it ended.
    "session/list": [
        listed(),
        listed((FIRST_ID, "running")),
        listed((FIRST_ID, "idle")),
    ],
}
request_methods = {"session/start", "session/resume", "session/list"}
screen_contains = ("1 00000001", "2 00000003", "Ctrl+X tabs")
screen_excludes = ("Opening session", "Failed")

timeline: Timeline = [
    "hi\r",
    turn_started(),
    user_msg("hi"),
    assistant_msg("Working on it.", generation_status="in_progress"),
    # The turn still runs: the new tab opens at once, with no wait for its end.
    "/tab new\r",
    take_snapshot("opened_while_running"),
    "second\r",
    turn_started(SECOND_ID),
    *_second,
    turn_completed(session_id=SECOND_ID),
    advance(3000),
    take_snapshot("still_running"),
    advance(3000),
    take_snapshot("done_in_background"),
    # Back on the first tab: its mark clears and its finished history shows.
    CTRL_X,
    "1",
    take_snapshot("back_on_first"),
]
