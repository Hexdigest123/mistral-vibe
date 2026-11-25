//! The marker-column icons transcript entries open with: Nerd Font glyphs from
//! the `nerd-font-symbols` icon library, each a single-cell private-use codepoint.

use nerd_font_symbols::{fa, md};

/// A tool call, or a group of them (`nf-fa-wrench`).
pub const TOOL: &str = fa::FA_WRENCH;
/// A reasoning trace (`nf-md-thought_bubble`).
pub const THOUGHT: &str = md::MD_THOUGHT_BUBBLE;
/// A turn's `Worked for` summary (`nf-fa-clock`).
pub const TURN: &str = fa::FA_CLOCK;
/// A scheduled loop's prompt (`nf-fa-rotate_right`).
pub const LOOP: &str = fa::FA_ROTATE_RIGHT;
/// Every marker icon, for chrome detection.
pub const ALL: [&str; 4] = [TOOL, THOUGHT, TURN, LOOP];
/// Cells the marker column takes: the one-cell icon plus its pad.
pub const WIDTH: u16 = 2;
