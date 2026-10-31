//! `/model` picker state: a Default row plus one row per model, fzf-searchable by name, alias and
//! provider (fork feature, AGENTS.md). A pick chains straight into `/thinking`, which writes both.

use std::sync::Arc;

use crossterm::event::{KeyEvent, MouseButton, MouseEvent, MouseEventKind};
use serde_json::Value;

use crate::app::{App, ModelOption, ToastSeverity};
use crate::config_write::Scope;
use crate::event_handler;
use crate::option_list::OptionList;
use crate::search_field::{self, Outcome};
use crate::server::Client;
use crate::thinking_picker::{self, ModelPick, THINKING_LEVELS};
use crate::utils::fzf;

/// Alias persisted for the Default (unpinned) row.
pub const UNPINNED_ACTIVE_MODEL: &str = "";

/// A `/config` field write's server answer, applied on the main thread.
pub enum Event {
    /// Runtime returned by `config/write`.
    Written(Value),
    /// The write failed; the message names the field and the server's reason.
    Failed(String),
}

pub(crate) const FAILED_TOAST_SECS: u64 = 8;

/// Apply the server's answer and release the commit that was in flight.
pub fn apply_event(app: &mut App, event: Event) {
    match event {
        Event::Written(runtime) => event_handler::apply_runtime_value(app, &runtime),
        Event::Failed(message) => app.show_toast(message, ToastSeverity::Error, FAILED_TOAST_SECS),
    }
}

/// Hand the highlighted model to the thinking picker, opened at once on its
/// levels; nothing is written until that picker commits or is dismissed. A
/// model that cannot be resolved has no levels to offer and is written alone.
pub fn select(app: &mut App, client: &Arc<Client>, scope: Scope) {
    if option_count(app) == 0 {
        return;
    }
    let alias = selected_alias(app);
    app.model_picker.open = false;
    let target = match alias.as_str() {
        UNPINNED_ACTIVE_MODEL => app.model_picker.default_alias.clone(),
        _ => alias.clone(),
    };
    let option = app.model_picker.models.iter().find(|m| m.alias == target);
    let Some((thinking, levels)) = option.map(|m| (m.thinking.clone(), m.thinking_levels.clone()))
    else {
        let pick = ModelPick {
            alias,
            target: String::new(),
            scope,
        };
        thinking_picker::commit_model(app, client, &pick);
        return;
    };
    let pick = ModelPick {
        alias,
        target,
        scope,
    };
    thinking_picker::open_for_model(app, pick, thinking, levels);
}

/// Open the picker highlighted on the current choice, with an empty search.
pub fn open(app: &mut App) {
    search_field::clear(&mut app.model_picker.search);
    app.model_picker.list = OptionList::new(current_index(app));
    app.model_picker.open = true;
}

/// Route a key through the search field first; returns whether it consumed the key.
pub fn search_key(app: &mut App, key: &KeyEvent) -> bool {
    match search_field::handle_key(&mut app.model_picker.search, key) {
        Outcome::Pass => false,
        Outcome::Consumed => true,
        Outcome::Filtered => {
            refilter(app);
            true
        }
    }
}

/// Insert pasted text into the focused search field.
pub fn paste(app: &mut App, text: &str) {
    if search_field::paste(&mut app.model_picker.search, text) {
        refilter(app);
    }
}

/// A press on the search field focuses it; one on a row leaves the field. True when consumed.
pub fn search_click(app: &mut App, event: MouseEvent) -> bool {
    if event.kind != MouseEventKind::Down(MouseButton::Left) {
        return false;
    }
    let at = (event.column, event.row);
    let picker = &mut app.model_picker;
    if picker.search.area.contains(at.into()) {
        picker.search.focused = true;
        return true;
    }
    if picker.list.index_at(at).is_some() {
        picker.search.focused = false;
    }
    false
}

/// Re-rank models for the query and highlight the best match (the current choice when cleared).
fn refilter(app: &mut App) {
    rank(app);
    let first = match query(app).is_empty() {
        true => current_index(app),
        false => 0,
    };
    app.model_picker.list = OptionList::new(first);
}

/// Recompute `matches`: fzf over each model's display name, alias, id and provider, best first.
fn rank(app: &mut App) {
    let query = query(app).to_owned();
    let picker = &mut app.model_picker;
    picker.matches = match query.is_empty() {
        true => Vec::new(),
        false => fzf::rank(&picker.models, &query, haystack, |_| ""),
    };
}

/// One line per model, so terms can match across fields (`openrouter gpt`).
fn haystack(model: &ModelOption) -> String {
    fzf::haystack([
        model.display_name.as_str(),
        &model.alias,
        &model.name,
        &model.provider,
    ])
}

fn query(app: &App) -> &str {
    app.model_picker.search.query.trim()
}

/// The model shown on row `i`, or `None` for the Default row (only listed without a query).
pub fn model_at(app: &App, i: usize) -> Option<&ModelOption> {
    let picker = &app.model_picker;
    let index = match query(app).is_empty() {
        true => i.checked_sub(1)?,
        false => *picker.matches.get(i)?,
    };
    picker.models.get(index)
}

/// Whether row `i` is the Default (unpinned) row.
pub fn is_default_row(app: &App, i: usize) -> bool {
    i == 0 && query(app).is_empty()
}

/// Pre-selected row: pinned model `+1` (offset by Default), else `0` (Default).
fn current_index(app: &App) -> usize {
    if app.model_picker.is_pinned {
        if let Some(i) = model_index(app) {
            return i + 1;
        }
    }
    0
}

/// Index into `models` of the currently active alias, if any.
fn model_index(app: &App) -> Option<usize> {
    app.model_picker
        .models
        .iter()
        .position(|m| m.alias == app.model_picker.current_model)
}

/// Row count: the Default row plus one per model, or the matches while searching.
pub fn option_count(app: &App) -> usize {
    match query(app).is_empty() {
        true => app.model_picker.models.len() + 1,
        false => app.model_picker.matches.len(),
    }
}

/// Move the highlight up/down by one, wrapping at the ends.
pub fn navigate(app: &mut App, down: bool) {
    let count = option_count(app);
    app.model_picker.list.step(down, count, true, |_| true);
}

/// Whether row `i` is the current choice: Default when unpinned, else the pinned model.
pub fn is_current(app: &App, i: usize) -> bool {
    if is_default_row(app, i) {
        return !app.model_picker.is_pinned;
    }
    app.model_picker.is_pinned
        && model_at(app, i).is_some_and(|m| m.alias == app.model_picker.current_model)
}

/// The alias to persist for the highlighted row (`""` for Default).
pub fn selected_alias(app: &App) -> String {
    let sel = app.model_picker.list.selected();
    match is_default_row(app, sel) {
        true => UNPINNED_ACTIVE_MODEL.to_owned(),
        false => model_at(app, sel)
            .map(|m| m.alias.clone())
            .unwrap_or_default(),
    }
}

/// Close the picker without persisting (Esc / cancel).
pub fn cancel(app: &mut App) {
    app.model_picker.open = false;
}

/// Refresh the model snapshot from a `runtime/read`/`runtime/updated` value
/// (shape `{runtime: {config: {...}}}`), so the picker reflects live config.
pub fn apply_runtime(app: &mut App, response: &Value) {
    let Some(config) = crate::server::RuntimeSnapshot::config(response) else {
        return;
    };
    let models: Vec<ModelOption> = config.models.into_iter().filter_map(model_option).collect();
    let alias = config.default_model_alias;
    app.model_picker.default_display_name = models
        .iter()
        .find(|model| model.alias == alias)
        .map_or_else(|| alias.clone(), |model| model.display_name.clone());
    app.model_picker.models = models;
    app.model_picker.current_model = config.active_model.map(|m| m.alias).unwrap_or_default();
    app.model_picker.is_pinned = config.active_model_pinned;
    app.model_picker.default_alias = alias;
    rank(app);
    if app.model_picker.list.selected() >= option_count(app) {
        app.model_picker.list = OptionList::new(0);
    }
}

fn model_option(model: crate::server::ModelView) -> Option<ModelOption> {
    if model.alias.is_empty() {
        return None;
    }
    // Older servers omit the per-model set; fall back to the canonical five (ADR 0014).
    let thinking_levels = match model.thinking_levels.is_empty() {
        true => THINKING_LEVELS.iter().map(|it| it.to_string()).collect(),
        false => model.thinking_levels,
    };
    Some(ModelOption {
        display_name: model.display_name.unwrap_or_else(|| model.alias.clone()),
        alias: model.alias,
        name: model.name,
        provider: model.provider,
        thinking: model.thinking.unwrap_or_default(),
        thinking_levels,
    })
}
