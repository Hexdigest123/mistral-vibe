//! Session tabs: several sessions in one window, switched in place.
// Fork feature (AGENTS.md "Fork features"): quick-switch tabs — only the active
// tab is attached to the app-server; the others keep their transcript, scroll
// and composer draft here, and their session in the store (resumable later).
// The `enable_session_tabs` config value (default on) hides the whole feature.
// A switch runs at once: the server parks a running turn, which `background` polls.

mod actions;
mod background;
mod command;
mod keys;
mod stale;
mod switch;

use ratatui::layout::Rect;

use crate::app::{App, Severity, Status};
use crate::clock::UiInstant;
use crate::transcript::Snapshot;

pub use actions::{click, close, new_tab, step, switch_to};
pub use background::{apply_event, poll, Event};
pub use command::run as command;
pub use keys::{chord_key, handle_key};

/// Refusal shown while the session is starting or failed: nothing is attached to leave.
pub const STARTING: &str = "Wait for the session to start before switching tabs.";

/// Refusal shown while a compaction runs: its answer belongs to the session being left.
pub const COMPACTING: &str = "Wait for the compaction to finish before switching tabs.";

/// What a tab not on screen is doing, as the last poll of the server saw it.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Activity {
    #[default]
    Idle,
    /// Its turn still runs in the background.
    Running,
    /// Its turn waits on an answer (an approval, a question).
    Waiting,
    /// Its turn ended while the user was away.
    Done,
}

/// One tab: the session it shows, its label, and the view saved while away.
pub struct Tab {
    pub session_id: Option<String>,
    pub title: String,
    pub snapshot: Option<TabSnapshot>,
    pub activity: Activity,
}

impl Tab {
    pub fn new(session_id: Option<String>, title: String) -> Self {
        Self {
            session_id,
            title,
            snapshot: None,
            activity: Activity::Idle,
        }
    }
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
    /// The tab left goes once the switch lands: closed, or empty (the server drops it).
    pending_close: Option<usize>,
    /// That tab goes because it was empty, not because the user closed it.
    pending_empty: bool,
    /// Ctrl+X was pressed: the next key is a tab command (1-9 switch, n new, w close).
    pub chord: bool,
    /// Painted tab cells of the last frame, for mouse clicks.
    pub areas: Vec<Rect>,
    /// The `enable_session_tabs` config value.
    pub enabled: bool,
    /// When the tabs running in the background are polled next; unset with none.
    pub poll_at: Option<UiInstant>,
    /// A background poll is in flight.
    polling: bool,
}

impl Default for SessionTabs {
    fn default() -> Self {
        Self {
            list: Vec::new(),
            active: 0,
            pending: None,
            pending_close: None,
            pending_empty: false,
            chord: false,
            areas: Vec::new(),
            enabled: true,
            poll_at: None,
            polling: false,
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
        app.session_tabs.chord = false;
        app.session_tabs.poll_at = None;
    }
}

/// Whether a tab action can leave the attached session now; says why when not.
fn ready(app: &mut App) -> bool {
    let text = match () {
        _ if matches!(app.session.status, Status::Starting | Status::Failed) => STARTING,
        _ if app.compacting => COMPACTING,
        _ => return true,
    };
    crate::notices::inline(app, Severity::Warning, text);
    false
}

/// `App::set_session_id` hook: register the attached session as a tab.
pub fn on_session_id(app: &mut App, id: &str) {
    if !app.session_tabs.enabled {
        return;
    }
    if let Some((_, to)) = app.session_tabs.pending.take() {
        // A tab switch landed: the target tab now shows the attached session, and the
        // callbacks of the one left (parked, re-sent when it is attached again) are moot.
        let left = app.session.session_id.clone();
        if let Some(left) = left.as_deref().filter(|left| *left != id) {
            stale::drop_callbacks(app, left);
        }
        app.session_tabs.active = to;
        if let Some(gone) = app.session_tabs.pending_close.take() {
            app.session_tabs.list.remove(gone);
            if to > gone {
                app.session_tabs.active = to - 1;
            }
            if std::mem::take(&mut app.session_tabs.pending_empty) {
                switch::say_empty(app, gone);
            }
        }
        let tab = &mut app.session_tabs.list[app.session_tabs.active];
        tab.session_id = Some(id.to_owned());
        tab.snapshot = None;
        tab.activity = Activity::Idle;
        if tab.title == "New" {
            tab.title = crate::sessions_page::short_id(id).to_owned();
        }
        background::rearm(app);
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
            let from = app.session_tabs.active;
            let empty = switch::save_current_from_switching(app);
            app.session_tabs.active = index;
            let tab = &mut app.session_tabs.list[index];
            (tab.snapshot, tab.activity) = (None, Activity::Idle);
            switch::drop_empty(app, from, empty);
        }
        return;
    }
    if app.sessions_page.switching.is_some() {
        // The Sessions page opened a session that is not a tab yet: the
        // current tab keeps its view, the opened one gets a new tab.
        let from = app.session_tabs.active;
        let empty = switch::save_current_from_switching(app);
        let title = app
            .sessions_page
            .sessions
            .iter()
            .find(|session| session.id == id)
            .map(|session| session.label().to_owned())
            .unwrap_or_else(|| crate::sessions_page::short_id(id).to_owned());
        app.session_tabs
            .list
            .push(Tab::new(Some(id.to_owned()), title));
        app.session_tabs.active = app.session_tabs.list.len() - 1;
        switch::drop_empty(app, from, empty);
        return;
    }
    if app.session_tabs.list.is_empty() {
        // The session the run started with.
        let title = crate::sessions_page::short_id(id).to_owned();
        app.session_tabs
            .list
            .push(Tab::new(Some(id.to_owned()), title));
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

/// A tab switch failed: the tab left stays active, with its draft back. When the
/// target's session no longer exists, its tab is removed from the list instead.
pub fn on_switch_failed(app: &mut App, session_gone: bool) {
    let Some((from, to)) = app.session_tabs.pending.take() else {
        return;
    };
    app.session_tabs.pending_close = None;
    app.session_tabs.pending_empty = false;
    if session_gone {
        app.session_tabs.list.remove(to);
        if to < from {
            app.session_tabs.active = from - 1;
        }
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
