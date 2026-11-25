"""Settings across the finer `/config` sections, shared by the label scenarios."""

from __future__ import annotations

from scenarios.slash_command._config_fixtures import field, fields_read

READ = fields_read(
    field("theme", "str", "dark", category="popular"),
    field("enable_mcp", "bool", True, popular=False, category="mcp"),
    field(
        "experimental_enable_document_library_connector",
        "bool",
        False,
        popular=False,
        category="mcp",
    ),
    field("max_concurrent_subagents", "int", 4, popular=False, category="subagents"),
    field("default_approval_policy", "str", "ask", popular=False, category="approvals"),
    field("enable_otel", "bool", False, popular=False, category="telemetry"),
    field("otel_endpoint", "str", "", popular=False, category="telemetry"),
    field("api_timeout", "int", 720, popular=False, category="network"),
    field("experimental_target_runtime", "bool", False, popular=False, category="experimental"),
    field("applied_migrations", "list", [], popular=False, category="advanced"),
)
