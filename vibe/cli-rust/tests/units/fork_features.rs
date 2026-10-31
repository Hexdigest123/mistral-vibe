//! Fork features must survive every upstream merge (root AGENTS.md "Fork features"): never delete or weaken these.

use vibe_rs::utils::fzf;

#[test]
fn model_refresh_is_the_model_commands_argument() {
    assert_eq!(
        vibe_rs::commands::argument_hint(Some('/'), "model "),
        Some("[refresh]"),
        "fork feature dropped: `/model refresh`"
    );
}

#[test]
fn paste_image_is_registered_on_linux_and_macos() {
    assert_eq!(
        vibe_rs::commands::has_command("/paste-image"),
        cfg!(any(target_os = "linux", target_os = "macos")),
        "fork feature dropped: Linux clipboard image paste"
    );
}

#[test]
fn every_searchable_list_ranks_with_fzf_terms() {
    let items = [
        "Qwen3 Coder qwen3-coder local",
        "Qwen3 Coder qwen/qwen3-coder openrouter",
    ];
    let ranked = fzf::rank(&items, "coder openrouter", |s| s.to_string(), |_| "");
    assert_eq!(ranked, [1], "fork feature dropped: fzf list search");
    // The long lists that search: dropping one breaks this build.
    let _ = vibe_rs::model_picker::search_key;
    let _ = vibe_rs::resume_picker::search::shown;
    let _ = vibe_rs::config_edit::search::searchable;
}

#[test]
#[cfg(target_os = "linux")]
fn linux_clipboard_takes_every_image_type_and_file_copies() {
    use vibe_rs::paste_image::linux::{best_image_type, parse_uri_list, URI_LIST};

    let jpeg_only = vec!["image/jpeg".to_owned()];
    assert_eq!(best_image_type(&jpeg_only), Some("image/jpeg"));
    assert_eq!(URI_LIST, "text/uri-list");
    assert_eq!(parse_uri_list("file:///tmp/a.png").len(), 1);
}
