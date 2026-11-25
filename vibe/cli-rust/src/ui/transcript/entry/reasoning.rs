//! A reasoning trace: its `Thinking`/`Thought` row, folding its text.

use ratatui::style::Modifier;
use ratatui::text::{Line, Span};

use crate::selection::{fold, Fold};
use crate::ui::markdown::LinkedLines;
use crate::ui::{icons, pulse, theme};

pub(super) fn push_reasoning(
    lines: &mut LinkedLines,
    text: &str,
    in_progress: bool,
    local: bool,
    expanded: bool,
    pulse_frame: usize,
    width: u16,
) {
    let marker = if in_progress {
        pulse::glyph(pulse_frame).to_string()
    } else if local {
        "■".to_string()
    } else {
        icons::THOUGHT.to_string()
    };
    let label = if in_progress { "Thinking" } else { "Thought" };
    let style = theme::muted_style();
    // The icon carries the fold state on every theme: muted folded, bold unfolded.
    let marker_style = if !in_progress && !local && expanded {
        theme::text(theme::foreground()).add_modifier(Modifier::BOLD)
    } else {
        style
    };
    lines.push(Line::from(vec![
        Span::styled(format!("{marker} "), marker_style),
        Span::styled(label, style),
    ]));
    if !expanded {
        return;
    }
    // `.reasoning-message-content` pads two cells on each side; the body hangs under the icon column.
    let pad = " ".repeat(icons::WIDTH as usize);
    let body_width = width.saturating_sub(icons::WIDTH + 2) as usize;
    for line in text.lines() {
        for (row, gap) in fold::wrap_hard(line, body_width) {
            let row = Line::from(Span::styled(format!("{pad}{row}"), style));
            lines.push_folded(row, Fold::hung(gap, icons::WIDTH));
        }
    }
}
