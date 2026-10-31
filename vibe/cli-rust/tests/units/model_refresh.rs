//! Fork feature: `/model refresh` reports each `discover = true` provider's count and failures.

use serde_json::json;
use vibe_rs::commands::model_refresh::{summary, NO_PROVIDER};
use vibe_rs::commands::CommandEvent;

fn entry(provider: &str, ids: &[&str]) -> serde_json::Value {
    json!({"providerName": provider, "endpoint": "https://x/models", "modelIds": ids})
}

#[test]
fn a_refresh_lists_each_providers_count() {
    let answer = json!({"entries": [entry("openrouter", &["a", "b"]), entry("local", &["c"])], "errors": []});
    let CommandEvent::Status(text) = summary(&answer) else {
        panic!("a clean refresh is a status");
    };
    assert_eq!(text, "Models refreshed: openrouter 2, local 1");
}

#[test]
fn a_failed_provider_is_an_error_that_still_counts_what_is_listed() {
    let answer = json!({"entries": [entry("openrouter", &["a"])], "errors": ["local: HTTP 503"]});
    let CommandEvent::Error(text) = summary(&answer) else {
        panic!("a failed provider is an error");
    };
    assert_eq!(
        text,
        "Could not refresh local: HTTP 503; models listed: openrouter 1"
    );
}

#[test]
fn nothing_to_refresh_says_what_to_configure() {
    let CommandEvent::Status(text) = summary(&json!({"entries": [], "errors": []})) else {
        panic!("no provider is a status");
    };
    assert_eq!(text, NO_PROVIDER);
    assert!(matches!(summary(&json!({})), CommandEvent::Status(_)));
}
