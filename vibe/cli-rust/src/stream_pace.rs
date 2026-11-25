//! Fork feature (AGENTS.md "Fork features"): TTFT and TPS in the bottom bar, measured like OpenCode's TUI.

use std::time::Duration;

use serde::Deserialize;
use serde_json::Value;

use crate::app::App;
use crate::clock::{self, UiInstant};
use crate::server::{EntryHead, MessageEntry, ReasoningEntry, SessionStats};

/// Chars per token for the live rate while streaming; OpenCode's TUI plugins estimate the same way.
const CHARS_PER_TOKEN: f64 = 4.0;

/// One reading: TTFT and the summed per-entry decode windows, from which TPS derives.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Pace {
    pub ttft: Option<Duration>,
    /// Sum of each streamed entry's first-to-last-token window, so tool time between entries is excluded.
    pub decode: Option<Duration>,
    /// Char-based estimate of the streamed output tokens.
    pub est_tokens: u64,
    /// Exact completion tokens from `session/statsUpdated`; 0 until reported.
    pub completion_tokens: u64,
}

impl Pace {
    /// `(output tokens) / (sum of per-entry decode windows)`, OpenCode's `tokensPerSecond`.
    pub fn tps(&self) -> Option<f64> {
        let secs = self.decode?.as_secs_f64();
        if secs <= 0.0 {
            return None;
        }
        let tokens = if self.completion_tokens > 0 {
            self.completion_tokens as f64
        } else {
            self.est_tokens as f64
        };
        (tokens > 0.0).then_some(tokens / secs)
    }
}

/// What the footer paints for a reading.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PaceView {
    pub ttft: Option<Duration>,
    pub tps: Option<f64>,
}

impl PaceView {
    fn from_pace(pace: Pace) -> Option<Self> {
        let view = Self {
            ttft: pace.ttft,
            tps: pace.tps(),
        };
        (view.ttft.is_some() || view.tps.is_some()).then_some(view)
    }
}

/// One streaming entry's decode window: first token, last token, streamed chars.
#[derive(Clone, Copy, Debug, Default)]
struct EntryStream {
    first_token_at: Option<UiInstant>,
    last_stream_at: Option<UiInstant>,
    chars: u64,
}

impl EntryStream {
    fn note_text(&mut self, now: UiInstant, chars: u64) {
        self.first_token_at.get_or_insert(now);
        self.last_stream_at = Some(now);
        self.chars += chars;
    }
}

/// The in-progress turn: turn start plus one stream per entry, in arrival order.
#[derive(Clone, Debug)]
struct Live {
    started_at: UiInstant,
    entries: Vec<(String, EntryStream)>,
}

impl Live {
    fn note_text(&mut self, id: &str, now: UiInstant, chars: u64) {
        if chars == 0 {
            return;
        }
        let index = match self.entries.iter().position(|(eid, _)| eid == id) {
            Some(index) => index,
            None => {
                self.entries.push((id.to_owned(), EntryStream::default()));
                self.entries.len() - 1
            }
        };
        self.entries[index].1.note_text(now, chars);
    }

    /// `now` extends only the latest entry's window; earlier entries end at their own last token.
    fn reading(&self, now: UiInstant, completion_tokens: u64) -> Pace {
        let ttft = self
            .entries
            .iter()
            .filter_map(|(_, entry)| entry.first_token_at)
            .min()
            .map(|at| at.duration_since(self.started_at));
        let last = self.entries.len().saturating_sub(1);
        let mut decode = Duration::ZERO;
        let mut chars = 0;
        for (index, (_, entry)) in self.entries.iter().enumerate() {
            let Some(first) = entry.first_token_at else {
                continue;
            };
            let end = if index == last {
                now
            } else {
                entry.last_stream_at.unwrap_or(first)
            };
            decode += end.duration_since(first);
            chars += entry.chars;
        }
        Pace {
            ttft,
            decode: (decode > Duration::ZERO).then_some(decode),
            est_tokens: (chars as f64 / CHARS_PER_TOKEN).round() as u64,
            completion_tokens,
        }
    }
}

/// The turn's live streams plus the last completed turn's reading, which stays shown when idle.
#[derive(Clone, Debug, Default)]
pub struct Tracker {
    live: Option<Live>,
    shown: Option<Pace>,
}

impl Tracker {
    pub fn start(&mut self, now: UiInstant) {
        self.live = Some(Live {
            started_at: now,
            entries: Vec::new(),
        });
    }

    pub fn note_text(&mut self, id: &str, now: UiInstant, chars: u64) {
        if let Some(live) = &mut self.live {
            live.note_text(id, now, chars);
        }
    }

    pub fn finish(&mut self, completion_tokens: u64) {
        if let Some(live) = self.live.take() {
            let end = live
                .entries
                .last()
                .and_then(|(_, entry)| entry.last_stream_at)
                .unwrap_or(live.started_at);
            self.shown = Some(live.reading(end, completion_tokens));
        }
    }

    pub fn note_completion(&mut self, tokens: u64) {
        if tokens > 0 {
            if let Some(shown) = &mut self.shown {
                shown.completion_tokens = tokens;
            }
        }
    }

    /// The live turn's reading while one streams, else the last finished turn's.
    pub fn view(&self, now: UiInstant) -> Option<PaceView> {
        let pace = match &self.live {
            Some(live) => live.reading(now, 0),
            None => self.shown?,
        };
        PaceView::from_pace(pace)
    }
}

/// The footer's TTFT/TPS segment, computed at paint time so a streaming rate ticks with the clock.
pub fn footer_pace(app: &App) -> Option<PaceView> {
    app.session.pace.view(clock::now())
}

/// `turn/started`: the request is dispatched, the TTFT clock starts (OpenCode's "message created").
pub fn on_turn_started(app: &mut App) {
    app.session.pace.start(clock::now());
}

/// `history/entryAdded`: a streaming assistant or reasoning entry's first text is its first token.
pub fn on_entry_added(app: &mut App, params: &Value, entry: &EntryHead) {
    if entry.generation_status.as_deref() != Some("in_progress") {
        return;
    }
    let Some(id) = entry.id.as_deref() else {
        return;
    };
    let chars = match entry.entry_type() {
        Some("reasoning") => params
            .get("entry")
            .and_then(|raw| ReasoningEntry::deserialize(raw).ok())
            .map_or(0, |entry| entry.text.chars().count() as u64),
        _ if entry.message_role() == Some("assistant") => params
            .get("entry")
            .and_then(|raw| MessageEntry::deserialize(raw).ok())
            .map_or(0, |entry| entry.text("\n\n").chars().count() as u64),
        _ => 0,
    };
    app.session.pace.note_text(id, clock::now(), chars);
}

/// `history/entryUpdated`: the patch's appended text is the entry's next streamed tokens.
pub fn on_entry_updated(app: &mut App, params: &Value) {
    let Some(id) = params.get("entryId").and_then(Value::as_str) else {
        return;
    };
    let transcript = &app.view.transcript;
    if !transcript.is_assistant_message(id) && !transcript.is_reasoning(id) {
        return;
    }
    let ops = params
        .get("patch")
        .and_then(Value::as_array)
        .map_or(&[][..], Vec::as_slice);
    app.session
        .pace
        .note_text(id, clock::now(), appended_chars(ops));
}

/// `turn/completed`: the live streams freeze into the shown reading.
pub fn on_turn_completed(app: &mut App) {
    let completion_tokens = app.session.stats.last_turn_completion_tokens;
    app.session.pace.finish(completion_tokens);
}

/// `session/statsUpdated`: the exact completion tokens replace the char estimate in the shown reading.
pub fn on_stats_updated(app: &mut App, stats: &SessionStats) {
    app.session
        .pace
        .note_completion(stats.last_turn_completion_tokens);
}

/// A new session starts with no reading.
pub fn reset(app: &mut App) {
    app.session.pace = Tracker::default();
}

/// Chars appended by this patch at `/text` (reasoning) or `/content/<n>/text` (message blocks).
fn appended_chars(ops: &[Value]) -> u64 {
    ops.iter()
        .filter(|op| op.get("op").and_then(Value::as_str) == Some("append"))
        .filter(|op| {
            op.get("path")
                .and_then(Value::as_str)
                .is_some_and(is_text_path)
        })
        .filter_map(|op| op.get("value").and_then(Value::as_str))
        .map(|text| text.chars().count() as u64)
        .sum()
}

fn is_text_path(path: &str) -> bool {
    if path == "/text" {
        return true;
    }
    let Some(rest) = path.strip_prefix("/content/") else {
        return false;
    };
    let Some((index, tail)) = rest.split_once('/') else {
        return false;
    };
    !index.is_empty() && index.bytes().all(|b| b.is_ascii_digit()) && tail == "text"
}
