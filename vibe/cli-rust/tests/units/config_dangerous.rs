//! Fork feature (AGENTS.md "Fork features"): a /config field flagged dangerous
//! on the wire decodes to a dangerous row and defaults to not dangerous.

use serde_json::json;
use vibe_rs::config_fields;

#[test]
fn the_dangerous_flag_decodes_and_defaults_off() {
    let loaded = config_fields::parse(&json!({
        "fields": [
            {
                "name": "disable_all_telemetry", "path": "/disable_all_telemetry",
                "kind": "bool", "value": true, "description": "DANGEROUS: ...",
                "popular": true, "dangerous": true,
            },
            {
                "name": "enable_telemetry", "path": "/enable_telemetry",
                "kind": "bool", "value": true, "description": "",
                "popular": true,
            },
        ],
    }));
    let by_name: std::collections::HashMap<&str, bool> = loaded
        .fields
        .iter()
        .map(|field| (field.name.as_str(), field.dangerous))
        .collect();
    assert_eq!(by_name.get("disable_all_telemetry"), Some(&true));
    assert_eq!(by_name.get("enable_telemetry"), Some(&false));
}
