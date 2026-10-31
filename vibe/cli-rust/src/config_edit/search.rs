//! Fork feature (AGENTS.md): fzf search over a `/config` choice list too long for one screen.

use crossterm::event::{KeyCode, KeyEvent, MouseButton, MouseEvent, MouseEventKind};

use super::{choice_label, choices, ConfigEdit, MAX_VISIBLE_CHOICES};
use crate::config::ConfigField;
use crate::option_list::OptionList;
use crate::search_field::{self, Outcome};
use crate::utils::fzf;

/// Whether the field's choices get a search row: more than fit on screen.
pub fn searchable(field: &ConfigField) -> bool {
    choices(field).len() > MAX_VISIBLE_CHOICES
}

/// Indices into `choices` the list shows, best match first; every one without a query.
pub fn visible(edit: &ConfigEdit) -> Vec<usize> {
    let field = &edit.field;
    let haystack = |choice: &String| fzf::haystack([choice_label(field, choice).as_str(), choice]);
    fzf::rank(&choices(field), &edit.search.query, haystack, |_| "")
}

/// Route a key through the search first; true when it consumed it. Tab keeps cycling the layer.
pub fn key(edit: &mut ConfigEdit, key: &KeyEvent) -> bool {
    if key.code == KeyCode::Tab || !searchable(&edit.field) {
        return false;
    }
    match search_field::handle_key(&mut edit.search, key) {
        Outcome::Pass => false,
        Outcome::Consumed => true,
        Outcome::Filtered => {
            refilter(edit);
            true
        }
    }
}

/// Insert pasted text into the focused field; false when it is not focused.
pub fn paste(edit: &mut ConfigEdit, text: &str) -> bool {
    if !search_field::paste(&mut edit.search, text) {
        return false;
    }
    refilter(edit);
    true
}

/// A press on the search field focuses it; true when consumed.
pub fn click(edit: &mut ConfigEdit, event: MouseEvent) -> bool {
    let on_field = event.kind == MouseEventKind::Down(MouseButton::Left)
        && edit.search.area.contains((event.column, event.row).into());
    if on_field {
        edit.search.focused = true;
    }
    on_field
}

/// Highlight the best match, or the drafted choice once the query is cleared.
fn refilter(edit: &mut ConfigEdit) {
    let all = choices(&edit.field);
    let shown = visible(edit);
    let index = match edit.search.query.trim().is_empty() {
        true => shown
            .iter()
            .position(|&i| all[i] == edit.draft)
            .unwrap_or(0),
        false => 0,
    };
    edit.list = OptionList::new(index);
    super::select_choice(edit, &all, &shown, index);
}
