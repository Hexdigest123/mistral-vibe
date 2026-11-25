//! Polling the tabs whose turn runs in the background, to mark them running or done.

use std::sync::Arc;
use std::time::Duration;

use serde_json::json;

use super::Activity;
use crate::app::App;
use crate::server::{method, Client};

/// How often the background tabs are read while one runs.
const POLL_INTERVAL: Duration = Duration::from_secs(3);

/// The most sessions one poll reads; the tab bar holds far fewer.
const POLL_LIMIT: usize = 500;

/// A poll answered: each listed session's status, or nothing when the read failed.
pub struct Event(pub Option<Vec<(String, String)>>);

/// The sessions of the tabs not on screen whose turn runs or waits.
fn background_ids(app: &App) -> Vec<String> {
    let tabs = &app.session_tabs;
    let live = |activity| matches!(activity, Activity::Running | Activity::Waiting);
    let tabs = tabs.list.iter().enumerate();
    tabs.filter(|(index, tab)| *index != app.session_tabs.active && live(tab.activity))
        .filter_map(|(_, tab)| tab.session_id.clone())
        .collect()
}

/// Arm the next poll while a tab runs in the background; no tab, no poll.
pub(super) fn rearm(app: &mut App) {
    let any = app.session_tabs.enabled && !background_ids(app).is_empty();
    app.session_tabs.poll_at = any.then(|| crate::clock::now() + POLL_INTERVAL);
}

/// Read the status of the background tabs' sessions: a host method, no session attached.
pub fn poll(app: &mut App, client: &Arc<Client>) {
    app.session_tabs.poll_at = None;
    let ids = background_ids(app);
    if ids.is_empty() || app.session_tabs.polling || app.events.is_none() {
        return;
    }
    app.session_tabs.polling = true;
    let client = client.clone();
    crate::ui_event::spawn(app, async move {
        let params = json!({ "sessionIds": ids, "limit": POLL_LIMIT });
        let value = client.request(method::SESSION_LIST, params).await.ok();
        Event(value.map(|value| {
            let rows = crate::sessions_page::row::sessions(&value);
            rows.into_iter().map(|row| (row.id, row.status)).collect()
        }))
    });
}

/// Mark each background tab from the answer, and poll on while one still runs.
pub fn apply_event(app: &mut App, event: Event) {
    app.session_tabs.polling = false;
    if let Some(rows) = event.0 {
        let active = app.session_tabs.active;
        for (index, tab) in app.session_tabs.list.iter_mut().enumerate() {
            let live = matches!(tab.activity, Activity::Running | Activity::Waiting);
            let Some(id) = tab
                .session_id
                .as_deref()
                .filter(|_| live && index != active)
            else {
                continue;
            };
            tab.activity = match rows.iter().find(|(row, _)| row == id) {
                Some((_, status)) if status == "running" => Activity::Running,
                Some((_, status)) if status == "blocked" => Activity::Waiting,
                Some((_, status)) if status.is_empty() => tab.activity,
                Some(_) => Activity::Done,
                None => Activity::Idle,
            };
        }
    }
    rearm(app);
}
