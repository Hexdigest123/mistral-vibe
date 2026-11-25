//! `/config` shows readable setting names; search still matches the raw keys.

use serde_json::json;
use vibe_rs::app::App;
use vibe_rs::config_label::humanize;
use vibe_rs::{config, config_fields};

fn app_with(names: &[&str], query: &str) -> App {
    let mut app = App::default();
    let loaded = config_fields::parse(&json!({
        "fields": names.iter().map(|name| json!({
            "name": name, "path": format!("/{name}"), "kind": "int", "value": 1,
        })).collect::<Vec<_>>(),
    }));
    config::apply_loaded(&mut app, loaded);
    app.config_screen.search.query = query.into();
    app
}

fn labels(app: &App) -> Vec<String> {
    config::filtered(app).iter().map(|f| f.label()).collect()
}

#[test]
fn snake_case_reads_as_a_sentence() {
    assert_eq!(
        humanize("max_concurrent_subagents"),
        "Max concurrent subagents"
    );
    assert_eq!(humanize("theme"), "Theme");
    assert_eq!(
        humanize("disable_welcome_banner_animation"),
        "Disable welcome banner animation"
    );
    assert_eq!(humanize("enable_session_tabs"), "Enable session tabs");
}

#[test]
fn experimental_settings_trade_their_prefix_for_a_suffix() {
    assert_eq!(
        humanize("experimental_enable_document_library_connector"),
        "Document library connector (experimental)"
    );
    assert_eq!(
        humanize("experimental_target_runtime"),
        "Target runtime (experimental)"
    );
    assert_eq!(humanize("experimental"), "Experimental");
    assert_eq!(humanize("experimental_enable"), "Enable (experimental)");
}

#[test]
fn acronyms_keep_their_casing_anywhere() {
    assert_eq!(humanize("enable_mcp"), "Enable MCP");
    assert_eq!(humanize("otel_endpoint"), "OTel endpoint");
    assert_eq!(humanize("tts_models"), "TTS models");
    assert_eq!(humanize("vibe_base_url"), "Vibe base URL");
    assert_eq!(
        humanize("api_retry_max_elapsed_time"),
        "API retry max elapsed time"
    );
    assert_eq!(humanize("system_prompt_id"), "System prompt ID");
    assert_eq!(humanize("enable_pr_monitoring"), "Enable PR monitoring");
    assert_eq!(humanize("mcp_servers"), "MCP servers");
    assert_eq!(
        humanize("experimental_local_runtime_session_api"),
        "Local runtime session API (experimental)"
    );
}

#[test]
fn odd_keys_never_come_out_empty() {
    assert_eq!(humanize("__"), "__");
    assert_eq!(humanize(""), "");
    assert_eq!(humanize("_leading__double_"), "Leading double");
}

#[test]
fn search_matches_the_label_and_the_raw_key() {
    let names = ["max_concurrent_subagents", "api_timeout", "theme"];
    let by_label = app_with(&names, "concurrent subagents");
    assert_eq!(labels(&by_label), ["Max concurrent subagents"]);
    let by_key = app_with(&names, "max_concurrent");
    assert_eq!(labels(&by_key), ["Max concurrent subagents"]);
    let by_acronym = app_with(&names, "'API timeout");
    assert_eq!(labels(&by_acronym), ["API timeout"]);
}

#[test]
fn the_raw_key_stays_the_written_identity() {
    let app = app_with(&["experimental_enable_tab_status"], "");
    let field = &config::filtered(&app)[0];
    assert_eq!(field.label(), "Tab status (experimental)");
    assert_eq!(field.name, "experimental_enable_tab_status");
    assert_eq!(field.path, "/experimental_enable_tab_status");
}
