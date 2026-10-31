"""Drag the config choice scrollbar to reveal models beyond the first viewport."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline

models = [
    {
        "name": f"model-{index}",
        "alias": f"model-{index}",
        "thinking": "off",
        "supportsImages": False,
        "displayName": f"Model {index}",
    }
    for index in range(30)
]
handshake = {
    "config/read": {"config": {"models": models}},
    "runtime/read": {"runtime": {"config": {"models": models}}},
}

capture_startup = False
screen_contains = ("Model 28",)
screen_excludes = ("Model 29", "default (currently")
timeline: Timeline = [
    "/config\r",
    "\r",
    # Rows sit one lower than without search: the choice list's search row.
    "\x1b[<0;59;12M",
    "\x1b[<32;59;40M",
    "\x1b[<0;59;40m",
    "\x1b[<65;40;19M",
    "\x1b[<64;40;19M",
]
