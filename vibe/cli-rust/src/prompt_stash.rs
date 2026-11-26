//! Stashed prompts: a LIFO stack behind `/stash`, `/stash list`, `/pop` and Ctrl+X s / p.

use crate::app::{App, Severity};
use crate::commands::simple::add_text;
use crate::{completion_manager, input, long_paste};

const NOTICE_SECS: u64 = 3;
const PREVIEW_CHARS: usize = 72;

/// The stashed prompts, oldest first; a pop takes the last.
#[derive(Default)]
pub struct PromptStash {
    entries: Vec<String>,
}

fn tell(app: &mut App, severity: Severity, text: &str) {
    crate::ui::notice::show(app, severity, text, NOTICE_SECS);
}

fn count(app: &App) -> String {
    match app.prompt_stash.entries.len() {
        1 => "1 prompt stashed".to_owned(),
        n => format!("{n} prompts stashed"),
    }
}

/// Set the composer's draft aside and clear the composer; an empty draft stashes nothing.
pub fn stash_draft(app: &mut App) {
    app.chat_input.normalize_positions();
    let input = &app.chat_input;
    let text = match input.mode.prefix() {
        Some(prefix) => format!("{prefix}{}", input.mentions.expanded(&input.input)),
        None => input.mentions.expanded(&input.input),
    };
    if text.trim().is_empty() {
        return tell(
            app,
            Severity::Warning,
            "Nothing to stash: the prompt is empty.",
        );
    }
    input::reset_history_state(app);
    long_paste::dismiss(app);
    app.chat_input.clear();
    completion_manager::input_changed(app);
    push(app, text);
}

/// `/stash <text>`: stash the given text; the composer is left alone.
pub fn stash_text(app: &mut App, text: &str) {
    push(app, text.to_owned());
}

fn push(app: &mut App, text: String) {
    app.prompt_stash.entries.push(text);
    let message = format!("{}. Pop the latest with /pop or Ctrl+X p.", count(app));
    tell(app, Severity::Information, &message);
}

/// Put the latest stashed prompt at the cursor, as a paste would; says so when none is left.
pub fn pop(app: &mut App) {
    if input::composer_hidden(app) {
        return;
    }
    let Some(text) = app.prompt_stash.entries.pop() else {
        return tell(app, Severity::Information, "No stashed prompts.");
    };
    input::handle_paste(app, text);
    let left = app.prompt_stash.entries.len();
    if left > 0 {
        tell(
            app,
            Severity::Information,
            &format!("{left} still stashed."),
        );
    }
}

/// `/stash list`: the stash newest first, each prompt cut to one line.
pub fn list(app: &mut App) {
    let entries = &app.prompt_stash.entries;
    if entries.is_empty() {
        return add_text(app, "No stashed prompts.");
    }
    let mut lines = vec![format!("## Stash ({})", entries.len()), String::new()];
    for (rank, entry) in entries.iter().rev().enumerate() {
        lines.push(format!("{}. {}", rank + 1, preview(entry)));
    }
    lines.push(String::new());
    lines.push("`/pop` takes number 1 (last in, first out).".to_owned());
    add_text(app, &lines.join("\n"));
}

fn preview(text: &str) -> String {
    let one_line = text.split_whitespace().collect::<Vec<_>>().join(" ");
    match one_line.chars().count() > PREVIEW_CHARS {
        true => format!(
            "{}…",
            one_line.chars().take(PREVIEW_CHARS).collect::<String>()
        ),
        false => one_line,
    }
}

/// `/stash [list|<text>]`: list the stash, stash the text, or explain how to stash the draft.
pub fn command(app: &mut App, args: &str) {
    match args {
        "" => tell(
            app,
            Severity::Information,
            "Stash the draft with Ctrl+X s, or /stash <text>. /stash list shows the stash.",
        ),
        "list" => list(app),
        text => stash_text(app, text),
    }
}
