//! The prompt stash: Ctrl+X s / p and `/stash`, `/stash list`, `/pop` set prompts aside last in, first out.

use crossterm::event::KeyCode;
use vibe_rs::app::App;
use vibe_rs::prompt_stash;

use crate::support::{ctrl, press, send_key, type_text};

fn chord(app: &mut App, second: char) {
    send_key(app, ctrl('x'));
    press(app, KeyCode::Char(second));
}

fn last_row(app: &App) -> String {
    let row = app.view.transcript.last_shown_row().cloned();
    let text = row
        .as_ref()
        .and_then(|row| row["content"][0]["text"].as_str());
    text.unwrap_or_default().to_owned()
}

#[test]
fn ctrl_x_s_stashes_the_draft_and_clears_the_prompt() {
    let mut app = App::default();
    type_text(&mut app, "fix the login bug");
    chord(&mut app, 's');
    assert_eq!(app.chat_input.input, "");
}

#[test]
fn ctrl_x_p_pops_the_latest_stash_first() {
    let mut app = App::default();
    type_text(&mut app, "first");
    chord(&mut app, 's');
    type_text(&mut app, "second");
    chord(&mut app, 's');

    chord(&mut app, 'p');
    assert_eq!(app.chat_input.input, "second");
    app.chat_input.clear();
    chord(&mut app, 'p');
    assert_eq!(app.chat_input.input, "first");
}

#[test]
fn pop_inserts_at_the_cursor_of_a_typed_prompt() {
    let mut app = App::default();
    type_text(&mut app, "stashed");
    chord(&mut app, 's');
    type_text(&mut app, "ab");
    press(&mut app, KeyCode::Left);
    chord(&mut app, 'p');
    assert_eq!(app.chat_input.input, "astashedb");
}

#[test]
fn pop_with_nothing_stashed_leaves_the_prompt_alone() {
    let mut app = App::default();
    type_text(&mut app, "draft");
    chord(&mut app, 'p');
    assert_eq!(app.chat_input.input, "draft");
}

#[test]
fn stashing_an_empty_prompt_stashes_nothing() {
    let mut app = App::default();
    chord(&mut app, 's');
    chord(&mut app, 'p');
    assert_eq!(app.chat_input.input, "");
}

#[test]
fn a_collapsed_paste_is_stashed_in_full() {
    let mut app = App::default();
    let long = "line\n".repeat(30);
    vibe_rs::input::handle_paste(&mut app, long.clone());
    chord(&mut app, 's');
    app.chat_input.clear();
    prompt_stash::pop(&mut app);
    assert_eq!(
        app.chat_input.mentions.expanded(&app.chat_input.input),
        long
    );
}

#[test]
fn slash_stash_text_then_pop_returns_it() {
    let mut app = App::default();
    prompt_stash::command(&mut app, "write the changelog");
    prompt_stash::pop(&mut app);
    assert_eq!(app.chat_input.input, "write the changelog");
}

#[test]
fn stash_list_shows_the_newest_first_on_one_line_each() {
    let mut app = App::default();
    prompt_stash::command(&mut app, "older prompt");
    prompt_stash::command(&mut app, "newer\nprompt");
    prompt_stash::command(&mut app, "list");
    let list = last_row(&app);
    let newer = list.find("1. newer prompt").expect(&list);
    let older = list.find("2. older prompt").expect(&list);
    assert!(newer < older, "{list}");
    assert!(list.contains("## Stash (2)"), "{list}");
}

#[test]
fn stash_list_over_an_empty_stash_says_so() {
    let mut app = App::default();
    prompt_stash::command(&mut app, "list");
    assert_eq!(last_row(&app), "No stashed prompts.");
}

#[test]
fn a_long_prompt_is_cut_in_the_list() {
    let mut app = App::default();
    prompt_stash::command(&mut app, &"x".repeat(200));
    prompt_stash::command(&mut app, "list");
    let list = last_row(&app);
    assert!(
        list.contains('…') && !list.contains(&"x".repeat(100)),
        "{list}"
    );
}

#[test]
fn ctrl_s_still_swaps_its_own_single_slot() {
    let mut app = App::default();
    type_text(&mut app, "slot");
    send_key(&mut app, ctrl('s'));
    assert_eq!(app.chat_input.input, "");
    chord(&mut app, 'p');
    assert_eq!(app.chat_input.input, "", "Ctrl+S does not feed the stack");
    send_key(&mut app, ctrl('s'));
    assert_eq!(app.chat_input.input, "slot");
}
