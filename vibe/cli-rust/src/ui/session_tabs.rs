//! The session tab bar: one row above the conversation, shown when more than
//! one tab is open. A click switches, a middle click closes.

use ratatui::layout::Rect;
use ratatui::style::Color;
use ratatui::Frame;
use unicode_width::UnicodeWidthStr;

use super::{hint_line, list_cursor, theme};
use crate::app::App;
use crate::hints::{action, key};
use crate::session_tabs::Activity;
use crate::utils::text::ellipsize;

/// Longest label a tab cell shows, number and padding included.
const MAX_CELL: u16 = 26;

/// The glyph and color of a tab running (`●`), waiting (`!`) or done (`✓`) in the background.
fn marker(activity: Activity) -> Option<(&'static str, Color)> {
    match activity {
        Activity::Idle => None,
        Activity::Running => Some(("●", theme::primary())),
        Activity::Waiting => Some(("!", theme::warning())),
        Activity::Done => Some(("✓", theme::success())),
    }
}

/// The bar's height: one row when tabs are visible, else none.
pub fn height(app: &App) -> u16 {
    u16::from(crate::session_tabs::visible(app))
}

/// Draw the bar into `area` and record each tab's painted cell for clicks.
pub fn draw(app: &mut App, f: &mut Frame, area: Rect) {
    app.session_tabs.areas.clear();
    if area.width == 0 || area.height == 0 {
        return;
    }
    crate::mouse::register_region(app, area, crate::mouse::MouseTarget::TabBar);
    let mut x = area.x;
    for (index, tab) in app.session_tabs.list.iter().enumerate() {
        let mark = marker(tab.activity);
        let room = MAX_CELL as usize - 3 - 2 * usize::from(mark.is_some());
        let head = format!("{} ", index + 1);
        let glyph = mark
            .map(|(glyph, _)| format!("{glyph} "))
            .unwrap_or_default();
        let label = format!("{head}{glyph}{}", ellipsize(&tab.title, room));
        let width = (label.width() as u16 + 2)
            .min(MAX_CELL)
            .min(area.right().saturating_sub(x));
        if width == 0 {
            break;
        }
        let cell = Rect {
            x,
            y: area.y,
            width,
            height: 1,
        };
        app.session_tabs.areas.push(cell);
        let active = index == app.session_tabs.active;
        let style = if active {
            list_cursor::paint(f, cell);
            list_cursor::style()
        } else {
            theme::muted_style()
        };
        let padded = list_cursor::padded(&label, width as usize);
        f.buffer_mut()
            .set_stringn(x, area.y, padded, width as usize, style);
        if let Some((glyph, color)) = mark {
            let at = x + head.width() as u16;
            if at < x + width {
                let style = style.fg(color);
                f.buffer_mut().set_stringn(at, area.y, glyph, 1, style);
            }
        }
        x += width + 1;
    }
    let hints = if app.session_tabs.chord {
        [(key::CTRL_X, action::TAB_CHORD)]
    } else {
        [(key::CTRL_X, action::TABS)]
    };
    let width = crate::hints::width(&hints);
    if width < area.width {
        hint_line::draw(
            f,
            Rect {
                x: area.right() - width,
                y: area.y,
                width,
                height: 1,
            },
            &hints,
        );
    }
}
