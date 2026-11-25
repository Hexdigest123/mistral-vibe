//! `/config` field views decoded from the app-server response.

use std::collections::BTreeMap;

use serde::Deserialize;
use serde_json::Value;

#[derive(Clone)]
pub struct ConfigField {
    pub name: String,
    pub popular: bool,
    /// The settings-screen section key the server filed the field under. An
    /// older server sends none; the `popular` flag then decides the section.
    pub category: String,
    pub path: String,
    pub raw_value: Value,
    pub kind: String,
    pub writable: bool,
    pub overridden: bool,
    pub enum_choices: Vec<String>,
    pub description: String,
    pub value_labels: BTreeMap<String, String>,
    pub layers: Vec<(String, Value)>,
    /// Fork feature (AGENTS.md "Fork features"): a dangerous setting (e.g. the
    /// telemetry kill switch) is flagged red and warns when switched on.
    pub dangerous: bool,
}

impl ConfigField {
    /// The effective value as shown to the user, preferring its human label.
    pub fn display_value(&self) -> String {
        self.labeled(&self.raw_value)
    }

    /// One layer's value as shown to the user, preferring its human label.
    pub fn labeled(&self, value: &Value) -> String {
        value
            .as_str()
            .and_then(|text| self.value_labels.get(text))
            .cloned()
            .unwrap_or_else(|| format_value(value))
    }
}

#[derive(Default)]
pub struct Loaded {
    pub fields: Vec<ConfigField>,
    pub targets: Vec<String>,
    /// Why the read failed; the fields on screen then stay.
    pub error: Option<String>,
}

/// App-server `ConfigFieldsReadResponse`.
#[derive(Deserialize)]
struct WireResponse {
    #[serde(deserialize_with = "crate::utils::json::lenient")]
    fields: Vec<WireField>,
    #[serde(default, deserialize_with = "crate::utils::json::lenient")]
    targets: Vec<String>,
}

/// App-server `ConfigFieldWire`.
#[derive(Default, Deserialize)]
#[serde(default, rename_all = "camelCase")]
struct WireField {
    name: String,
    kind: String,
    description: String,
    value: Value,
    path: String,
    popular: bool,
    category: String,
    enum_choices: Vec<String>,
    value_labels: BTreeMap<String, String>,
    #[serde(deserialize_with = "crate::utils::json::lenient")]
    layer_values: Vec<WireLayer>,
    dangerous: bool,
}

#[derive(Deserialize)]
struct WireLayer {
    layer: String,
    #[serde(default)]
    value: Value,
}

pub fn parse(result: &Value) -> Loaded {
    let Ok(response) = WireResponse::deserialize(result) else {
        return Loaded {
            error: Some("unexpected config/fields/read response".into()),
            ..Loaded::default()
        };
    };
    Loaded {
        fields: response.fields.into_iter().map(field).collect(),
        targets: response.targets,
        error: None,
    }
}

fn field(wire: WireField) -> ConfigField {
    let layers: Vec<_> = wire
        .layer_values
        .into_iter()
        .map(|item| (item.layer, item.value))
        .collect();
    ConfigField {
        writable: layers.first().is_none_or(|(layer, _)| layer != "admin"),
        overridden: layers.iter().any(|(layer, _)| layer != "default"),
        name: wire.name,
        popular: wire.popular,
        category: resolve_category(&wire.category, wire.popular),
        path: wire.path,
        raw_value: wire.value,
        kind: wire.kind,
        enum_choices: wire.enum_choices,
        description: wire.description,
        value_labels: wire.value_labels,
        layers,
        dangerous: wire.dangerous,
    }
}

/// An older server sends no category; fall back to the `popular` flag.
fn resolve_category(category: &str, popular: bool) -> String {
    if category.is_empty() {
        if popular {
            "popular".to_owned()
        } else {
            "advanced".to_owned()
        }
    } else {
        category.to_owned()
    }
}

/// The settings-screen sections in display order. The client owns the labels
/// and this order; a newer server's unknown key sorts after the known ones,
/// ahead of "advanced" (ADR 0014).
pub const SECTION_ORDER: &[&str] = &[
    "popular",
    "fork",
    "models",
    "voice",
    "tts",
    "tools",
    "agents",
    "appearance",
    "safety",
    "worktrees",
];

/// Where a section sits in the list: known keys by `SECTION_ORDER`, unknown
/// keys after them, "advanced" last.
pub fn section_rank(category: &str) -> usize {
    if category == "advanced" {
        usize::MAX
    } else {
        SECTION_ORDER
            .iter()
            .position(|key| *key == category)
            .unwrap_or(SECTION_ORDER.len())
    }
}

/// The heading drawn over a section.
pub fn section_label(category: &str) -> String {
    match category {
        "popular" => "Popular settings".to_owned(),
        "fork" => "Fork features".to_owned(),
        "models" => "Models".to_owned(),
        "voice" => "Voice".to_owned(),
        "tts" => "TTS".to_owned(),
        "tools" => "Tools".to_owned(),
        "agents" => "Agents".to_owned(),
        "appearance" => "Appearance".to_owned(),
        "safety" => "Safety".to_owned(),
        "worktrees" => "Worktrees".to_owned(),
        "advanced" => "Advanced settings".to_owned(),
        other => other.to_owned(),
    }
}

pub fn format_value(value: &Value) -> String {
    match value {
        Value::Bool(value) => if *value { "True" } else { "False" }.to_owned(),
        Value::String(value) if value.is_empty() => "\"\"".to_owned(),
        Value::String(value) => value.clone(),
        Value::Array(values) => format!(
            "[{} item{}]",
            values.len(),
            if values.len() == 1 { "" } else { "s" }
        ),
        Value::Object(values) => format!(
            "{{{} entr{}}}",
            values.len(),
            if values.len() == 1 { "y" } else { "ies" }
        ),
        Value::Null => "—".to_owned(),
        Value::Number(value) => value.to_string(),
    }
}
