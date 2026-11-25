//! `/config` rows group into the server's category sections, ordered client-side.

use serde_json::json;
use vibe_rs::app::App;
use vibe_rs::config_fields::{section_label, section_rank};
use vibe_rs::{config, config_fields};

fn app_with(fields: &[(&str, &str, bool)]) -> App {
    let mut app = App::default();
    let loaded = config_fields::parse(&json!({
        "fields": fields.iter().map(|(name, category, popular)| json!({
            "name": name, "path": format!("/{name}"), "kind": "int", "value": 42,
            "popular": popular, "category": category,
        })).collect::<Vec<_>>(),
    }));
    config::apply_loaded(&mut app, loaded);
    app
}

fn names(app: &App) -> Vec<&str> {
    config::filtered(app)
        .into_iter()
        .map(|field| field.name.as_str())
        .collect()
}

#[test]
fn empty_query_orders_rows_by_section_rank() {
    let app = app_with(&[
        ("api_timeout", "advanced", false),
        ("tts_models", "tts", false),
        ("theme", "popular", true),
        ("disable_all_telemetry", "fork", false),
        ("active_transcribe_model", "voice", false),
        ("providers", "models", false),
    ]);
    assert_eq!(
        names(&app),
        [
            "theme",
            "disable_all_telemetry",
            "providers",
            "active_transcribe_model",
            "tts_models",
            "api_timeout"
        ]
    );
}

#[test]
fn missing_category_falls_back_to_the_popular_flag() {
    let app = app_with(&[("z_old", "", false), ("a_old", "", true)]);
    let loaded = config::filtered(&app);
    assert_eq!(loaded[0].name, "a_old");
    assert_eq!(loaded[0].category, "popular");
    assert_eq!(loaded[1].category, "advanced");
}

#[test]
fn unknown_category_sorts_after_known_sections_before_advanced() {
    assert!(section_rank("worktrees") < section_rank("brand_new_section"));
    assert!(section_rank("brand_new_section") < section_rank("advanced"));
    assert_eq!(section_label("brand_new_section"), "brand_new_section");
}

#[test]
fn section_labels_match_the_known_keys() {
    assert_eq!(section_label("popular"), "Popular settings");
    assert_eq!(section_label("fork"), "Fork features");
    assert_eq!(section_label("tts"), "TTS");
    assert_eq!(section_label("voice"), "Voice");
    assert_eq!(section_label("advanced"), "Advanced settings");
}
