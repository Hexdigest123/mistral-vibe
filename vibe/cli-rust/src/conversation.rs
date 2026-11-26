//! Conversation mode: a hands-free voice session with a Mistral voice agent (Ctrl+X t).
// Fork feature (AGENTS.md "Fork features"): the app server hosts the session and its
// microphone; this renders its phase, runs the tasks the voice agent hands over through
// the ordinary prompt queue, and holds smart-approve for as long as it runs.

use std::sync::Arc;

use serde_json::{json, Value};

use crate::app::{App, Severity};
use crate::commands::submission::new_message_id;
use crate::commands::{spawn_session, CommandEvent};
use crate::server::request_error::describe;
use crate::server::{method, Client};
use crate::transcript::local;

/// The approval policy a conversation runs under: what it flags, the keyboard answers.
const POLICY: &str = "smart-approve";
/// Longest answer of the coding agent handed to the voice agent, in characters.
const MAX_REPORT_CHARS: usize = 1500;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Phase {
    #[default]
    Off,
    Connecting,
    Listening,
    Thinking,
    Speaking,
    Working,
}

impl Phase {
    pub fn label(self) -> &'static str {
        match self {
            Phase::Off => "",
            Phase::Connecting => "connecting",
            Phase::Listening => "listening",
            Phase::Thinking => "thinking",
            Phase::Speaking => "speaking",
            Phase::Working => "working",
        }
    }
}

#[derive(Default)]
pub struct State {
    /// The `conversation_mode_enabled` setting from `/voice`.
    pub enabled: bool,
    pub phase: Phase,
    /// The policy to go back to when the conversation ends, if it changed it.
    restore_policy: Option<String>,
    /// The task the voice agent waits on.
    task: Option<String>,
    approval_reported: bool,
}

/// A settled start or stop: the runtime after the policy switch, and the status or the failure.
pub struct Event {
    pub runtime: Option<Value>,
    pub outcome: Result<String, String>,
}

pub fn active(app: &App) -> bool {
    app.conversation.phase != Phase::Off
}

/// Ctrl+X t: start or end the conversation.
pub fn toggle(app: &mut App, client: &Arc<Client>) {
    match active(app) {
        true => stop(app, client),
        false => start(app, client),
    }
}

async fn switch_policy(
    client: &Client,
    session_id: &str,
    name: &str,
    opt_in: bool,
) -> Result<Value, String> {
    let params = json!({"sessionId": session_id, "approvalPolicy": name, "optIn": opt_in});
    let result = client
        .request(method::SESSION_APPROVAL_POLICY_UPDATE, params)
        .await;
    result.map_err(|error| describe(&error))
}

fn start(app: &mut App, client: &Arc<Client>) {
    if !app.conversation.enabled {
        let text = "Conversation mode is off: turn it on in /voice.";
        return crate::notices::inline(app, Severity::Warning, text);
    }
    let current = app.agents.active_policy.name.clone();
    let restore = (current != POLICY).then_some(current);
    let undo = restore.clone();
    let spawned = spawn_session(app, client, move |client, session_id| async move {
        let runtime = switch_policy(&client, &session_id, POLICY, true).await;
        let runtime = match runtime {
            Ok(runtime) => runtime,
            Err(error) => {
                return failed(None, format!("Conversation mode needs {POLICY}: {error}"))
            }
        };
        let params = json!({ "sessionId": session_id });
        let started = client.request(method::CONVERSATION_START, params).await;
        let error = match started {
            Ok(value) if value["ok"].as_bool() == Some(true) => None,
            Ok(value) => Some(
                value["error"]
                    .as_str()
                    .unwrap_or("it did not start")
                    .to_owned(),
            ),
            Err(error) => Some(describe(&error)),
        };
        match error {
            None => CommandEvent::Conversation(Box::new(Event {
                runtime: Some(runtime),
                outcome: Ok(String::new()),
            })),
            Some(error) => {
                // The policy goes back at once: no conversation is left to need it.
                let back = match undo {
                    Some(name) => switch_policy(&client, &session_id, &name, false).await.ok(),
                    None => None,
                };
                failed(back.or(Some(runtime)), error)
            }
        }
    });
    if spawned {
        app.conversation.phase = Phase::Connecting;
        app.conversation.restore_policy = restore;
    }
}

fn failed(runtime: Option<Value>, error: String) -> CommandEvent {
    CommandEvent::Conversation(Box::new(Event {
        runtime,
        outcome: Err(error),
    }))
}

/// End the conversation and put the approval policy back; the server closes its session.
fn stop(app: &mut App, client: &Arc<Client>) {
    let restore = end(app);
    spawn_session(app, client, move |client, session_id| async move {
        let params = json!({ "sessionId": session_id });
        let _ = client.request(method::CONVERSATION_STOP, params).await;
        let runtime = match restore {
            Some(name) => switch_policy(&client, &session_id, &name, false).await.ok(),
            None => None,
        };
        CommandEvent::Conversation(Box::new(Event {
            runtime,
            outcome: Ok("Conversation mode off.".to_owned()),
        }))
    });
}

/// Back to idle; the policy the conversation replaced, still to restore.
fn end(app: &mut App) -> Option<String> {
    app.conversation.phase = Phase::Off;
    app.conversation.task = None;
    app.conversation.approval_reported = false;
    app.conversation.restore_policy.take()
}

/// Apply a settled start or stop.
pub fn apply_event(app: &mut App, event: Event) {
    if let Some(runtime) = &event.runtime {
        crate::event_handler::apply_runtime_value(app, runtime);
    }
    let id = new_message_id();
    match event.outcome {
        Ok(text) if text.is_empty() => {}
        Ok(text) => local::add_command_status(&mut app.view.transcript, &id, &text),
        Err(error) => {
            end(app);
            local::add_command_error(&mut app.view.transcript, &id, &error);
        }
    }
}

/// `conversation/state`: the voice agent's phase; `stopped` ends the conversation, with its error.
pub fn on_state(app: &mut App, client: &Arc<Client>, params: &Value) {
    let phase = match params["state"].as_str() {
        Some("connecting") => Phase::Connecting,
        Some("listening") => Phase::Listening,
        Some("thinking") => Phase::Thinking,
        Some("speaking") => Phase::Speaking,
        Some("working") => Phase::Working,
        _ => return stopped(app, client, params["error"].as_str()),
    };
    if !active(app) {
        return;
    }
    // Rows follow the server's own order: the first listening state is what says it is on.
    if app.conversation.phase == Phase::Connecting && phase == Phase::Listening {
        let text = "Conversation mode on: just talk. Ctrl+X t ends it.";
        local::add_command_status(&mut app.view.transcript, &new_message_id(), text);
    }
    app.conversation.phase = phase;
}

fn stopped(app: &mut App, client: &Arc<Client>, error: Option<&str>) {
    if !active(app) {
        return;
    }
    if let Some(error) = error {
        let message = format!("Conversation mode stopped: {error}");
        crate::notices::failed(app, &message);
    }
    stop(app, client);
}

/// `conversation/transcript`: a finished spoken line, as a row in the conversation.
pub fn on_transcript(app: &mut App, params: &Value) {
    let (Some(role), Some(content)) = (params["role"].as_str(), params["content"].as_str()) else {
        return;
    };
    if params["final"].as_bool() == Some(false) || content.trim().is_empty() {
        return;
    }
    let who = if role == "user" { "You" } else { "Vibe" };
    let text = format!("🎙 {who}: {}", content.trim());
    local::add_command_status(&mut app.view.transcript, &new_message_id(), &text);
}

fn report(app: &App, client: &Arc<Client>, status: &'static str, text: String) {
    let (Some(session_id), Some(task_id)) = (
        app.session.session_id.clone(),
        app.conversation.task.clone(),
    ) else {
        return;
    };
    let client = client.clone();
    let params =
        json!({"sessionId": session_id, "taskId": task_id, "status": status, "text": text});
    crate::work::spawn(async move {
        let _ = client
            .request(method::CONVERSATION_TASK_RESULT, params)
            .await;
    });
}

/// `conversation/taskRequest`: run the voice agent's request as a prompt, or stop the running turn.
pub fn on_task_request(app: &mut App, client: &Arc<Client>, params: &Value) {
    if !active(app) {
        return;
    }
    match params["action"].as_str() {
        Some("run") => {
            let Some(task) = params["taskId"].as_str() else {
                return;
            };
            app.conversation.task = Some(task.to_owned());
            app.conversation.approval_reported = false;
            let prompt = params["prompt"].as_str().unwrap_or_default().to_owned();
            crate::message_queue::enqueue_prompt(app, client, prompt);
            crate::message_queue::resume(app, client);
        }
        Some("cancel") => crate::commands::submission::send_interrupt(app, client),
        _ => {}
    }
}

/// A turn ended: if the voice agent waits on it, hand it the answer.
pub fn on_turn_completed(app: &mut App, client: &Arc<Client>, status: Option<&str>) {
    if app.conversation.task.is_none() {
        return;
    }
    let (status, text) = match status {
        Some("failed") => ("failed", "The coding agent's turn failed.".to_owned()),
        Some("interrupted") => ("interrupted", "The turn was stopped.".to_owned()),
        _ => {
            let answer = app.view.transcript.last_assistant_message();
            let answer = answer.unwrap_or_else(|| "Done, with no message.".to_owned());
            ("done", answer.chars().take(MAX_REPORT_CHARS).collect())
        }
    };
    report(app, client, status, text);
    app.conversation.task = None;
}

/// An approval or question waits for the keyboard: say so once, so the voice agent can tell the user.
pub fn on_approval(app: &mut App, client: &Arc<Client>) {
    if app.conversation.task.is_some() && !app.conversation.approval_reported {
        app.conversation.approval_reported = true;
        report(app, client, "needs_approval", String::new());
    }
}

/// Follow the `conversation_mode_enabled` setting of a runtime snapshot.
pub fn apply_runtime(app: &mut App, runtime: &Value) {
    if let Some(config) = crate::server::RuntimeSnapshot::config(runtime) {
        app.conversation.enabled = config.conversation_mode_enabled;
    }
}

/// After the voice settings landed: turning the setting off ends a running conversation.
pub fn sync(app: &mut App, client: &Arc<Client>) {
    if !app.conversation.enabled && active(app) {
        stop(app, client);
    }
}
