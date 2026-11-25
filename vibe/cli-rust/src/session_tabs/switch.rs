//! Starting a tab switch: save the tab left, paint the tab switched to, ask
//! the app-server to resume or start its session, and settle on the answer.
//! The in-flight state rides the Sessions page's `switching` record, so every
//! gate that blocks a session switch (input, Esc, Ctrl+C) blocks a tab switch.

use std::sync::Arc;

use crate::app::{App, Severity};
use crate::server::{AgentConfig, Client};
use crate::sessions_page::{requests, Switching};
use crate::ui::loading::OPENING_SESSION_STATUS;

use super::{actions, switching, Activity, TabSnapshot};

/// Say the empty tab at `index` was dropped: the server drops a session nothing was run in.
pub(super) fn say_empty(app: &mut App, index: usize) {
    let text = format!(
        "Closed the empty tab {}: nothing was written in it.",
        index + 1
    );
    crate::ui::notice::show(app, Severity::Information, &text, 4);
}

/// Save the active tab's view from the page's in-flight switch record; true
/// when that session was empty, so the server drops it.
pub(super) fn save_current_from_switching(app: &mut App) -> bool {
    let from = app.session_tabs.active;
    let Some(switching) = &app.sessions_page.switching else {
        return false;
    };
    let empty = !switching.previous.has_server_entries();
    let snapshot = TabSnapshot {
        transcript: switching.previous.clone(),
        scroll: switching.scroll,
        draft: app.chat_input.input.clone(),
        cursor: app.chat_input.cursor,
    };
    if let Some(tab) = app.session_tabs.list.get_mut(from) {
        tab.snapshot = Some(snapshot);
    }
    empty
}

/// Remove the tab at `index` when its session was empty: the server dropped it with the switch.
pub(super) fn drop_empty(app: &mut App, index: usize, empty: bool) {
    if empty && index < app.session_tabs.list.len() && app.session_tabs.list.len() > 1 {
        actions::remove_tab(app, index);
        say_empty(app, index);
    }
}

/// The agent config a new tab's session opens with: the current one, minus a
/// pinned worktree (a tab is not a worktree run).
fn config_for_new(app: &App) -> AgentConfig {
    let mut config = app.session.agent_config.clone();
    config.worktree = None;
    config
}

/// Whether the attached session has turn work the server parks when it is left.
fn running(app: &App) -> bool {
    matches!(app.session.status, crate::app::Status::Generating { .. })
        || (!app.queue.paused && !app.queue.is_empty())
}

/// Switch to tab `to`, even while a turn runs: save the active tab, show the
/// target's saved view, and send the resume/start request. The answer lands in
/// `super::on_session_id`.
pub(super) fn start(app: &mut App, client: &Arc<Client>, to: usize) {
    if !app.session_tabs.enabled
        || to >= app.session_tabs.list.len()
        || to == app.session_tabs.active
        || app.sessions_page.switching.is_some()
        || switching(app)
    {
        return;
    }
    let from = app.session_tabs.active;
    // The server parks a running turn, and drops a session nothing was ever run in.
    let running = running(app);
    let empty = !running && !app.view.transcript.has_server_entries();
    app.session_tabs.list[from].activity = if running {
        Activity::Running
    } else {
        Activity::Idle
    };
    if empty && app.session_tabs.pending_close.is_none() {
        app.session_tabs.pending_close = Some(from);
        app.session_tabs.pending_empty = true;
    }
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

/// Switch to tab `to` whose session is already attached (the server reused it,
/// e.g. for an empty session a new tab replaced): swap the saved views locally,
/// no server round-trip — so it works even while a turn runs.
pub(super) fn switch_local(app: &mut App, to: usize) {
    let from = app.session_tabs.active;
    let snapshot = TabSnapshot {
        transcript: app.view.transcript.snapshot(),
        scroll: (app.view.scroll, app.view.scroll_target),
        draft: app.chat_input.input.clone(),
        cursor: app.chat_input.cursor,
    };
    app.session_tabs.list[from].snapshot = Some(snapshot);
    app.session_tabs.active = to;
    let saved = app.session_tabs.list[to].snapshot.take();
    match &saved {
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
    let (draft, cursor) = saved
        .as_ref()
        .map(|saved| (saved.draft.clone(), saved.cursor))
        .unwrap_or_default();
    restore_draft(app, &draft, cursor);
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
