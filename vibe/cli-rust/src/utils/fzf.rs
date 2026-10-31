//! fzf-style list search on nucleo, case-insensitive: every space-separated term must match, with `'exact`, `^prefix`, `suffix$` and `!not`.

use std::cell::RefCell;
use std::cmp::Reverse;

use nucleo_matcher::pattern::{AtomKind, CaseMatching, Normalization, Pattern};
use nucleo_matcher::{Config, Matcher, Utf32Str};

thread_local! {
    // Reused: a matcher allocates its scoring matrix up front.
    static MATCHER: RefCell<Matcher> = RefCell::new(Matcher::new(Config::DEFAULT));
}

/// A parsed list query: fzf terms for names, verbatim terms for prose.
pub struct Query {
    fuzzy: Pattern,
    verbatim: Pattern,
}

impl Query {
    /// `None` for a query with no terms, which lists every row.
    pub fn new(query: &str) -> Option<Self> {
        let fuzzy = Pattern::parse(query, CaseMatching::Ignore, Normalization::Smart);
        let verbatim = Pattern::new(
            query,
            CaseMatching::Ignore,
            Normalization::Smart,
            AtomKind::Substring,
        );
        (!fuzzy.atoms.is_empty()).then_some(Self { fuzzy, verbatim })
    }

    /// fzf's score for `text`, higher is better; `None` when a term misses.
    pub fn score(&self, text: &str) -> Option<u32> {
        score(&self.fuzzy, text)
    }

    /// The score when every term appears as typed: fuzzy terms match most prose.
    pub fn score_verbatim(&self, text: &str) -> Option<u32> {
        score(&self.verbatim, text)
    }
}

fn score(pattern: &Pattern, text: &str) -> Option<u32> {
    let mut buf = Vec::new();
    MATCHER.with_borrow_mut(|matcher| pattern.score(Utf32Str::new(text, &mut buf), matcher))
}

/// Indices of the `items` matching `query`, best first: fzf on `name`, then
/// verbatim terms in `prose`. Ties keep the list's own order (popular first,
/// newest first), and a blank query keeps every item in it.
pub fn rank<T>(
    items: &[T],
    query: &str,
    name: impl Fn(&T) -> String,
    prose: impl Fn(&T) -> &str,
) -> Vec<usize> {
    let Some(query) = Query::new(query) else {
        return (0..items.len()).collect();
    };
    let mut ranked: Vec<_> = items
        .iter()
        .enumerate()
        .filter_map(|(index, item)| {
            let name = name(item);
            let (tier, score) = match query.score(&name) {
                Some(score) => (0, score),
                None => (1, query.score_verbatim(prose(item))?),
            };
            Some((tier, Reverse(score), index))
        })
        .collect();
    ranked.sort_unstable();
    ranked.into_iter().map(|(.., index)| index).collect()
}

/// `fields` joined for one fzf haystack, skipping blanks and repeats.
pub fn haystack<'a>(fields: impl IntoIterator<Item = &'a str>) -> String {
    let mut seen: Vec<&str> = Vec::new();
    for field in fields {
        if !field.is_empty() && !seen.iter().any(|kept| kept.eq_ignore_ascii_case(field)) {
            seen.push(field);
        }
    }
    seen.join(" ")
}
