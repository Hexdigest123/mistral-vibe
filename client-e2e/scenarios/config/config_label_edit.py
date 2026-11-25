"""A setting is found by its raw key, shown by its label, and its editor names both."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.slash_command._config_fixtures import field, fields_read

handshake = {
    "config/fields/read": fields_read(
        field("theme", "str", "dark", category="popular"),
        field("max_concurrent_subagents", "int", 4, popular=False, category="subagents"),
        field("api_timeout", "int", 720, popular=False, category="network"),
    )
}

screen_contains = ("Max concurrent subagents", "max_concurrent_subagents", "WHERE IT'S SET")
screen_excludes = ("API timeout",)

# Search the raw key (the list keeps only the label), open the editor, then search the label.
timeline: Timeline = [
    "/config\r",
    "/max_conc",
    take_snapshot("raw_key_search"),
    "\r",
    take_snapshot("editor"),
]
