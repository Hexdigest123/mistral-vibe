"""`/config` lists readable setting names in the finer sections, never the raw keys."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.config._label_fixtures import READ

handshake = {"config/fields/read": READ}

screen_contains = (
    "MCP & connectors",
    "Enable MCP",
    "Document library connector (experimental)",
    "Subagents",
    "Max concurrent subagents",
    "Approvals",
    "Default approval policy",
    "Telemetry & logging",
    "Enable OTel",
)
screen_excludes = ("max_concurrent_subagents", "experimental_enable_document_library_connector")

timeline: Timeline = ["/config\r", take_snapshot()]
