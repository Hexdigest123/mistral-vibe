//! Session tabs: registration on session attach, the Ctrl+X chord, queueing
//! while a turn runs, closing and the config gate.

use std::sync::Arc;

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use vibe_rs::app::{App, Status};
use vibe_rs::server::Client;
use vibe_rs::session_tabs::{self, QueuedAction, SessionTabs, Tab};
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

/// Ctrl+X then a key, through the composer handler.
fn chord(app: &mut App, client: &Arc<Client>, second: KeyCode) -> bool {
    assert!(session_tabs::handle_key(
        app,
        client,
        &key(KeyCode::Char('x'), KeyModifiers::CONTROL)
    ));
    assert!(app.session_tabs.chord);
    session_tabs::handle_key(app, client, &key(second, KeyModifiers::NONE))
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
    app.session_tabs.list.push(Tab {
        session_id: Some("00000000-0000-4000-8000-000000000002".into()),
        title: "Second".into(),
        snapshot: None,
    });
    assert!(
        !session_tabs::switchable(&app),
        "off means no switching even with tabs"
    );
    // The chord is inert too.
    let client = Arc::new(Client::stub());
    assert!(!session_tabs::handle_key(
        &mut app,
        &client,
        &key(KeyCode::Char('x'), KeyModifiers::CONTROL)
    ));
    assert!(!app.session_tabs.chord);
}

#[test]
fn ctrl_x_chord_switches_between_tabs() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    assert!(!app.session_tabs.chord, "the chord disarms after one key");
    assert!(session_tabs::switching(&app));
    // The answer lands: the second tab is active.
    app.set_session_id("00000000-0000-4000-8000-000000000002".into());
    assert_eq!(app.session_tabs.active, 1);
    // Ctrl+X 1 goes back.
    assert!(chord(&mut app, &client, KeyCode::Char('1')));
    app.set_session_id("00000000-0000-4000-8000-000000000001".into());
    assert_eq!(app.session_tabs.active, 0);
}

#[test]
fn chord_letter_past_the_last_tab_does_nothing_but_consumes() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    assert!(chord(&mut app, &client, KeyCode::Char('9')));
    assert!(!session_tabs::switching(&app));
    assert_eq!(app.session_tabs.active, 0);
}

#[test]
fn any_other_key_cancels_the_chord() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    assert!(chord(&mut app, &client, KeyCode::Char('z')));
    assert!(!app.session_tabs.chord);
    assert!(!session_tabs::switching(&app));
}

#[test]
fn tab_and_alt_digit_no_longer_switch_tabs() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    assert!(!session_tabs::handle_key(
        &mut app,
        &client,
        &key(KeyCode::Tab, KeyModifiers::NONE)
    ));
    assert!(!session_tabs::handle_key(
        &mut app,
        &client,
        &key(KeyCode::Char('2'), KeyModifiers::ALT)
    ));
    assert!(!session_tabs::switching(&app));
}

#[test]
fn chord_n_opens_a_new_tab() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    assert!(chord(&mut app, &client, KeyCode::Char('n')));
    assert_eq!(app.session_tabs.list.len(), 3);
    assert!(session_tabs::switching(&app));
    app.set_session_id("00000000-0000-4000-8000-000000000007".into());
    assert_eq!(app.session_tabs.active, 2);
    assert_eq!(
        app.session_tabs.list[2].session_id.as_deref(),
        Some("00000000-0000-4000-8000-000000000007")
    );
}

#[test]
fn chord_c_closes_the_active_tab() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    app.session_tabs.active = 1;
    assert!(chord(&mut app, &client, KeyCode::Char('c')));
    // The active tab switches away first; once that lands, it is removed.
    assert!(session_tabs::switching(&app));
    app.set_session_id("00000000-0000-4000-8000-000000000001".into());
    assert_eq!(app.session_tabs.list.len(), 1);
    assert_eq!(app.session_tabs.active, 0);
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
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    assert_eq!(
        app.chat_input.input, "",
        "the target tab's empty draft shows meanwhile"
    );
    session_tabs::on_switch_failed(&mut app, false);
    assert!(!session_tabs::switching(&app));
    assert_eq!(app.session_tabs.active, 0);
    assert_eq!(app.chat_input.input, "draft in tab one");
    assert_eq!(app.session_tabs.list.len(), 2, "the tab stays");
}

#[test]
fn a_switch_to_a_gone_session_removes_its_tab() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    app.chat_input.input = "draft in tab one".into();
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    session_tabs::on_switch_failed(&mut app, true);
    assert_eq!(app.session_tabs.list.len(), 1, "the dead tab is removed");
    assert_eq!(app.session_tabs.active, 0);
    assert_eq!(app.chat_input.input, "draft in tab one");
}

#[test]
fn a_tab_sharing_the_attached_session_switches_locally() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    // The server reused the empty session: both tabs name it.
    app.session_tabs.list[1].session_id = Some("00000000-0000-4000-8000-000000000001".into());
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    assert_eq!(app.session_tabs.active, 1);
    assert!(!session_tabs::switching(&app), "no server round-trip");
}

#[test]
fn a_switch_while_a_turn_runs_is_queued_and_runs_when_idle() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    app.set_status(Status::Generating {
        since: vibe_rs::clock::now(),
    });
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    assert_eq!(app.session_tabs.queued, Some(QueuedAction::Switch(1)));
    assert!(!session_tabs::switching(&app), "nothing is in flight yet");
    // Still busy: the queued switch waits.
    session_tabs::maybe_run_queued(&mut app, &client);
    assert!(!session_tabs::switching(&app));
    assert_eq!(app.session_tabs.queued, Some(QueuedAction::Switch(1)));
    // The turn ends: the queued switch runs.
    app.set_status(Status::Ready);
    session_tabs::maybe_run_queued(&mut app, &client);
    assert_eq!(app.session_tabs.queued, None);
    assert!(session_tabs::switching(&app));
    app.set_session_id("00000000-0000-4000-8000-000000000002".into());
    assert_eq!(app.session_tabs.active, 1);
}

#[test]
fn a_new_tab_while_a_turn_runs_is_queued() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    app.set_status(Status::Generating {
        since: vibe_rs::clock::now(),
    });
    assert!(chord(&mut app, &client, KeyCode::Char('n')));
    assert_eq!(app.session_tabs.queued, Some(QueuedAction::New));
    assert_eq!(app.session_tabs.list.len(), 2);
    app.set_status(Status::Ready);
    session_tabs::maybe_run_queued(&mut app, &client);
    assert_eq!(app.session_tabs.list.len(), 3);
    assert!(session_tabs::switching(&app));
}

#[test]
fn with_one_tab_ctrl_x_n_still_opens_a_new_tab() {
    let client = Arc::new(Client::stub());
    let mut app = ready_app();
    assert!(session_tabs::handle_key(
        &mut app,
        &client,
        &key(KeyCode::Char('x'), KeyModifiers::CONTROL)
    ));
    assert!(app.session_tabs.chord, "the chord arms with a single tab");
    assert!(session_tabs::visible(&app), "the bar shows while armed");
    session_tabs::handle_key(
        &mut app,
        &client,
        &key(KeyCode::Char('n'), KeyModifiers::NONE),
    );
    assert_eq!(app.session_tabs.list.len(), 2);
    assert!(session_tabs::switching(&app));
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
fn ctrl_x_chord_works_through_the_real_input_path() {
    let client = Arc::new(Client::stub());
    let (config_tx, _rx) = tokio::sync::mpsc::channel::<vibe_rs::config::Loaded>(1);
    let mut app = two_tabs();
    vibe_rs::input::handle_key(
        &mut app,
        &client,
        &config_tx,
        key(KeyCode::Char('x'), KeyModifiers::CONTROL),
    );
    assert!(app.session_tabs.chord, "Ctrl+X arms the chord");
    vibe_rs::input::handle_key(
        &mut app,
        &client,
        &config_tx,
        key(KeyCode::Char('2'), KeyModifiers::NONE),
    );
    assert!(!app.session_tabs.chord);
    assert!(session_tabs::switching(&app), "the chord switched tabs");
    assert_eq!(
        app.chat_input.input, "",
        "the digit did not reach the composer"
    );
}

#[test]
fn a_non_tab_chord_key_falls_through_to_the_rail() {
    let client = Arc::new(Client::stub());
    let mut app = ready_app();
    app.goal.goal = Some(
        serde_json::from_value(serde_json::json!({
            "goalId": "goal-1", "revision": 1, "objectiveRevision": 1,
            "objective": "Ship it", "status": "active", "tokenBudget": 50000,
            "tokensUsed": 12500, "timeUsedSeconds": 240,
        }))
        .unwrap(),
    );
    assert!(session_tabs::handle_key(
        &mut app,
        &client,
        &key(KeyCode::Char('x'), KeyModifiers::CONTROL)
    ));
    assert!(app.session_tabs.chord);
    // 'g' is a rail jump letter, not a tab key: the chord cancels and the rail
    // takes the key, as Ctrl+X g would have without the feature.
    session_tabs::handle_key(
        &mut app,
        &client,
        &key(KeyCode::Char('g'), KeyModifiers::NONE),
    );
    assert!(!app.session_tabs.chord);
    assert!(!session_tabs::switching(&app), "no tab switch happened");
    assert_eq!(vibe_rs::rail::window(&app), Some(vibe_rs::rail::Item::Goal));
}

#[test]
fn the_default_is_enabled() {
    assert!(SessionTabs::default().enabled);
}
