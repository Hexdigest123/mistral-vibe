//! `/model` picker state: a Default row plus one row per model, fzf-searchable by name, alias,
//! id and provider (fork feature, AGENTS.md). A pick chains straight into `/thinking`, which writes both.

use std::sync::Arc;

use crossterm::event::{KeyEvent, MouseButton, MouseEvent, MouseEventKind};
use serde_json::Value;

use crate::app::{App, ModelOption, Severity};
use crate::config_write::Scope;
use crate::event_handler;
use crate::option_list::OptionList;
use crate::search_field::{self, Outcome};
use crate::server::Client;
use crate::thinking_picker::{self, ModelPick, THINKING_LEVELS};
use crate::utils::fzf;

pub mod catalog_check;
pub use catalog_check::CHECKING_LABEL;

/// Alias persisted for the Default (unpinned) row.
pub const UNPINNED_ACTIVE_MODEL: &str = "";

/// Label of the Default row, and its search text.
pub const DEFAULT_LABEL: &str = "Default";
/// Row shown when the filter matches nothing.
pub const NO_MATCHES_LABEL: &str = "No matching models";

/// One visible row of the picker.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Row {
    /// The unpinned Default entry.
    Default,
    /// A model of `ModelPicker::models`.
    Model(usize),
    /// The filter matched nothing; cannot take the highlight.
    Note,
}

impl Row {
    pub fn selectable(&self) -> bool {
        !matches!(self, Self::Note)
    }
}

/// A `/config` field write's server answer, applied on the main thread.
pub enum Event {
    /// Runtime returned by `config/write`.
    Written(Value),
    /// The write failed; the message names the field and the server's reason.
    Failed(String),
    /// The catalog check opening the picker answered, whatever its outcome.
    Checked,
}

/// Apply the server's answer.
pub fn apply_event(app: &mut App, event: Event) {
    match event {
        Event::Written(runtime) => event_handler::apply_runtime_value(app, &runtime),
        Event::Failed(message) => crate::notices::inline(app, Severity::Error, &message),
        Event::Checked => {
            app.model_picker.checks_in_flight = app.model_picker.checks_in_flight.saturating_sub(1);
        }
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
    let searched = !query(app).is_empty();
    app.model_picker.open = false;
    app.model_picker.search = search_field::Search::default();
    app.model_picker.matches.clear();
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
            searched,
        };
        thinking_picker::commit_model(app, client, &pick);
        return;
    };
    let pick = ModelPick {
        alias,
        target,
        scope,
        searched,
    };
    thinking_picker::open_for_model(app, pick, thinking, levels);
}

/// Open the picker highlighted on the current choice, with an empty search.
pub fn open(app: &mut App) {
    search_field::clear(&mut app.model_picker.search);
    app.model_picker.list = OptionList::new(current_index(app));
    app.model_picker.open = true;
}

/// Open the picker highlighted on the current choice, and check the catalog
/// for models a plan upgrade unlocked.
pub fn open_with_catalog_check(app: &mut App, client: &Arc<Client>) {
    open(app);
    crate::model_selection::opened(app, crate::model_selection::Picker::Model);
    catalog_check::start(app, client);
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

/// Same, under the shared search-field name used by the other pickers.
pub fn paste_search(app: &mut App, text: &str) {
    paste(app, text);
}

/// Route a key through the search field first; same as `search_key`.
pub fn handle_search_key(app: &mut App, key: &KeyEvent) -> bool {
    search_key(app, key)
}

/// Focus the search field from a click on the search row.
pub fn focus_search(app: &mut App) {
    app.model_picker.search.focused = true;
    app.model_picker.list.reset_viewport();
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

/// The visible rows: with an empty query the Default row then every model in
/// config order; with a query the matches, best first, or a single note row.
pub fn rows(app: &App) -> Vec<Row> {
    match query(app).is_empty() {
        true => std::iter::once(Row::Default)
            .chain((0..app.model_picker.models.len()).map(Row::Model))
            .collect(),
        false => match app.model_picker.matches.is_empty() {
            true => vec![Row::Note],
            false => app
                .model_picker
                .matches
                .iter()
                .map(|&i| Row::Model(i))
                .collect(),
        },
    }
}

/// The current choice's row: Default when unpinned, else the pinned model's.
pub fn current_row(app: &App) -> Option<Row> {
    match app.model_picker.is_pinned {
        false => Some(Row::Default),
        true => model_index(app).map(Row::Model),
    }
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
    app.model_picker.search = search_field::Search::default();
    app.model_picker.matches.clear();
}

/// Refresh the model snapshot from a `runtime/read`/`runtime/updated` value
/// (shape `{runtime: {config: {...}}}`), so the picker reflects live config.
pub fn apply_runtime(app: &mut App, response: &Value) {
    let Some(config) = crate::server::RuntimeSnapshot::config(response) else {
        return;
    };
    let highlighted = app.model_picker.open.then(|| selected_alias(app));
    app.model_picker.has_locked_models = config.models.iter().any(|m| m.requires.is_some());
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
    if app.model_picker.open {
        keep_highlight(app, highlighted.as_deref());
    } else if app.model_picker.list.selected() >= option_count(app) {
        app.model_picker.list = OptionList::new(0);
    }
}

/// After the list changed under the open picker, highlight the row that was
/// highlighted, or the nearest one.
fn keep_highlight(app: &mut App, alias: Option<&str>) {
    let count = option_count(app);
    let index = match query(app).is_empty() {
        true => match alias {
            None => None,
            Some(a) if a == UNPINNED_ACTIVE_MODEL => Some(0),
            Some(a) => app
                .model_picker
                .models
                .iter()
                .position(|m| m.alias == a)
                .map(|i| i + 1),
        },
        false => app
            .model_picker
            .matches
            .iter()
            .position(|&i| app.model_picker.models[i].alias == alias.unwrap_or_default()),
    };
    let selected = app.model_picker.list.selected();
    match index {
        Some(index) => app.model_picker.list.highlight(index),
        None if selected >= count => app.model_picker.list.select(count.saturating_sub(1)),
        None => {}
    }
}

fn model_option(model: crate::server::ModelView) -> Option<ModelOption> {
    if model.alias.is_empty() || model.requires.is_some() {
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
