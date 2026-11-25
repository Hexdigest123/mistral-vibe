//! The footer's TTFT/TPS segment: a turn's stream tracking and the forms it paints.

use std::time::Duration;

use vibe_rs::clock;
use vibe_rs::stream_pace::{PaceView, Tracker};
use vibe_rs::ui::footer_fit::{self, Inputs};
use vibe_rs::ui::footer_gauge::{pace_forms, Usage};

fn ms(millis: u64) -> Duration {
    Duration::from_millis(millis)
}

#[test]
fn ttft_runs_from_turn_start_to_the_first_streamed_text() {
    let t0 = clock::now();
    let mut tracker = Tracker::default();
    tracker.start(t0);
    assert_eq!(
        tracker.view(t0 + ms(500)),
        None,
        "no token yet, nothing to show"
    );
    tracker.note_text("a", t0 + ms(800), 48);
    let view = tracker
        .view(t0 + ms(2000))
        .expect("a reading once text streamed");
    assert_eq!(view.ttft, Some(ms(800)));
    // 48 chars estimate 12 tokens over the 1.2s since the first token.
    assert_eq!(view.tps, Some(10.0));
}

#[test]
fn the_live_rate_uses_the_char_estimate_until_completion_tokens_arrive() {
    let t0 = clock::now();
    let mut tracker = Tracker::default();
    tracker.start(t0);
    tracker.note_text("a", t0 + ms(800), 48);
    tracker.note_text("a", t0 + ms(2000), 48);
    let view = tracker.view(t0 + ms(2000)).expect("live");
    // 96 chars estimate 24 tokens over 1.2s of decoding.
    assert_eq!(view.tps, Some(20.0));
    tracker.finish(0);
    let view = tracker.view(t0 + ms(9000)).expect("shown after the turn");
    assert_eq!(view.ttft, Some(ms(800)));
    assert_eq!(
        view.tps,
        Some(20.0),
        "the decode window ends at the last token, not at turn end"
    );
}

#[test]
fn the_decode_window_sums_per_entry_windows_and_skips_the_gap_between_them() {
    let t0 = clock::now();
    let mut tracker = Tracker::default();
    tracker.start(t0);
    tracker.note_text("a", t0 + ms(800), 48);
    tracker.note_text("a", t0 + ms(2000), 48);
    // A second entry streams after a 6s tool gap; the gap is not provider-active time.
    tracker.note_text("b", t0 + ms(8000), 48);
    tracker.note_text("b", t0 + ms(9200), 48);
    let view = tracker.view(t0 + ms(9200)).expect("live");
    assert_eq!(view.ttft, Some(ms(800)));
    // 192 chars estimate 48 tokens over the two 1.2s entry windows (2.4s), not the 8.4s span.
    assert_eq!(view.tps, Some(20.0));
    tracker.finish(96);
    let view = tracker.view(t0 + ms(20000)).expect("shown after the turn");
    assert_eq!(
        view.tps,
        Some(40.0),
        "96 exact tokens over the same 2.4s of summed entry windows"
    );
}

#[test]
fn exact_completion_tokens_replace_the_estimate_in_the_shown_reading() {
    let t0 = clock::now();
    let mut tracker = Tracker::default();
    tracker.start(t0);
    tracker.note_text("a", t0 + ms(500), 40);
    tracker.note_text("a", t0 + ms(2500), 40);
    tracker.finish(0);
    tracker.note_completion(80);
    let view = tracker.view(t0 + ms(9000)).expect("shown");
    assert_eq!(
        view.tps,
        Some(40.0),
        "80 tokens over the 2.0s decode window"
    );
    tracker.note_completion(0);
    let view = tracker.view(t0 + ms(9000)).expect("shown");
    assert_eq!(
        view.tps,
        Some(40.0),
        "a zero reading keeps the last exact count"
    );
}

#[test]
fn a_turn_without_streamed_text_shows_nothing() {
    let t0 = clock::now();
    let mut tracker = Tracker::default();
    tracker.start(t0);
    tracker.finish(120);
    assert_eq!(tracker.view(t0 + ms(9000)), None);
}

#[test]
fn pace_forms_paint_ttft_and_tps_then_shrink_to_tps() {
    let pace = Some(PaceView {
        ttft: Some(ms(800)),
        tps: Some(42.0),
    });
    let forms = pace_forms(pace);
    assert_eq!(
        forms[0],
        vec![("0.8s ttft · 42.0 tok/s".to_owned(), footer_fit::Tone::Muted)]
    );
    assert_eq!(
        forms[1],
        vec![("42.0 tok/s".to_owned(), footer_fit::Tone::Muted)]
    );
    assert!(pace_forms(None).is_empty());
    assert!(pace_forms(Some(PaceView {
        ttft: None,
        tps: None
    }))
    .is_empty());
    let ttft_only = pace_forms(Some(PaceView {
        ttft: Some(ms(120)),
        tps: None,
    }));
    assert_eq!(ttft_only.len(), 1);
    assert_eq!(
        ttft_only[0],
        vec![("0.1s ttft".to_owned(), footer_fit::Tone::Muted)]
    );
}

#[test]
fn the_pace_segment_paints_after_the_gauges_and_hides_last() {
    let inputs = |width: usize, pace: Option<PaceView>| Inputs {
        width,
        cwd: "/tmp/project",
        copy_icon: false,
        quit: None,
        tokens: (23_000, 600_000),
        usage: Some(Usage {
            percent: 40.0,
            payg: false,
        }),
        pace,
    };
    let pace = Some(PaceView {
        ttft: Some(ms(800)),
        tps: Some(42.0),
    });
    let fitted = footer_fit::fit(inputs(120, pace));
    let text = |form: &footer_fit::Form| {
        form.iter()
            .map(|(text, _)| text.as_str())
            .collect::<String>()
    };
    assert_eq!(text(&fitted.pace), "0.8s ttft · 42.0 tok/s");
    assert!(text(&fitted.usage).contains("40%"));
    // Narrow enough that the pace segment must give way before the gauges do.
    let narrow = footer_fit::fit(inputs(46, pace));
    assert_eq!(text(&narrow.pace), "42.0 tok/s");
    let narrower = footer_fit::fit(inputs(37, pace));
    assert!(
        narrower.pace.is_empty(),
        "the pace segment hides first: {:?}",
        text(&narrower.pace)
    );
    assert!(!narrower.usage.is_empty(), "gauges never hide");
}
