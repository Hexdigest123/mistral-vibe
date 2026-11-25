//! Readable `/config` setting names derived from the raw snake_case keys.

/// Words that keep their own casing wherever they appear.
const ACRONYMS: &[(&str, &str)] = &[
    ("api", "API"),
    ("cli", "CLI"),
    ("id", "ID"),
    ("json", "JSON"),
    ("llm", "LLM"),
    ("mcp", "MCP"),
    ("otel", "OTel"),
    ("pr", "PR"),
    ("toml", "TOML"),
    ("tts", "TTS"),
    ("ui", "UI"),
    ("url", "URL"),
    ("yaml", "YAML"),
];

/// `max_concurrent_subagents` -> `Max concurrent subagents`;
/// `experimental_enable_x` -> `X (experimental)`.
pub fn humanize(name: &str) -> String {
    let mut words: Vec<&str> = name.split('_').filter(|word| !word.is_empty()).collect();
    let experimental = words.first() == Some(&"experimental") && words.len() > 1;
    if experimental {
        words.remove(0);
        if words.first() == Some(&"enable") && words.len() > 1 {
            words.remove(0);
        }
    }
    let mut label = String::new();
    for (index, word) in words.iter().enumerate() {
        if index > 0 {
            label.push(' ');
        }
        match ACRONYMS.iter().find(|(key, _)| key == word) {
            Some((_, text)) => label.push_str(text),
            None if index == 0 => label.push_str(&capitalize(word)),
            None => label.push_str(word),
        }
    }
    if experimental {
        label.push_str(" (experimental)");
    }
    if label.is_empty() {
        name.to_owned()
    } else {
        label
    }
}

fn capitalize(word: &str) -> String {
    let mut chars = word.chars();
    chars
        .next()
        .map(|first| first.to_uppercase().chain(chars).collect())
        .unwrap_or_default()
}
