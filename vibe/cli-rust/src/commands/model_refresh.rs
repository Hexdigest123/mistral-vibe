//! Fork feature (AGENTS.md): `/model refresh` asks every `discover = true` provider for its models again.

use std::sync::Arc;

use serde_json::Value;

use super::event::{dispatch, CommandEvent};
use crate::app::App;
use crate::server::{method, Client};

/// The `/model` argument that refreshes instead of opening the picker.
pub const REFRESH: &str = "refresh";

pub const NO_PROVIDER: &str =
    "No provider has `discover = true` in config.toml, so there is nothing to refresh.";

/// Send `models/refresh`; the `runtime/updated` it triggers brings the models to `/model`.
pub fn refresh(app: &mut App, client: &Arc<Client>) {
    let Some((session_id, tx)) = dispatch(app) else {
        return;
    };
    app.begin_command_loading();
    let client = client.clone();
    tokio::spawn(async move {
        let params = serde_json::json!({ "sessionId": session_id });
        let event = match client.request(method::MODELS_REFRESH, params).await {
            Ok(value) => summary(&value),
            Err(error) => CommandEvent::Error(format!(
                "Failed to refresh models: {}",
                crate::server::request_error::describe(&error)
            )),
        };
        let _ = tx.try_send(event);
    });
}

/// One line per answer: each provider's model count, then what failed.
pub fn summary(value: &Value) -> CommandEvent {
    let list = |key: &str| value.get(key).and_then(Value::as_array).cloned();
    let entries = list("entries").unwrap_or_default();
    let errors: Vec<String> = list("errors")
        .unwrap_or_default()
        .iter()
        .filter_map(|error| error.as_str().map(str::to_owned))
        .collect();
    if entries.is_empty() && errors.is_empty() {
        return CommandEvent::Status(NO_PROVIDER.to_owned());
    }
    let counts: Vec<String> = entries
        .iter()
        .map(|entry| {
            let name = entry.get("providerName").and_then(Value::as_str);
            let count = entry
                .get("modelIds")
                .and_then(Value::as_array)
                .map_or(0, Vec::len);
            format!("{} {count}", name.unwrap_or("?"))
        })
        .collect();
    let counts = counts.join(", ");
    match errors.is_empty() {
        true => CommandEvent::Status(format!("Models refreshed: {counts}")),
        false => CommandEvent::Error(format!(
            "Could not refresh {}; models listed: {counts}",
            errors.join("; ")
        )),
    }
}
