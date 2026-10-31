"""Fork feature: `/resume` search ranks titles with fzf, then previews; letters type into the field."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline


def _session(index: int, title: str, preview: str) -> dict[str, object]:
    session_id = f"00000000-0000-4000-8000-{index:012d}"
    return {
        "id": session_id,
        "rootSessionId": session_id,
        "parentSessionId": None,
        "title": title,
        "preview": preview,
        "status": {"type": "idle"},
        "createdAt": 1_787_821_243_000 - index * 60_000,
        "updatedAt": 1_787_821_245_000 - index * 60_000,
        "cwd": "/workspace",
    }


handshake = {
    "session/list": {
        "items": [
            _session(1, "Fix the login redirect loop", "OAuth callback loops"),
            _session(2, "Move model discovery cache", "Cache under the temp dir"),
            _session(3, "Add dark mode to settings", "Theme toggle in config"),
            _session(4, "", "Investigate the flaky golden tests"),
        ],
        "nextCursor": None,
        "previousCursor": None,
    }
}
capture_startup = False
# `d` and `j` type into the field; a title term, then a verbatim preview term.
timeline: Timeline = [
    "/resume\r",
    "/",
    "disc cache",
    "\x1b",
    "\x1b",
    "/",
    "flaky",
    "\x1b",
    "\x1b",
]
screen_contains = ("Search sessions",)
