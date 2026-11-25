"""The bottom bar shows the turn's TTFT and tok/s after the context gauge, summing per-entry decode windows so tool time between entries is excluded."""

from __future__ import annotations

from e2e.app_server.config import COLUMNS, ROWS
from e2e.app_server.events import (
    SESSION_ID,
    assistant_delta,
    assistant_msg,
    complete_entry,
    turn_completed,
    turn_started,
    user_msg,
)
from e2e.app_server.scenario import AppServerEvent, Timeline, advance, take_snapshot

_A = "pace-a"
_B = "pace-b"
_PROMPT = "pace"


def _stats(completion_tokens: int) -> AppServerEvent:
    """A `session/statsUpdated` whose last turn reported exact completion tokens."""
    return {
        "method": "session/statsUpdated",
        "params": {
            "sessionId": SESSION_ID,
            "emittedAt": 1_787_593_260_000,
            "stats": {
                "contextTokens": 0,
                "lastTurnCompletionTokens": completion_tokens,
            },
            "contextWindow": 600_000,
        },
    }


_LEFT = "/test/workdir"
_RIGHT = "ctx        0/600k · 0.8s ttft · 20.0 tok/s"
screen_rows = {ROWS - 1: _LEFT.ljust(COLUMNS - len(_RIGHT)) + _RIGHT}

# One enqueue releases the whole batch; the releases drip it around the advances. Entry A
# streams at 800 ms..2000 ms, then a 6 s tool gap, then entry B at 8000 ms..9200 ms: the summed
# per-entry decode windows are 1.2 s + 1.2 s = 2.4 s for 192 chars (48 estimated tokens, and the
# turn's 48 exact completion tokens agree), so 20.0 tok/s -- the gap is not provider time.
timeline: Timeline = [
    f"{_PROMPT}\r",
    turn_started(),
    user_msg(_PROMPT),
    assistant_msg("a" * 48, entry_id=_A, generation_status="in_progress"),
    assistant_delta(_A, "b" * 48),
    complete_entry(_A),
    assistant_msg("c" * 48, entry_id=_B, generation_status="in_progress"),
    assistant_delta(_B, "d" * 48),
    complete_entry(_B),
    turn_completed(),
    _stats(48),
    {"release": 3},
    advance(800),
    {"release": 1},
    advance(1200),
    {"release": 1},
    advance(6000),
    {"release": 2},
    advance(1200),
    {"release": 2},
    take_snapshot("streaming"),
    {"release": 2},
    take_snapshot("completed"),
]
