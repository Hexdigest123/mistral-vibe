//! The editor's title: the readable label, then the raw config.toml key, dim.

use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span};

use super::super::theme;
use crate::config_fields::ConfigField;
use crate::utils::text::ellipsize;

/// `─ Label  raw_key ` fitted to a box `width` columns wide; the key is the first to shrink.
pub(super) fn line(field: &ConfigField, width: u16) -> Line<'static> {
    let label = field.label();
    let mut spans = vec![
        Span::raw("─ "),
        Span::styled(label.clone(), Style::default().add_modifier(Modifier::BOLD)),
    ];
    let used = 2 + label.chars().count() + 1;
    let room = usize::from(width).saturating_sub(2 + used + 2);
    if label.to_lowercase() != field.name && room >= 4 {
        spans.push(Span::styled(
            format!("  {}", ellipsize(&field.name, room)),
            theme::dim(theme::muted()),
        ));
    }
    spans.push(Span::raw(" "));
    Line::from(spans)
}
