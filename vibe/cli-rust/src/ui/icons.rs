//! The marker-column icons transcript entries open with: plain single-cell
//! glyphs every terminal font ships, no Nerd Font required.

/// A tool call, or a group of them (`●`).
pub const TOOL: &str = "●";
/// A reasoning trace (`○`).
pub const THOUGHT: &str = "○";
/// A turn's `Worked for` summary (`◷`).
pub const TURN: &str = "◷";
/// A scheduled loop's prompt (`↻`).
pub const LOOP: &str = "↻";
/// Every marker icon, for chrome detection.
pub const ALL: [&str; 4] = [TOOL, THOUGHT, TURN, LOOP];
/// Cells the marker column takes: the one-cell icon plus its pad.
pub const WIDTH: u16 = 2;
