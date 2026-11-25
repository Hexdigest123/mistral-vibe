//! Session tabs: several sessions in one window, switched in place.
// Fork feature (AGENTS.md \"Fork features\"): quick-switch tabs — only the active
// tab is attached to the app-server; the others keep their transcript, scroll
// and composer draft here, and their session in the store (resumable later).
// The `enable_session_tabs` config value (default on) hides the whole feature.
// A switch while a turn runs is queued and runs when the session goes idle.

mod command;
mod keys;
mod switch;

use std::sync::Arc;

use ratatui::layout::Rect;

use crate::app::{App, Severity, Status};
use crate::server::Client;
use crate::transcript::Snapshot;

pub use command::run as command;
pub use keys::{chord_key, handle_key};

/// Refusal shown while the session is starting or failed: nothing queues then.
pub const BUSY: &str = "Wait for the current turn to finish before switching tabs.";

/// A tab action the user asked for while a turn runs; it runs once the session is idle.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum QueuedAction {
    Switch(usize),
    New,
    Close(usize),
}

/// One tab: the session it shows, its label, and the view saved while away.
pub struct Tab {
    pub session_id: Option<String>,
    pub title: String,
    pub snapshot: Option<TabSnapshot>,
}

/// The conversation and composer a tab had when the user switched away.
#[derive(Clone)]
pub struct TabSnapshot {
    pub transcript: Snapshot,
    pub scroll: (u16, u16),
    pub draft: String,
    pub cursor: usize,
}

/// The open tabs and which one is attached; empty until the first session lands.
pub struct SessionTabs {
    pub list: Vec<Tab>,
    pub active: usize,
    /// The tab switch in flight: (the tab left, the tab switched to).
    pending: Option<(usize, usize)>,
    /// The active tab closes once its switch away lands.
    pending_close: Option<usize>,
    /// The tab action queued while the session was busy.
    pub queued: Option<QueuedAction>,
    /// Ctrl+X was pressed: the next key is a tab command (1-9 switch, n new, c close).
    pub chord: bool,
    /// Painted tab cells of the last frame, for mouse clicks.
    pub areas: Vec<Rect>,
    /// The `enable_session_tabs` config value.
    pub enabled: bool,
}

impl Default for SessionTabs {
    fn default() -> Self {
        Self {
            list: Vec::new(),
            active: 0,
            pending: None,
            pending_close: None,
            queued: None,
            chord: false,
            areas: Vec::new(),
            enabled: true,
        }
    }
}

/// Whether tabs can be switched: the feature is on and more than one is open.
pub fn switchable(app: &App) -> bool {
    app.session_tabs.enabled && app.session_tabs.list.len() > 1
}

/// Whether the tab bar is drawn: more than one open tab, or the chord is armed.
pub fn visible(app: &App) -> bool {
    app.session_tabs.enabled && (app.session_tabs.list.len() > 1 || app.session_tabs.chord)
}

/// Whether a tab switch is waiting on the server.
pub fn switching(app: &App) -> bool {
    app.session_tabs.pending.is_some()
}

/// Apply the `enable_session_tabs` config value.
pub fn set_enabled(app: &mut App, enabled: bool) {
    app.session_tabs.enabled = enabled;
    if !enabled {
        app.session_tabs.queued = None;
        app.session_tabs.chord = false;
    }
}

/// `App::set_session_id` hook: register the attached session as a tab.
pub fn on_session_id(app: &mut App, id: &str) {
    if !app.session_tabs.enabled {
        return;
    }
    if let Some((_from, to)) = app.session_tabs.pending.take() {
        // A tab switch landed: the target tab now shows the attached session.
        app.session_tabs.active = to;
        if let Some(closing) = app.session_tabs.pending_close.take() {
            app.session_tabs.list.remove(closing);
            if to > closing {
                app.session_tabs.active = to - 1;
            }
        }
        let tab = &mut app.session_tabs.list[app.session_tabs.active];
        tab.session_id = Some(id.to_owned());
        tab.snapshot = None;
        if tab.title == "New" {
            tab.title = crate::sessions_page::short_id(id).to_owned();
        }
        return;
    }
    if let Some(index) = app
        .session_tabs
        .list
        .iter()
        .position(|tab| tab.session_id.as_deref() == Some(id))
    {
        // Re-adopted an open tab (the Sessions page opened it): leave the
        // current tab's view saved, land on the existing one.
        if index != app.session_tabs.active {
            save_current_from_switching(app);
            app.session_tabs.active = index;
            app.session_tabs.list[index].snapshot = None;
        }
        return;
    }
    if app.sessions_page.switching.is_some() {
        // The Sessions page opened a session that is not a tab yet: the
        // current tab keeps its view, the opened one gets a new tab.
        save_current_from_switching(app);
        let title = app
            .sessions_page
            .sessions
            .iter()
            .find(|session| session.id == id)
            .map(|session| session.label().to_owned())
            .unwrap_or_else(|| crate::sessions_page::short_id(id).to_owned());
        app.session_tabs.list.push(Tab {
            session_id: Some(id.to_owned()),
            title,
            snapshot: None,
        });
        app.session_tabs.active = app.session_tabs.list.len() - 1;
        return;
    }
    if app.session_tabs.list.is_empty() {
        // The session the run started with.
        app.session_tabs.list.push(Tab {
            session_id: Some(id.to_owned()),
            title: crate::sessions_page::short_id(id).to_owned(),
            snapshot: None,
        });
        app.session_tabs.active = 0;
        return;
    }
    // An in-place replacement (`/clear`, `/compact`): the active tab takes the new id.
    let tab = &mut app.session_tabs.list[app.session_tabs.active];
    tab.session_id = Some(id.to_owned());
    tab.snapshot = None;
}

/// The attached session's title lands: the active tab shows it.
pub fn note_title(app: &mut App, title: Option<&str>) {
    if !app.session_tabs.enabled {
        return;
    }
    let Some(tab) = app.session_tabs.list.get_mut(app.session_tabs.active) else {
        return;
    };
    match title.filter(|title| !title.is_empty()) {
        Some(title) => tab.title = title.to_owned(),
        None => {
            if let Some(id) = &tab.session_id {
                tab.title = crate::sessions_page::short_id(id).to_owned();
            }
        }
    }
}

/// Save the active tab's view from the page's in-flight switch record.
fn save_current_from_switching(app: &mut App) {
    let from = app.session_tabs.active;
    let Some(switching) = &app.sessions_page.switching else {
        return;
    };
    let snapshot = TabSnapshot {
        transcript: switching.previous.clone(),
        scroll: switching.scroll,
        draft: app.chat_input.input.clone(),
        cursor: app.chat_input.cursor,
    };
    if let Some(tab) = app.session_tabs.list.get_mut(from) {
        tab.snapshot = Some(snapshot);
    }
}

/// A tab switch failed: the tab left stays active, with its draft back. When the
/// target's session no longer exists, its tab is removed from the list instead.
pub fn on_switch_failed(app: &mut App, session_gone: bool) {
    let Some((from, to)) = app.session_tabs.pending.take() else {
        return;
    };
    app.session_tabs.pending_close = None;
    if session_gone {
        app.session_tabs.list.remove(to);
        if to < from {
            app.session_tabs.active = from - 1;
        }
        app.session_tabs.queued = None;
        crate::notices::inline(
            app,
            Severity::Warning,
            "Removed a tab whose session no longer exists.",
        );
    }
    if let Some(snapshot) = app.session_tabs.list[app.session_tabs.active]
        .snapshot
        .clone()
    {
        let (draft, cursor) = (snapshot.draft.clone(), snapshot.cursor);
        switch::restore_draft(app, &draft, cursor);
    }
}

/// Queue a tab action while the session is busy; it runs when the session is idle.
fn queue(app: &mut App, action: QueuedAction) {
    if matches!(app.session.status, Status::Starting | Status::Failed) {
        crate::notices::inline(app, Severity::Warning, BUSY);
        return;
    }
    let text = match action {
        QueuedAction::Switch(index) => {
            format!(
                "Switch to tab {} when the current turn finishes.",
                index + 1
            )
        }
        QueuedAction::New => "Open the new tab when the current turn finishes.".to_owned(),
        QueuedAction::Close(index) => {
            format!("Close tab {} when the current turn finishes.", index + 1)
        }
    };
    app.session_tabs.queued = Some(action);
    crate::notices::inline(app, Severity::Information, &text);
}

/// Run the queued tab action once the session is idle; called after server events.
pub fn maybe_run_queued(app: &mut App, client: &Arc<Client>) {
    if !app.session_tabs.enabled {
        app.session_tabs.queued = None;
        return;
    }
    let Some(action) = app.session_tabs.queued else {
        return;
    };
    if crate::sessions_page::switching(app) || switching(app) || !crate::sessions_page::idle(app) {
        return;
    }
    app.session_tabs.queued = None;
    match action {
        QueuedAction::Switch(index) => switch_to(app, client, index),
        QueuedAction::New => new_tab(app, client),
        QueuedAction::Close(index) => close(app, client, index),
    }
}

/// Remove the tab at `index`, fixing the active index and any queued action.
fn remove_tab(app: &mut App, index: usize) {
    app.session_tabs.list.remove(index);
    if app.session_tabs.active > index {
        app.session_tabs.active -= 1;
    }
    let mut drop_queued = false;
    if let Some(queued) = &mut app.session_tabs.queued {
        match queued {
            QueuedAction::Switch(i) | QueuedAction::Close(i) => {
                if *i == index {
                    drop_queued = true;
                } else if *i > index {
                    *i -= 1;
                }
            }
            QueuedAction::New => {}
        }
    }
    if drop_queued {
        app.session_tabs.queued = None;
    }
}

/// Open a new tab with a fresh session in the current folder.
pub fn new_tab(app: &mut App, client: &Arc<Client>) {
    if !app.session_tabs.enabled {
        disabled_notice(app);
        return;
    }
    if crate::sessions_page::switching(app) || switching(app) {
        return;
    }
    if !crate::sessions_page::idle(app) {
        queue(app, QueuedAction::New);
        return;
    }
    app.session_tabs.list.push(Tab {
        session_id: None,
        title: "New".to_owned(),
        snapshot: None,
    });
    let to = app.session_tabs.list.len() - 1;
    switch::start(app, client, to);
}

/// Switch to the tab at `index`.
pub fn switch_to(app: &mut App, client: &Arc<Client>, index: usize) {
    if !app.session_tabs.enabled {
        disabled_notice(app);
        return;
    }
    if index >= app.session_tabs.list.len() || index == app.session_tabs.active {
        return;
    }
    if crate::sessions_page::switching(app) || switching(app) {
        return;
    }
    // The target's session is already attached (the server reused it): swap views locally.
    if app.session_tabs.list[index].session_id.is_some()
        && app.session_tabs.list[index].session_id == app.session.session_id
    {
        switch::switch_local(app, index);
        return;
    }
    if !crate::sessions_page::idle(app) {
        queue(app, QueuedAction::Switch(index));
        return;
    }
    switch::start(app, client, index);
}

/// Close the tab at `index`; the active one switches to a neighbour first.
pub fn close(app: &mut App, client: &Arc<Client>, index: usize) {
    if !app.session_tabs.enabled {
        disabled_notice(app);
        return;
    }
    let len = app.session_tabs.list.len();
    if index >= len {
        return;
    }
    if len == 1 {
        crate::notices::inline(
            app,
            Severity::Warning,
            "The last tab can't be closed; /exit quits.",
        );
        return;
    }
    if index == app.session_tabs.active {
        if crate::sessions_page::switching(app) || switching(app) {
            return;
        }
        if !crate::sessions_page::idle(app) {
            queue(app, QueuedAction::Close(index));
            return;
        }
        app.session_tabs.pending_close = Some(index);
        let to = if index > 0 { index - 1 } else { 1 };
        switch::start(app, client, to);
    } else {
        remove_tab(app, index);
    }
}

/// Switch to the next (1) or previous (-1) tab, wrapping.
pub fn step(app: &mut App, client: &Arc<Client>, delta: isize) {
    let len = app.session_tabs.list.len() as isize;
    if len < 2 {
        return;
    }
    let to = (app.session_tabs.active as isize + delta).rem_euclid(len) as usize;
    switch_to(app, client, to);
}

/// A mouse press on the tab bar at `column`.
pub fn click(
    app: &mut App,
    client: &Arc<Client>,
    column: u16,
    button: crossterm::event::MouseButton,
) {
    use crossterm::event::MouseButton;
    let Some(index) = app
        .session_tabs
        .areas
        .iter()
        .position(|area| column >= area.x && column < area.right())
    else {
        return;
    };
    match button {
        MouseButton::Left => switch_to(app, client, index),
        MouseButton::Middle => close(app, client, index),
        _ => {}
    }
}

/// The feature is off: say so instead of switching.
fn disabled_notice(app: &mut App) {
    crate::notices::inline(
        app,
        Severity::Warning,
        "Session tabs are off; set enable_session_tabs = true to use them.",
    );
}
