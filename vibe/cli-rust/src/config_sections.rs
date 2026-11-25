//! `/config` section order and headings; the server only sends section keys.

/// The settings-screen sections in display order. The client owns the labels
/// and this order; a newer server's unknown key sorts after the known ones,
/// ahead of "advanced" (ADR 0014).
pub const SECTION_ORDER: &[&str] = &[
    "popular",
    "fork",
    "models",
    "utility_models",
    "limits",
    "prompts",
    "voice",
    "tts",
    "tools",
    "mcp",
    "agents",
    "subagents",
    "approvals",
    "skills",
    "plugins",
    "appearance",
    "input",
    "safety",
    "telemetry",
    "worktrees",
    "network",
    "system",
    "experimental",
];

/// Where a section sits in the list: known keys by `SECTION_ORDER`, unknown
/// keys after them, "advanced" last.
pub fn section_rank(category: &str) -> usize {
    if category == "advanced" {
        usize::MAX
    } else {
        SECTION_ORDER
            .iter()
            .position(|key| *key == category)
            .unwrap_or(SECTION_ORDER.len())
    }
}

/// The heading drawn over a section.
pub fn section_label(category: &str) -> String {
    match category {
        "popular" => "Popular settings",
        "fork" => "Fork features",
        "models" => "Models",
        "utility_models" => "Utility models",
        "limits" => "Token limits",
        "prompts" => "Prompts & context",
        "voice" => "Voice",
        "tts" => "TTS",
        "tools" => "Tools",
        "mcp" => "MCP & connectors",
        "agents" => "Agents",
        "subagents" => "Subagents",
        "approvals" => "Approvals",
        "skills" => "Skills",
        "plugins" => "Plugins",
        "appearance" => "Appearance",
        "input" => "Input & editing",
        "safety" => "Safety",
        "telemetry" => "Telemetry & logging",
        "worktrees" => "Git & worktrees",
        "network" => "Network & API",
        "system" => "System & updates",
        "experimental" => "Experimental",
        "advanced" => "Advanced settings",
        other => other,
    }
    .to_owned()
}
