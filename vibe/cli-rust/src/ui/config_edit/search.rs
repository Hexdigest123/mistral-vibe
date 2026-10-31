//! Fork feature (AGENTS.md): the search row above a long `/config` choice list.

use ratatui::layout::Rect;
use ratatui::Frame;

use super::layout::SEARCH_ROWS;
use crate::config_edit::{self, ConfigEdit};
use crate::ui::theme;

/// The search row and its matches; returns the list's area and its labels.
pub(super) fn draw(
    f: &mut Frame,
    editor: Rect,
    edit: &mut ConfigEdit,
    labels: &[String],
    cursor_on: bool,
) -> (Rect, Vec<String>) {
    let shown: Vec<String> = config_edit::search::visible(edit)
        .into_iter()
        .map(|index| labels[index].clone())
        .collect();
    if !config_edit::search::searchable(&edit.field) {
        return (editor, shown);
    }
    let row = Rect::new(editor.x + 1, editor.y, editor.width.saturating_sub(2), 1);
    edit.search.area = crate::ui::search_field::draw_row(
        f,
        row,
        &edit.search,
        "Search choices",
        cursor_on,
        theme::surface(),
    );
    let list = Rect {
        y: editor.y + SEARCH_ROWS,
        height: editor.height.saturating_sub(SEARCH_ROWS),
        ..editor
    };
    if shown.is_empty() {
        let style = theme::dim(theme::text_muted()).bg(theme::surface());
        let width = list.width.saturating_sub(1) as usize;
        f.buffer_mut()
            .set_stringn(list.x + 1, list.y, "No matching choices", width, style);
    }
    (list, shown)
}
