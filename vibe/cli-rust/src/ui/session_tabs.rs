//! The session tab bar: one row above the conversation, shown when more than
//! one tab is open. A click switches, a middle click closes.

use ratatui::layout::Rect;
use ratatui::Frame;
use unicode_width::UnicodeWidthStr;

use super::{hint_line, list_cursor, theme};
use crate::app::App;
use crate::hints::{action, key};
use crate::utils::text::ellipsize;

/// Longest label a tab cell shows, number and padding included.
const MAX_CELL: u16 = 26;

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
        let label = format!(
            "{} {}",
            index + 1,
            ellipsize(&tab.title, MAX_CELL as usize - 3)
        );
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
