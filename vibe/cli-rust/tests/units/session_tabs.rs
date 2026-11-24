//! Session tabs: registration on session attach, switching, closing and the config gate.

use std::sync::Arc;

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use vibe_rs::app::{App, Status};
use vibe_rs::focus::tab_navigates;
use vibe_rs::server::Client;
use vibe_rs::session_tabs::{self, SessionTabs, Tab};
use vibe_rs::sessions_page::Switching;

fn ready_app() -> App {
    let mut app = App::default();
    app.set_status(Status::Ready);
    app.set_session_id("00000000-0000-4000-8000-000000000001".into());
    app
}

fn two_tabs() -> App {
    let mut app = ready_app();
    app.session_tabs.list.push(Tab {
        session_id: Some("00000000-0000-4000-8000-000000000002".into()),
        title: "Second".into(),
        snapshot: None,
    });
    app
}

fn key(code: KeyCode, modifiers: KeyModifiers) -> KeyEvent {
    KeyEvent::new(code, modifiers)
}

#[test]
fn the_startup_session_becomes_the_first_tab() {
    let app = ready_app();
    assert_eq!(app.session_tabs.list.len(), 1);
    assert_eq!(app.session_tabs.active, 0);
    assert_eq!(
        app.session_tabs.list[0].session_id.as_deref(),
        Some("00000000-0000-4000-8000-000000000001")
    );
    // Re-attaching the same session changes nothing.
    let mut app = app;
    app.set_session_id("00000000-0000-4000-8000-000000000001".into());
    assert_eq!(app.session_tabs.list.len(), 1);
    assert_eq!(app.session_tabs.active, 0);
}

#[test]
fn an_in_place_replacement_keeps_the_active_tab() {
    let mut app = two_tabs();
    app.set_session_id("00000000-0000-4000-8000-000000000009".into());
    assert_eq!(app.session_tabs.list.len(), 2);
    assert_eq!(app.session_tabs.active, 0);
    assert_eq!(
        app.session_tabs.list[0].session_id.as_deref(),
        Some("00000000-0000-4000-8000-000000000009")
    );
}

#[test]
fn the_sessions_page_opening_a_session_adds_a_tab() {
    let mut app = ready_app();
    let previous = app.view.transcript.snapshot();
    app.sessions_page.switching = Some(Switching {
        id: "00000000-0000-4000-8000-000000000002".into(),
        previous,
        scroll: (0, 0),
        from_page: true,
    });
    app.set_session_id("00000000-0000-4000-8000-000000000002".into());
    assert_eq!(app.session_tabs.list.len(), 2);
    assert_eq!(app.session_tabs.active, 1);
    assert!(
        app.session_tabs.list[0].snapshot.is_some(),
        "the tab left keeps its view"
    );
}

#[test]
fn reopening_an_open_tab_switches_to_it() {
    let mut app = two_tabs();
    app.session_tabs.active = 1;
    let previous = app.view.transcript.snapshot();
    app.sessions_page.switching = Some(Switching {
        id: "00000000-0000-4000-8000-000000000001".into(),
        previous,
        scroll: (0, 0),
        from_page: true,
    });
    app.set_session_id("00000000-0000-4000-8000-000000000001".into());
    assert_eq!(app.session_tabs.list.len(), 2, "no duplicate tab");
    assert_eq!(app.session_tabs.active, 0);
}

#[test]
fn disabled_config_keeps_the_feature_inert() {
    let mut app = App::default();
    session_tabs::set_enabled(&mut app, false);
    app.set_session_id("00000000-0000-4000-8000-000000000001".into());
    assert!(app.session_tabs.list.is_empty());
    assert!(!session_tabs::switchable(&app));
    assert!(!tab_navigates(&app));
    app.session_tabs.list.push(Tab {
        session_id: Some("00000000-0000-4000-8000-000000000002".into()),
        title: "Second".into(),
        snapshot: None,
    });
    assert!(
        !session_tabs::switchable(&app),
        "off means no switching even with tabs"
    );
}

#[test]
fn tab_key_steps_and_wraps_through_the_tabs() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    assert!(tab_navigates(&app), "the composer's Tab switches tabs now");
    assert!(session_tabs::handle_key(
        &mut app,
        &client,
        &key(KeyCode::Tab, KeyModifiers::NONE)
    ));
    assert!(session_tabs::switching(&app));
    // The answer lands: the second tab is active.
    app.set_session_id("00000000-0000-4000-8000-000000000002".into());
    assert_eq!(app.session_tabs.active, 1);
    // Shift+Tab wraps back to the first tab.
    assert!(session_tabs::handle_key(
        &mut app,
        &client,
        &key(KeyCode::BackTab, KeyModifiers::SHIFT)
    ));
    app.set_session_id("00000000-0000-4000-8000-000000000001".into());
    assert_eq!(app.session_tabs.active, 0);
}

#[test]
fn alt_digit_jumps_to_a_numbered_tab() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    assert!(session_tabs::handle_key(
        &mut app,
        &client,
        &key(KeyCode::Char('2'), KeyModifiers::ALT)
    ));
    app.set_session_id("00000000-0000-4000-8000-000000000002".into());
    assert_eq!(app.session_tabs.active, 1);
    // A digit past the last tab does nothing.
    let mut app = two_tabs();
    assert!(!session_tabs::handle_key(
        &mut app,
        &client,
        &key(KeyCode::Char('9'), KeyModifiers::ALT)
    ));
}

#[test]
fn closing_an_inactive_tab_keeps_the_active_one() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    app.session_tabs.list.push(Tab {
        session_id: Some("00000000-0000-4000-8000-000000000003".into()),
        title: "Third".into(),
        snapshot: None,
    });
    app.session_tabs.active = 1;
    session_tabs::close(&mut app, &client, 2);
    assert_eq!(app.session_tabs.list.len(), 2);
    assert_eq!(app.session_tabs.active, 1);
}

#[test]
fn the_last_tab_is_not_closed() {
    let client = Arc::new(Client::stub());
    let mut app = ready_app();
    session_tabs::close(&mut app, &client, 0);
    assert_eq!(app.session_tabs.list.len(), 1);
}

#[test]
fn a_failed_switch_restores_the_left_tab() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    app.chat_input.input = "draft in tab one".into();
    assert!(session_tabs::handle_key(
        &mut app,
        &client,
        &key(KeyCode::Tab, KeyModifiers::NONE)
    ));
    assert_eq!(
        app.chat_input.input, "",
        "the target tab's empty draft shows meanwhile"
    );
    session_tabs::on_switch_failed(&mut app);
    assert!(!session_tabs::switching(&app));
    assert_eq!(app.session_tabs.active, 0);
    assert_eq!(app.chat_input.input, "draft in tab one");
}

#[test]
fn new_tab_starts_a_fresh_session_and_lands_on_it() {
    let client = Arc::new(Client::stub());
    let mut app = ready_app();
    session_tabs::new_tab(&mut app, &client);
    assert_eq!(app.session_tabs.list.len(), 2);
    assert!(
        app.session_tabs.list[1].session_id.is_none(),
        "until the server answers"
    );
    app.set_session_id("00000000-0000-4000-8000-000000000007".into());
    assert_eq!(app.session_tabs.active, 1);
    assert_eq!(
        app.session_tabs.list[1].session_id.as_deref(),
        Some("00000000-0000-4000-8000-000000000007")
    );
}

#[test]
fn the_default_is_enabled() {
    assert!(SessionTabs::default().enabled);
}
