//! Fork feature (AGENTS.md): fzf search over the saved sessions, by title, then preview text.

use crate::sessions_page::row::Session;
use crate::utils::fzf;

/// Indices into `sessions` the list shows: best match first, every index in
/// list order without a query. Titles rank fuzzily; previews match verbatim.
pub fn shown(sessions: &[Session], query: &str) -> Vec<usize> {
    fzf::rank(sessions, query, |s| s.title.clone(), |s| &s.preview)
}
