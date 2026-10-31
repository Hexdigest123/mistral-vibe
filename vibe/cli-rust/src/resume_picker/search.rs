//! Fork feature (AGENTS.md): fzf search over the saved sessions, by title, then preview text.

use std::sync::Arc;

use crossterm::event::{KeyEvent, MouseButton, MouseEvent, MouseEventKind};

use super::Session;
use crate::app::App;
use crate::search_field::{self, Outcome};
use crate::server::Client;
use crate::utils::fzf;

/// Indices into `sessions` the list shows: best match first, all of them newest first without a query.
pub fn shown(app: &App) -> Vec<usize> {
    let picker = &app.resume_picker;
    let query = &picker.search.query;
    fzf::rank(&picker.sessions, query, |s| s.title.clone(), |s| &s.preview)
}

/// The session on the highlighted row.
pub fn selected(app: &App) -> Option<&Session> {
    let index = *shown(app).get(app.resume_picker.list.selected())?;
    app.resume_picker.sessions.get(index)
}

/// Route a key through the search first; true when it consumed it.
pub fn key(app: &mut App, client: &Arc<Client>, key: &KeyEvent) -> bool {
    match search_field::handle_key(&mut app.resume_picker.search, key) {
        Outcome::Pass => false,
        Outcome::Consumed => true,
        Outcome::Filtered => {
            refilter(app, client);
            true
        }
    }
}

/// Insert pasted text into the focused search field.
pub fn paste(app: &mut App, client: &Arc<Client>, text: &str) {
    if search_field::paste(&mut app.resume_picker.search, text) {
        refilter(app, client);
    }
}

/// A press on the search field focuses it; one on a row leaves the field. True when consumed.
pub fn click(app: &mut App, event: MouseEvent) -> bool {
    if event.kind != MouseEventKind::Down(MouseButton::Left) {
        return false;
    }
    let at = (event.column, event.row);
    let picker = &mut app.resume_picker;
    if picker.search.area.contains(at.into()) {
        picker.search.focused = true;
        return true;
    }
    if picker.list.index_at(at).is_some() {
        picker.search.focused = false;
    }
    false
}

/// A new query highlights and previews its best match.
fn refilter(app: &mut App, client: &Arc<Client>) {
    app.resume_picker.delete_confirm = None;
    app.resume_picker.list.reset();
    super::preview(app, client);
}
