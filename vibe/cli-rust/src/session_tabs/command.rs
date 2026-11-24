//! `/tab [new|next|prev|close [N]|N]`: manage the session tabs.

use std::sync::Arc;

use crate::app::{App, Severity};
use crate::server::Client;

use super::{close, new_tab, step, switch_to};

const USAGE: &str = "Usage: /tab [new|next|prev|close [N]|N]";

/// Run `/tab` with its argument text.
pub fn run(app: &mut App, client: &Arc<Client>, args: &str) {
    let arg = args.trim();
    let mut words = arg.split_whitespace();
    let word = words.next().unwrap_or("");
    match word {
        "" | "next" => step(app, client, 1),
        "prev" | "previous" => step(app, client, -1),
        "new" => new_tab(app, client),
        "close" => match words.next() {
            None => {
                let active = app.session_tabs.active;
                close(app, client, active);
            }
            Some(n) => match n.parse::<usize>() {
                Ok(n) if (1..=app.session_tabs.list.len()).contains(&n) => {
                    close(app, client, n - 1)
                }
                _ => crate::notices::inline(app, Severity::Warning, USAGE),
            },
        },
        n if n.bytes().all(|b| b.is_ascii_digit()) => match n.parse::<usize>() {
            Ok(n) if n >= 1 && n <= app.session_tabs.list.len() => switch_to(app, client, n - 1),
            _ => crate::notices::inline(app, Severity::Warning, USAGE),
        },
        _ => crate::notices::inline(app, Severity::Warning, USAGE),
    }
}
