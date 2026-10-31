//! Fork feature: fzf-style list search (terms, `'exact`, `^prefix`, `suffix$`, `!not`) shared by every picker.

use vibe_rs::utils::fzf::{haystack, rank, Query};

const MODELS: &[&str] = &[
    "Mistral Large 4 mistral-large-4 mistral",
    "Mistral Medium 3.5 mistral-medium-3.5 mistral",
    "OpenAI: GPT-5 openai/gpt-5 openrouter",
    "OpenAI: GPT-5 Mini openai/gpt-5-mini openrouter",
    "Qwen3 Coder qwen/qwen3-coder openrouter",
];

fn names(query: &str) -> Vec<&'static str> {
    rank(MODELS, query, |m| m.to_string(), |_| "")
        .into_iter()
        .map(|i| MODELS[i].split(' ').next().unwrap_or_default())
        .collect()
}

fn found(query: &str) -> Vec<usize> {
    rank(MODELS, query, |m| m.to_string(), |_| "")
}

#[test]
fn a_blank_query_keeps_every_item_in_order() {
    assert_eq!(found(""), [0, 1, 2, 3, 4]);
    assert_eq!(found("   "), [0, 1, 2, 3, 4]);
    assert!(Query::new("  ").is_none());
}

#[test]
fn every_space_separated_term_must_match_anywhere() {
    assert_eq!(found("large 4"), [0]);
    assert_eq!(found("openrouter gpt"), [2, 3]);
    assert_eq!(found("mistral zzz"), Vec::<usize>::new());
}

#[test]
fn matching_is_fuzzy_and_case_insensitive() {
    assert_eq!(found("QWCODER"), [4]);
    assert_eq!(found("mlg4"), [0]);
}

#[test]
fn the_tighter_match_ranks_first() {
    assert_eq!(found("medium")[0], 1);
    assert_eq!(found("gpt5mini")[0], 3);
}

#[test]
fn fzf_operators_narrow_the_match() {
    assert_eq!(found("'gpt-5-mini"), [3]);
    assert_eq!(found("^qwen"), [4]);
    assert_eq!(found("openrouter$"), [2, 3, 4]);
    assert_eq!(found("openai !mini"), [2]);
    assert_eq!(names("^mistral !medium"), ["Mistral"]);
}

#[test]
fn ties_keep_the_list_order() {
    let items = ["theme_b", "theme_a", "theme"];
    let ranked = rank(&items, "theme", |s| s.to_string(), |_| "");
    assert_eq!(ranked.len(), 3);
    assert_eq!(ranked[..2], [0, 1]);
}

#[test]
fn prose_matches_only_verbatim_and_after_every_name_match() {
    let items = [
        ("theme", "Color scheme"),
        ("color_depth", ""),
        ("timeout", ""),
    ];
    let ranked = rank(&items, "color", |i| i.0.to_string(), |i| i.1);
    assert_eq!(ranked, [1, 0]);
    let none = rank(&items, "csm", |i| i.0.to_string(), |i| i.1);
    assert!(none.is_empty(), "fuzzy terms never reach prose");
}

#[test]
fn haystack_joins_distinct_fields() {
    assert_eq!(
        haystack(["GPT-5", "gpt-5", "", "openai/gpt-5", "openrouter"]),
        "GPT-5 openai/gpt-5 openrouter"
    );
}
