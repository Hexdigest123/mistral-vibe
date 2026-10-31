//! `/resume` picker view: title, search row (fork feature, AGENTS.md), sessions, hints.

use ratatui::layout::Rect;
use ratatui::style::{Modifier, Style};
use ratatui::widgets::{Block, Borders, Clear};
use ratatui::Frame;

use super::{scrollbar, theme};
use crate::app::App;
use crate::hints::{self, action};

/// Rows around the list: 2 borders, title, search, blank, margin-top, help.
const CHROME_ROWS: u16 = 7;

pub fn draw(app: &mut App, f: &mut Frame, area: Rect) {
    // Sized from every session, so typing a search never resizes the box.
    let rows = app.resume_picker.sessions.len().max(1) as u16;
    let height = (rows + CHROME_ROWS).min(max_height(area));
    let kind = super::bottom_app::Kind::Resume;
    super::bottom_app::draw(app, f, area, height, kind, draw_box);
}

/// The whole picker takes at most 40% of the screen, keeping one session row.
fn max_height(area: Rect) -> u16 {
    (area.height * 2 / 5).max(CHROME_ROWS + 1)
}

fn draw_box(app: &mut App, f: &mut Frame, area: Rect) {
    if area.height < CHROME_ROWS {
        return;
    }
    f.render_widget(Clear, area);
    let bg = theme::background();
    f.buffer_mut().set_style(area, Style::default().bg(bg));
    f.render_widget(
        Block::default()
            .borders(Borders::ALL)
            .border_style(Style::default().fg(theme::popup_border()).bg(bg)),
        area,
    );
    let title = Style::default().fg(theme::secondary()).bg(bg);
    let cwd = app.resume_picker.cwd.as_deref().unwrap_or("this folder");
    f.buffer_mut()
        .set_string(area.x + 2, area.y + 1, "local", title);
    f.buffer_mut()
        .set_string(area.x + 8, area.y + 1, cwd, theme::muted_style().bg(bg));
    draw_search(
        app,
        f,
        Rect::new(area.x + 3, area.y + 2, area.width.saturating_sub(6), 1),
    );
    let visible = area.height.saturating_sub(CHROME_ROWS) as usize;
    let shown = crate::resume_picker::search::shown(app);
    let total = shown.len();
    let top = area.y + 4;
    let list_area = Rect::new(
        area.x + 1,
        top,
        area.width.saturating_sub(2),
        visible as u16,
    );
    let has_scrollbar = total > visible;
    let gutter = if has_scrollbar { 7 } else { 6 };
    let options = Rect::new(
        area.x + 3,
        list_area.y,
        area.width.saturating_sub(gutter),
        list_area.height,
    );
    let scroll = app.resume_picker.list.layout_rows(total, options);
    let row_right = area
        .x
        .saturating_add(area.width.saturating_sub(if has_scrollbar { 4 } else { 3 }));
    crate::mouse::register_region(app, list_area, crate::mouse::MouseTarget::ResumePicker);
    let empty = match app.resume_picker.sessions.is_empty() {
        true => "Loading sessions...",
        false => "No matching sessions",
    };
    if shown.is_empty() {
        f.buffer_mut()
            .set_string(area.x + 3, top, empty, theme::muted_style().bg(bg));
    }
    for (row, &index) in shown.iter().skip(scroll).take(visible).enumerate() {
        let session = &app.resume_picker.sessions[index];
        let y = top + row as u16;
        let selected = scroll + row == app.resume_picker.list.selected();
        let text = if session.title.is_empty() {
            &session.preview
        } else {
            &session.title
        };
        let time = format!("{:10}", relative_time(session.updated_at));
        let id = &session.id[..session.id.len().min(8)];
        let delete_message = if app.resume_picker.deleting.as_deref() == Some(&session.id) {
            Some("Deleting...")
        } else if app.resume_picker.delete_confirm.as_deref() == Some(&session.id) {
            if app.session.session_id.as_deref() == Some(&session.id) {
                Some("Can't delete current session")
            } else {
                Some("Press d again to delete")
            }
        } else {
            None
        };
        if selected {
            super::list_cursor::paint(
                f,
                Rect {
                    y,
                    height: 1,
                    ..options
                },
            );
        }
        let (text_style, _) = super::list_cursor::styles_on(selected, bg);
        let muted = text_style.add_modifier(Modifier::DIM);
        f.buffer_mut().set_string(area.x + 3, y, time, muted);
        f.buffer_mut().set_string(area.x + 15, y, id, muted);
        let locked = app.resume_picker.locked.contains(&session.id);
        let message = delete_message.unwrap_or(text);
        let message_x = area.x + 25;
        // The lock labels the row's trailing status, like the desktop's.
        let lock_width = if locked { 10 } else { 0 };
        let message_width = row_right
            .saturating_sub(message_x)
            .saturating_sub(lock_width) as usize;
        let message = crate::utils::text::ellipsize(message, message_width);
        f.buffer_mut()
            .set_stringn(message_x, y, &message, message_width, text_style);
        if locked {
            f.buffer_mut()
                .set_string(row_right.saturating_sub(10), y, "🔒 locked", muted);
        }
        // The `d` of "Press d again to delete" is styled as a shortcut.
        if let Some(offset) = message.strip_suffix(" again to delete").map(str::len) {
            let shortcut_x = message_x + offset as u16 - 1;
            if shortcut_x < row_right {
                f.buffer_mut().set_string(
                    shortcut_x,
                    y,
                    "d",
                    super::list_cursor::accent(text_style, theme::primary()),
                );
            }
        }
    }
    if has_scrollbar {
        let bar = Rect::new(area.x + area.width - 4, top, 1, visible as u16);
        scrollbar::draw(
            app,
            f,
            crate::mouse::MouseTarget::ResumePicker,
            bar,
            total as u16,
            visible as u16,
            scroll as u16,
        );
    }
    let search = &app.resume_picker.search;
    let help = crate::search_field::hints(
        search.focused,
        !search.query.is_empty(),
        &[
            hints::NAVIGATE,
            hints::SELECT,
            hints::SEARCH,
            ("d", action::DELETE),
            hints::CANCEL,
        ],
    );
    let width = area.width.saturating_sub(4);
    super::hint_line::draw_clipped(f, area.x + 2, area.y + area.height - 2, width, &help);
}

/// The search row under the title; the field owns its clicks.
fn draw_search(app: &mut App, f: &mut Frame, row: Rect) {
    let input = super::search_field::draw_row(
        f,
        row,
        &app.resume_picker.search,
        "Search sessions",
        app.view.cursor_on,
        theme::background(),
    );
    app.resume_picker.search.area = input;
    crate::mouse::register_region(app, input, crate::mouse::MouseTarget::ResumePicker);
    let field = (input.y, input.x, input.right().saturating_sub(1));
    app.view.bottom_app_selection_chrome.push(field);
}

fn relative_time(timestamp: u64) -> String {
    let now = crate::utils::replay_now_ms().unwrap_or_else(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |value| value.as_millis() as u64)
    });
    let seconds = now.saturating_sub(timestamp) / 1_000;
    match seconds {
        0..=59 => "just now".into(),
        60..=3_599 => format!("{}m ago", seconds / 60),
        3_600..=86_399 => format!("{}h ago", seconds / 3_600),
        86_400..=604_799 => format!("{}d ago", seconds / 86_400),
        _ => format!("{}w ago", seconds / 604_800),
    }
}
