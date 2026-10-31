//! `/model` search: ranking by name, alias and provider, Default hidden, Esc leaves then clears.

use crossterm::event::KeyCode;
use vibe_rs::app::{App, ModelOption};
use vibe_rs::model_picker::{self, is_default_row, model_at, option_count, selected_alias};

use crate::support::{key, stub};

fn press(app: &mut App, code: KeyCode) {
    vibe_rs::input::handle_model_key(app, &stub(), key(code));
}

fn type_text(app: &mut App, text: &str) {
    text.chars().for_each(|c| press(app, KeyCode::Char(c)));
}

fn model(alias: &str, display_name: &str, provider: &str) -> ModelOption {
    ModelOption {
        alias: alias.into(),
        display_name: display_name.into(),
        name: alias.into(),
        provider: provider.into(),
        ..Default::default()
    }
}

fn picker() -> App {
    let mut app = App::default();
    app.model_picker.models = vec![
        model("mistral-medium", "Mistral Medium", "mistral"),
        model("qwen3-coder", "Qwen3 Coder", "openrouter"),
        model("devstral", "Devstral", "llamacpp"),
        model("glm-5", "GLM 5", "openrouter"),
    ];
    model_picker::open(&mut app);
    app
}

fn shown(app: &App) -> Vec<String> {
    (0..option_count(app))
        .map(|i| model_at(app, i).map_or("Default".into(), |m| m.alias.clone()))
        .collect()
}

#[test]
fn typing_without_slash_does_not_search() {
    let mut app = picker();
    press(&mut app, KeyCode::Char('j'));
    assert!(app.model_picker.search.query.is_empty());
    assert_eq!(app.model_picker.list.selected(), 1);
}

#[test]
fn a_query_hides_default_and_matches_any_field() {
    let mut app = picker();
    press(&mut app, KeyCode::Char('/'));
    type_text(&mut app, "openrouter");
    assert_eq!(shown(&app), ["qwen3-coder", "glm-5"]);
    assert!(!is_default_row(&app, 0));
    assert_eq!(selected_alias(&app), "qwen3-coder");
}

#[test]
fn best_match_ranks_first_and_s_types_into_the_field() {
    let mut app = picker();
    press(&mut app, KeyCode::Char('/'));
    type_text(&mut app, "devs");
    assert_eq!(shown(&app)[0], "devstral");
    assert_eq!(app.model_picker.search.query, "devs");
    assert!(app.model_picker.open);
}

#[test]
fn no_match_leaves_enter_inert() {
    let mut app = picker();
    press(&mut app, KeyCode::Char('/'));
    type_text(&mut app, "zzzz");
    assert_eq!(option_count(&app), 0);
    press(&mut app, KeyCode::Enter);
    assert!(app.model_picker.open);
}

#[test]
fn esc_leaves_then_clears_then_closes() {
    let mut app = picker();
    press(&mut app, KeyCode::Char('/'));
    type_text(&mut app, "glm");
    press(&mut app, KeyCode::Esc);
    assert!(!app.model_picker.search.focused);
    assert_eq!(shown(&app), ["glm-5"]);
    press(&mut app, KeyCode::Esc);
    assert_eq!(option_count(&app), 5);
    assert_eq!(app.model_picker.list.selected(), 0);
    press(&mut app, KeyCode::Esc);
    assert!(!app.model_picker.open);
}
