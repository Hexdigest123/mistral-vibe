//! Starting a tab switch: save the tab left, paint the tab switched to, ask
//! the app-server to resume or start its session, and settle on the answer.
//! The in-flight state rides the Sessions page's `switching` record, so every
//! gate that blocks a session switch (input, Esc, Ctrl+C) blocks a tab switch.

use std::sync::Arc;

use crate::app::{App, Severity};
use crate::server::{AgentConfig, Client};
use crate::sessions_page::{requests, Switching};
use crate::ui::loading::OPENING_SESSION_STATUS;

use super::{switching, TabSnapshot, BUSY};

/// The agent config a new tab's session opens with: the current one, minus a
/// pinned worktree (a tab is not a worktree run).
fn config_for_new(app: &App) -> AgentConfig {
    let mut config = app.session.agent_config.clone();
    config.worktree = None;
    config
}

/// Switch to tab `to`: save the active tab, show the target's saved view, and
/// send the resume/start request. The answer lands in `super::on_session_id`.
pub(super) fn start(app: &mut App, client: &Arc<Client>, to: usize) {
    if !app.session_tabs.enabled
        || to >= app.session_tabs.list.len()
        || to == app.session_tabs.active
        || app.sessions_page.switching.is_some()
        || switching(app)
    {
        return;
    }
    if !crate::sessions_page::idle(app) {
        crate::notices::inline(app, Severity::Warning, BUSY);
        return;
    }
    let from = app.session_tabs.active;
    let snapshot = TabSnapshot {
        transcript: app.view.transcript.snapshot(),
        scroll: (app.view.scroll, app.view.scroll_target),
        draft: app.chat_input.input.clone(),
        cursor: app.chat_input.cursor,
    };
    app.session_tabs.list[from].snapshot = Some(snapshot.clone());
    app.session_tabs.pending = Some((from, to));
    let id = app.session_tabs.list[to]
        .session_id
        .clone()
        .unwrap_or_default();
    app.sessions_page.busy = Some(id.clone());
    app.sessions_page.ticket += 1;
    let ticket = app.sessions_page.ticket;
    app.sessions_page.switching = Some(Switching {
        id: id.clone(),
        previous: snapshot.transcript.clone(),
        scroll: snapshot.scroll,
        from_page: false,
    });
    // Paint the target tab at once, until the opened session's history lands.
    match &app.session_tabs.list[to].snapshot {
        Some(saved) => {
            app.view.transcript.restore(saved.transcript.clone());
            (app.view.scroll, app.view.scroll_target) = saved.scroll;
        }
        None => {
            app.view.transcript.clear();
            app.view.scroll = 0;
            app.view.scroll_target = 0;
        }
    }
    app.view.transcript_cache.invalidate_layouts();
    let (draft, cursor) = app.session_tabs.list[to]
        .snapshot
        .as_ref()
        .map(|saved| (saved.draft.clone(), saved.cursor))
        .unwrap_or_default();
    restore_draft(app, &draft, cursor);
    if app.begin_command_loading() {
        app.view.loading.set_label(OPENING_SESSION_STATUS);
    }
    if app.session_tabs.list[to].session_id.is_some() {
        requests::resume(app, client, id, config_for_new(app), ticket);
    } else {
        requests::start(app, client, config_for_new(app), ticket);
    }
}

/// Put a tab's draft back into the composer.
pub(super) fn restore_draft(app: &mut App, draft: &str, cursor: usize) {
    app.chat_input.input = draft.to_owned();
    app.chat_input.cursor = cursor;
    app.chat_input.anchor = None;
    app.chat_input.normalize_positions();
    crate::input::reset_history_state(app);
    crate::completion_manager::input_changed(app);
}
