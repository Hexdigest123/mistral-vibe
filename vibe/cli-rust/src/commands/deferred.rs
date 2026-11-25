//! Fork feature (AGENTS.md "Fork features"): one history-rewriting slash command waits here for idle.

use std::sync::Arc;

use tokio::sync::mpsc;

use super::submission::{self, NOTICE_TIMEOUT_SECS};
use super::{drops_queue, is_deferred, parse};
use crate::app::{App, Severity, Status};
use crate::server::Client;
use crate::{config, ui};

/// Whether `command` must wait: it is deferred and a turn, job, shell command or accepted queue is active.
pub(super) fn must_wait(app: &App, command: &str) -> bool {
    is_deferred(command)
        && (submission::working(app)
            || submission::shell_in_flight(app)
            || (!app.queue.paused && !app.queue.is_empty()))
}

/// Keep `value` for when the session is idle; a command already waiting is replaced.
pub(super) fn schedule(app: &mut App, command: &str, value: &str) {
    let replaced = app
        .deferred_command
        .replace(value.to_owned())
        .and_then(|old| parse(&old));
    let text = match replaced {
        Some(old) if old != command => {
            format!("{command} replaces {old}: it will run when the current turn finishes")
        }
        _ => format!("{command} will run when the current turn finishes"),
    };
    ui::notice::show(app, Severity::Information, &text, NOTICE_TIMEOUT_SECS);
}

/// Drop the waiting command (Esc on the turn), saying so.
pub fn cancel(app: &mut App) {
    if let Some(value) = app.deferred_command.take() {
        let command = parse(&value).unwrap_or("The scheduled command");
        let text = format!("{command} cancelled");
        ui::notice::show(app, Severity::Information, &text, NOTICE_TIMEOUT_SECS);
    }
}

/// Whether the session can run `command` now: attached, idle, and not switching.
fn runnable(app: &App, command: &str) -> bool {
    !matches!(app.session.status, Status::Starting | Status::Failed)
        && !submission::shell_in_flight(app)
        && !crate::sessions_page::switching(app)
        && !crate::session_tabs::switching(app)
        && submission::idle_hint(app, drops_queue(command)).is_none()
}

/// Run the waiting command once the session is idle; called after server events.
pub fn run_when_idle(
    app: &mut App,
    client: &Arc<Client>,
    config_tx: &mpsc::Sender<config::Loaded>,
) {
    let Some(value) = app.deferred_command.as_deref() else {
        return;
    };
    let Some(command) = parse(value) else {
        app.deferred_command = None;
        return;
    };
    if !runnable(app, command) {
        return;
    }
    let value = app.deferred_command.take().unwrap_or_default();
    // The "will run" notice is stale now.
    ui::notice::clear(app);
    app.pending_commands.push(value);
    submission::flush_pending(app, client, config_tx);
}
