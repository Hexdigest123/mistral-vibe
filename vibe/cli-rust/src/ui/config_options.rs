//! Config option row construction.

use super::config::{Opt, CURSOR_W, GAP, NAME_W, VALUE_W};
use crate::config::ConfigField;
use crate::config_fields::section_label;

pub(super) fn build_lines(fields: &[ConfigField], sections: bool) -> Vec<Opt> {
    if !sections {
        return fields
            .iter()
            .enumerate()
            .map(|(index, field)| row(index, field))
            .collect();
    }
    // `fields` arrives in section order (config::filtered sorts by rank), so a
    // new section starts whenever the category changes.
    let mut out: Vec<Opt> = Vec::new();
    let mut current: Option<&str> = None;
    for (rank, field) in fields.iter().enumerate() {
        if current != Some(field.category.as_str()) {
            if current.is_some() {
                out.push(Opt::Blank);
                out.push(Opt::Blank);
            }
            out.push(Opt::Section(section_label(&field.category)));
            out.push(Opt::Blank);
            out.push(Opt::Header(columns_header()));
            current = Some(field.category.as_str());
        }
        out.push(row(rank, field));
    }
    out
}

fn row(index: usize, field: &ConfigField) -> Opt {
    Opt::Row {
        index,
        name: truncate(&field.name, NAME_W),
        value: truncate(&field.display_value(), VALUE_W),
        dangerous: field.dangerous,
    }
}

fn columns_header() -> String {
    format!(
        "{}{:<name$}{}VALUE",
        " ".repeat(CURSOR_W),
        "SETTING",
        " ".repeat(GAP),
        name = NAME_W
    )
}

fn truncate(value: &str, width: usize) -> String {
    let count = value.chars().count();
    if count <= width {
        return value.to_owned();
    }
    if width <= 1 {
        return value.chars().take(width).collect();
    }
    let head: String = value.chars().take(width - 1).collect();
    format!("{head}…")
}
