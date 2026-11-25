//! The tab actions: open, switch, close and step, each running at once, busy or not.

use std::sync::Arc;

use crate::app::{App, Severity};
use crate::server::Client;

use super::{ready, switch, switching, Tab};

/// Open a new tab with a fresh session in the current folder.
pub fn new_tab(app: &mut App, client: &Arc<Client>) {
    if !app.session_tabs.enabled {
        return disabled_notice(app);
    }
    if crate::sessions_page::switching(app) || switching(app) || !ready(app) {
        return;
    }
    app.session_tabs.list.push(Tab::new(None, "New".to_owned()));
    let to = app.session_tabs.list.len() - 1;
    switch::start(app, client, to);
}

/// Switch to the tab at `index`.
pub fn switch_to(app: &mut App, client: &Arc<Client>, index: usize) {
    if !app.session_tabs.enabled {
        return disabled_notice(app);
    }
    if index >= app.session_tabs.list.len() || index == app.session_tabs.active {
        return;
    }
    if crate::sessions_page::switching(app) || switching(app) {
        return;
    }
    // The target's session is already attached (the server reused it): swap views locally.
    let target = app.session_tabs.list[index].session_id.as_deref();
    if target.is_some() && target == app.session.session_id.as_deref() {
        return switch::switch_local(app, index);
    }
    if ready(app) {
        switch::start(app, client, index);
    }
}

/// Close the tab at `index`; the active one switches to a neighbour first.
pub fn close(app: &mut App, client: &Arc<Client>, index: usize) {
    if !app.session_tabs.enabled {
        return disabled_notice(app);
    }
    let len = app.session_tabs.list.len();
    if index >= len || crate::sessions_page::switching(app) || switching(app) {
        return;
    }
    if len == 1 {
        let text = "The last tab can't be closed; /exit quits.";
        return crate::notices::inline(app, Severity::Warning, text);
    }
    if index != app.session_tabs.active {
        return remove_tab(app, index);
    }
    if ready(app) {
        app.session_tabs.pending_close = Some(index);
        switch::start(app, client, if index > 0 { index - 1 } else { 1 });
    }
}

/// Remove the tab at `index`, keeping the same tab active.
pub(super) fn remove_tab(app: &mut App, index: usize) {
    app.session_tabs.list.remove(index);
    if app.session_tabs.active > index {
        app.session_tabs.active -= 1;
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
