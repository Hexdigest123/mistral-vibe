//! The Ctrl+X chord: m opens the model picker, c the settings, with tabs on or off; other keys reach the rail.

use crossterm::event::KeyCode;
use vibe_rs::app::App;
use vibe_rs::rail::Item;

use crate::rail::with_items;
use crate::support::{ctrl, press, send_key};

fn tabs_off() -> App {
    let mut app = App::default();
    vibe_rs::session_tabs::set_enabled(&mut app, false);
    app
}

#[test]
fn ctrl_x_m_opens_the_model_picker() {
    let mut app = App::default();
    send_key(&mut app, ctrl('x'));
    press(&mut app, KeyCode::Char('m'));
    assert!(app.model_picker.open);
    assert!(!app.session_tabs.chord, "the chord is spent");
}

#[test]
fn ctrl_x_c_opens_the_settings() {
    let mut app = App::default();
    send_key(&mut app, ctrl('x'));
    press(&mut app, KeyCode::Char('c'));
    assert!(app.config_screen.open);
}

#[test]
fn the_chord_keys_work_with_tabs_off() {
    let mut app = tabs_off();
    send_key(&mut app, ctrl('x'));
    assert!(!app.session_tabs.chord, "tabs are off: no tab chord");
    press(&mut app, KeyCode::Char('m'));
    assert!(app.model_picker.open);

    let mut app = tabs_off();
    send_key(&mut app, ctrl('x'));
    press(&mut app, KeyCode::Char('c'));
    assert!(app.config_screen.open);
}

#[test]
fn the_chord_is_one_key_only() {
    let mut app = App::default();
    send_key(&mut app, ctrl('x'));
    press(&mut app, KeyCode::Char('z'));
    press(&mut app, KeyCode::Char('m'));
    assert!(!app.model_picker.open, "m alone is just text");
    assert_eq!(app.chat_input.input, "m");
}

#[test]
fn with_tabs_off_a_rail_letter_still_follows_ctrl_x() {
    let mut app = with_items(true);
    vibe_rs::session_tabs::set_enabled(&mut app, false);
    send_key(&mut app, ctrl('x'));
    assert!(
        app.rail.letters,
        "with tabs off the rail still shows its letters"
    );
    press(&mut app, KeyCode::Char('d'));
    assert_eq!(vibe_rs::rail::window(&app), Some(Item::Plan));
}

#[test]
fn a_chord_key_after_a_modified_key_is_not_a_chord() {
    let mut app = tabs_off();
    send_key(&mut app, ctrl('x'));
    send_key(&mut app, ctrl('a'));
    press(&mut app, KeyCode::Char('p'));
    assert_eq!(app.chat_input.input, "p");
}
