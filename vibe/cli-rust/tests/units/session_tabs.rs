//! Session tabs: registration on session attach, the Ctrl+X chord, switches while
//! a turn runs, empty tabs, closing and the config gate.

use std::sync::Arc;

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use serde_json::json;
use vibe_rs::app::{App, Status};
use vibe_rs::server::Client;
use vibe_rs::session_tabs::{self, Activity, SessionTabs, Tab};
use vibe_rs::sessions_page::Switching;

/// One server-owned entry: the session was used, so the server keeps it when it is left.
fn write_history(app: &mut App) {
    app.view.transcript.add(&json!({"entry": {
        "id": "user-1", "type": "message", "role": "user", "source": "user",
        "content": [{"type": "text", "text": "hi"}], "generationStatus": "completed",
        "sessionId": "s", "createdAt": 1u64, "updatedAt": 1u64, "turnId": "t1",
        "relatedEntryId": null,
    }}));
}

fn busy() -> Status {
    Status::Generating {
        since: vibe_rs::clock::now(),
    }
}

/// A used session on the first tab.
fn ready_app() -> App {
    let mut app = empty_app();
    write_history(&mut app);
    app
}

/// A session nothing was run in: the server drops it once it is left.
fn empty_app() -> App {
    let mut app = App::default();
    app.set_status(Status::Ready);
    app.set_session_id("00000000-0000-4000-8000-000000000001".into());
    app
}

fn second_tab() -> Tab {
    let id = "00000000-0000-4000-8000-000000000002";
    Tab::new(Some(id.into()), "Second".into())
}

fn two_tabs() -> App {
    let mut app = ready_app();
    app.session_tabs.list.push(second_tab());
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
    app.session_tabs.list.push(second_tab());
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
fn chord_w_closes_the_active_tab() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    app.session_tabs.active = 1;
    assert!(chord(&mut app, &client, KeyCode::Char('w')));
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
    let third = "00000000-0000-4000-8000-000000000003";
    app.session_tabs
        .list
        .push(Tab::new(Some(third.into()), "Third".into()));
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

const SECOND: &str = "00000000-0000-4000-8000-000000000002";
const FIRST: &str = "00000000-0000-4000-8000-000000000001";

#[test]
fn a_switch_while_a_turn_runs_starts_at_once_and_leaves_the_turn_running() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    app.set_status(busy());
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    assert!(session_tabs::switching(&app), "no waiting for the turn");
    app.set_session_id(SECOND.into());
    assert_eq!(app.session_tabs.active, 1);
    assert_eq!(app.session_tabs.list.len(), 2, "the busy tab stays");
    assert_eq!(app.session_tabs.list[0].activity, Activity::Running);
    assert_eq!(app.session_tabs.list[1].activity, Activity::Idle);
    assert!(
        app.session_tabs.poll_at.is_some(),
        "a background tab is polled"
    );
}

#[test]
fn a_new_tab_while_a_turn_runs_opens_at_once() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    app.set_status(busy());
    assert!(chord(&mut app, &client, KeyCode::Char('n')));
    assert_eq!(app.session_tabs.list.len(), 3);
    assert!(session_tabs::switching(&app));
    app.set_session_id("00000000-0000-4000-8000-000000000007".into());
    assert_eq!(app.session_tabs.active, 2);
    assert_eq!(app.session_tabs.list[0].activity, Activity::Running);
}

#[test]
fn closing_the_busy_active_tab_does_not_wait_for_its_turn() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    app.set_status(busy());
    assert!(chord(&mut app, &client, KeyCode::Char('w')));
    assert!(session_tabs::switching(&app));
    app.set_session_id(SECOND.into());
    assert_eq!(app.session_tabs.list.len(), 1);
}

#[test]
fn no_poll_is_armed_without_a_background_tab() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    app.set_session_id(SECOND.into());
    assert_eq!(app.session_tabs.list[0].activity, Activity::Idle);
    assert!(app.session_tabs.poll_at.is_none());
}

#[test]
fn nothing_is_left_while_the_session_starts_or_compacts() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    app.set_status(Status::Starting);
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    session_tabs::new_tab(&mut app, &client);
    assert!(!session_tabs::switching(&app));
    assert_eq!(app.session_tabs.list.len(), 2, "no orphan tab is opened");

    let mut app = two_tabs();
    app.compacting = true;
    session_tabs::new_tab(&mut app, &client);
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    assert!(!session_tabs::switching(&app));
    assert_eq!(app.session_tabs.list.len(), 2);
}

fn poll_answer(rows: &[(&str, &str)]) -> session_tabs::Event {
    let rows = rows
        .iter()
        .map(|(id, status)| (id.to_string(), status.to_string()));
    session_tabs::Event(Some(rows.collect()))
}

/// Two tabs on the second, the first running in the background.
fn background_app() -> App {
    let mut app = two_tabs();
    app.session_tabs.active = 1;
    app.session_tabs.list[0].activity = Activity::Running;
    app.session.session_id = Some(SECOND.into());
    app
}

#[test]
fn a_poll_marks_a_finished_background_tab_done_and_stops_polling() {
    let mut app = background_app();
    session_tabs::apply_event(&mut app, poll_answer(&[(FIRST, "idle")]));
    assert_eq!(app.session_tabs.list[0].activity, Activity::Done);
    assert!(app.session_tabs.poll_at.is_none(), "nothing runs any more");
}

#[test]
fn a_poll_keeps_a_running_tab_running_and_polls_on() {
    let mut app = background_app();
    session_tabs::apply_event(&mut app, poll_answer(&[(FIRST, "running")]));
    assert_eq!(app.session_tabs.list[0].activity, Activity::Running);
    assert!(app.session_tabs.poll_at.is_some());
    session_tabs::apply_event(&mut app, poll_answer(&[(FIRST, "blocked")]));
    assert_eq!(app.session_tabs.list[0].activity, Activity::Waiting);
    assert!(
        app.session_tabs.poll_at.is_some(),
        "a waiting turn still counts"
    );
}

#[test]
fn a_failed_poll_keeps_the_marks_and_tries_again() {
    let mut app = background_app();
    session_tabs::apply_event(&mut app, session_tabs::Event(None));
    assert_eq!(app.session_tabs.list[0].activity, Activity::Running);
    assert!(app.session_tabs.poll_at.is_some());
}

#[test]
fn a_session_the_server_no_longer_lists_loses_its_mark() {
    let mut app = background_app();
    session_tabs::apply_event(&mut app, poll_answer(&[]));
    assert_eq!(app.session_tabs.list[0].activity, Activity::Idle);
}

#[test]
fn switching_to_a_done_tab_clears_its_mark() {
    let client = Arc::new(Client::stub());
    let mut app = background_app();
    session_tabs::apply_event(&mut app, poll_answer(&[(FIRST, "idle")]));
    assert!(chord(&mut app, &client, KeyCode::Char('1')));
    app.set_session_id(FIRST.into());
    assert_eq!(app.session_tabs.list[0].activity, Activity::Idle);
    assert_eq!(app.session_tabs.active, 0);
}

#[test]
fn an_empty_tab_is_dropped_once_the_switch_away_lands() {
    let client = Arc::new(Client::stub());
    let mut app = empty_app();
    app.session_tabs.list.push(second_tab());
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    assert_eq!(
        app.session_tabs.list.len(),
        2,
        "still there while in flight"
    );
    app.set_session_id(SECOND.into());
    assert_eq!(app.session_tabs.list.len(), 1);
    assert_eq!(app.session_tabs.active, 0);
    assert_eq!(app.session_tabs.list[0].session_id.as_deref(), Some(SECOND));
    assert!(!session_tabs::visible(&app), "one tab left: no bar");
}

#[test]
fn an_empty_tab_left_for_a_later_tab_keeps_the_right_one_active() {
    let client = Arc::new(Client::stub());
    let mut app = empty_app();
    app.session_tabs.list.push(second_tab());
    let third = "00000000-0000-4000-8000-000000000003";
    app.session_tabs
        .list
        .push(Tab::new(Some(third.into()), "Third".into()));
    assert!(chord(&mut app, &client, KeyCode::Char('3')));
    app.set_session_id(third.into());
    assert_eq!(app.session_tabs.list.len(), 2);
    assert_eq!(app.session_tabs.active, 1, "the third tab, now second");
    assert_eq!(app.session_tabs.list[1].session_id.as_deref(), Some(third));
}

#[test]
fn a_new_tab_from_an_empty_one_replaces_it() {
    let client = Arc::new(Client::stub());
    let mut app = empty_app();
    session_tabs::new_tab(&mut app, &client);
    app.set_session_id("00000000-0000-4000-8000-000000000007".into());
    assert_eq!(app.session_tabs.list.len(), 1);
    assert_eq!(app.session_tabs.active, 0);
}

#[test]
fn a_tab_with_a_turn_or_history_is_not_dropped() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    app.set_session_id(SECOND.into());
    assert_eq!(app.session_tabs.list.len(), 2, "history keeps the tab");

    let mut app = empty_app();
    app.session_tabs.list.push(second_tab());
    app.set_status(busy());
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    app.set_session_id(SECOND.into());
    assert_eq!(
        app.session_tabs.list.len(),
        2,
        "a running turn keeps the tab"
    );
}

#[test]
fn a_failed_switch_keeps_the_empty_tab() {
    let client = Arc::new(Client::stub());
    let mut app = empty_app();
    app.session_tabs.list.push(second_tab());
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    session_tabs::on_switch_failed(&mut app, false);
    assert_eq!(app.session_tabs.list.len(), 2);
    assert_eq!(app.session_tabs.active, 0);
    // A later switch that lands drops it once, not twice.
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    app.set_session_id(SECOND.into());
    assert_eq!(app.session_tabs.list.len(), 1);
}

#[test]
fn the_sessions_page_leaving_an_empty_tab_drops_it_too() {
    let mut app = empty_app();
    let previous = app.view.transcript.snapshot();
    app.sessions_page.switching = Some(Switching {
        id: SECOND.into(),
        previous,
        scroll: (0, 0),
        from_page: true,
    });
    app.set_session_id(SECOND.into());
    assert_eq!(app.session_tabs.list.len(), 1);
    assert_eq!(app.session_tabs.list[0].session_id.as_deref(), Some(SECOND));
}

#[test]
fn an_index_that_no_longer_exists_breaks_nothing() {
    let client = Arc::new(Client::stub());
    let mut app = empty_app();
    app.session_tabs.list.push(second_tab());
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    app.set_session_id(SECOND.into());
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    session_tabs::switch_to(&mut app, &client, 1);
    session_tabs::close(&mut app, &client, 5);
    session_tabs::step(&mut app, &client, 1);
    session_tabs::click(&mut app, &client, 40, crossterm::event::MouseButton::Left);
    assert!(!session_tabs::switching(&app));
    assert_eq!(app.session_tabs.list.len(), 1);
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

fn approval_for(callback_id: &str, session_id: &str) -> vibe_rs::server::ApprovalCallback {
    serde_json::from_value(json!({
        "callbackId": callback_id, "sessionId": session_id, "detail": {"kind": "approval"},
    }))
    .unwrap()
}

#[test]
fn a_switch_closes_the_approvals_of_the_session_left_and_keeps_the_new_ones() {
    let client = Arc::new(Client::stub());
    let mut app = two_tabs();
    app.set_status(busy());
    assert!(chord(&mut app, &client, KeyCode::Char('2')));
    // The old session asks while its switch is in flight.
    app.approval.enqueue(approval_for("old", FIRST)).unwrap();
    vibe_rs::approval::show_pending(&mut app);
    assert!(app.approval.open, "the old session's approval is up");
    app.approval.enqueue(approval_for("old-2", FIRST)).unwrap();
    // The server re-sends the new session's callbacks around the answer.
    app.approval.enqueue(approval_for("new", SECOND)).unwrap();
    app.set_session_id(SECOND.into());
    assert!(!app.approval.open && app.approval.active.is_none());
    assert_eq!(app.approval.pending_len(), 1, "only the new session's one");
}

#[tokio::test]
async fn the_client_opts_in_to_parking_a_running_session_on_a_switch() {
    let (client, mut frames) = Client::stub_answering();
    let _ = vibe_rs::startup::initialize_connection(&client).await;
    let frame = frames.recv().await.expect("the initialize request");
    assert_eq!(frame["method"], "initialize");
    let capabilities = &frame["params"]["capabilities"];
    assert_eq!(capabilities["parkRunningSession"], true, "ADR 0022");
    assert_eq!(capabilities["callbackKinds"][0], "approval");
}

#[test]
fn the_default_is_enabled() {
    assert!(SessionTabs::default().enabled);
}
