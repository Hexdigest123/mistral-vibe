"""The last sections of `/config` (Network, Experimental, Advanced) show readable names too."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.config._label_fixtures import READ

handshake = {"config/fields/read": READ}

screen_contains = (
    "Network & API",
    "API timeout",
    "Experimental",
    "Target runtime (experimental)",
    "Advanced settings",
    "Applied migrations",
)
screen_excludes = ("experimental_target_runtime", "applied_migrations")

# Up from the first row wraps to the last, which scrolls the list to its end.
timeline: Timeline = ["/config\r", "k", take_snapshot()]
