//! Conversation mode client: Ctrl+X t, the voice agent's phases, its tasks and their results.

use crossterm::event::KeyCode;
use serde_json::json;
use vibe_rs::app::App;
use vibe_rs::conversation::{self, Event, Phase};

use crate::support::{ctrl, press, send_key, stub};

fn ready(enabled: bool) -> App {
    let mut app = App::default();
    app.set_status(vibe_rs::app::Status::Ready);
    app.set_session_id("00000000-0000-4000-8000-000000000001".into());
    app.conversation.enabled = enabled;
    app
}

fn last_row(app: &App) -> String {
    let row = app.view.transcript.last_shown_row().cloned();
    let text = row
        .as_ref()
        .and_then(|row| row["content"][0]["text"].as_str());
    text.unwrap_or_default().to_owned()
}

fn chord_t(app: &mut App) {
    send_key(app, ctrl('x'));
    press(app, KeyCode::Char('t'));
}

#[test]
fn ctrl_x_t_while_the_setting_is_off_points_to_voice_settings() {
    let mut app = ready(false);
    chord_t(&mut app);
    assert_eq!(app.conversation.phase, Phase::Off);
    assert!(!conversation::active(&app));
}

#[tokio::test]
async fn ctrl_x_t_starts_connecting_and_a_second_press_ends_it() {
    let mut app = ready(true);
    chord_t(&mut app);
    assert_eq!(app.conversation.phase, Phase::Connecting);
    chord_t(&mut app);
    assert_eq!(app.conversation.phase, Phase::Off);
}

#[test]
fn ctrl_x_t_without_a_session_does_not_start() {
    let mut app = App::default();
    app.conversation.enabled = true;
    chord_t(&mut app);
    assert_eq!(app.conversation.phase, Phase::Off);
}

#[tokio::test]
async fn the_server_state_drives_the_phase() {
    let mut app = ready(true);
    chord_t(&mut app);
    for (state, phase) in [
        ("listening", Phase::Listening),
        ("thinking", Phase::Thinking),
        ("speaking", Phase::Speaking),
        ("working", Phase::Working),
    ] {
        conversation::on_state(&mut app, &stub(), &json!({"state": state}));
        assert_eq!(app.conversation.phase, phase);
    }
}

#[tokio::test]
async fn a_stopped_state_ends_the_conversation() {
    let mut app = ready(true);
    chord_t(&mut app);
    conversation::on_state(&mut app, &stub(), &json!({"state": "stopped"}));
    assert_eq!(app.conversation.phase, Phase::Off);
}

#[test]
fn a_late_state_after_the_end_does_not_revive_it() {
    let mut app = ready(true);
    conversation::on_state(&mut app, &stub(), &json!({"state": "listening"}));
    assert_eq!(app.conversation.phase, Phase::Off);
}

#[tokio::test]
async fn a_failed_start_ends_it_and_says_why() {
    let mut app = ready(true);
    chord_t(&mut app);
    let outcome = Err("Conversation mode needs a build with the voice-agents feature".into());
    conversation::apply_event(
        &mut app,
        Event {
            runtime: None,
            outcome,
        },
    );
    assert_eq!(app.conversation.phase, Phase::Off);
    assert!(last_row(&app).contains("voice-agents"));
}

#[tokio::test]
async fn the_first_listening_state_says_how_to_end_it() {
    let mut app = ready(true);
    chord_t(&mut app);
    conversation::apply_event(
        &mut app,
        Event {
            runtime: None,
            outcome: Ok(String::new()),
        },
    );
    assert_eq!(last_row(&app), "", "a settled start adds no row of its own");
    conversation::on_state(&mut app, &stub(), &json!({"state": "listening"}));
    assert!(last_row(&app).contains("Ctrl+X t"));
}

#[test]
fn spoken_lines_become_rows_and_partial_ones_do_not() {
    let mut app = ready(true);
    let line = |role: &str, content: &str, last: bool| json!({"role": role, "content": content, "final": last});
    conversation::on_transcript(&mut app, &line("user", "run the tests", true));
    assert_eq!(last_row(&app), "🎙 You: run the tests");
    conversation::on_transcript(&mut app, &line("assistant", "Running them now.", true));
    assert_eq!(last_row(&app), "🎙 Vibe: Running them now.");
    conversation::on_transcript(&mut app, &line("user", "and then", false));
    assert_eq!(last_row(&app), "🎙 Vibe: Running them now.");
}

#[tokio::test]
async fn a_task_request_queues_the_prompt_and_a_finished_turn_clears_the_task() {
    let mut app = ready(true);
    chord_t(&mut app);
    let request = json!({"action": "run", "taskId": "t1", "prompt": "run the tests"});
    conversation::on_task_request(&mut app, &stub(), &request);
    conversation::on_turn_completed(&mut app, &stub(), Some("completed"));
    // A second completion has no task left to report.
    conversation::on_turn_completed(&mut app, &stub(), Some("failed"));
    assert_eq!(app.conversation.phase, Phase::Connecting);
}

#[test]
fn a_task_request_outside_a_conversation_is_ignored() {
    let mut app = ready(true);
    let request = json!({"action": "run", "taskId": "t1", "prompt": "run the tests"});
    conversation::on_task_request(&mut app, &stub(), &request);
    assert!(app.queue.is_empty());
}

#[test]
fn the_voice_settings_list_a_conversation_toggle() {
    assert_eq!(vibe_rs::voice_app::LABELS.len(), 3);
    assert!(vibe_rs::voice_app::LABELS[2].starts_with("Conversation mode"));
}

#[tokio::test]
async fn the_notifications_route_through_the_event_handler() {
    use vibe_rs::server::Notification;
    let mut app = ready(true);
    chord_t(&mut app);
    let state = Notification {
        method: "conversation/state".into(),
        params: json!({"sessionId": "00000000-0000-4000-8000-000000000001", "state": "listening"}),
    };
    vibe_rs::event_handler::apply_notification(&mut app, &stub(), &state);
    assert_eq!(app.conversation.phase, Phase::Listening);
}
