//! `/config` field views decoded from the app-server response.

use std::collections::BTreeMap;

use serde::Deserialize;
use serde_json::Value;

pub use crate::config_sections::{section_label, section_rank, SECTION_ORDER};

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
    /// The readable name shown instead of the raw key (`name` stays the key).
    pub fn label(&self) -> String {
        crate::config_label::humanize(&self.name)
    }

    /// The text a search ranks: the raw key when it matches, else the label.
    pub fn searched(&self, query: &crate::utils::fzf::Query) -> String {
        if query.score(&self.name).is_some() {
            self.name.clone()
        } else {
            self.label()
        }
    }

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
