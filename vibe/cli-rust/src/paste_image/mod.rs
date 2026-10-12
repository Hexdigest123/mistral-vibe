//! Clipboard-image ingestion and composer token insertion.

#[cfg(target_os = "linux")]
pub mod linux;
#[cfg(target_os = "macos")]
pub mod macos;

use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use tokio::sync::mpsc::Sender;

use crate::app::{App, Status, ToastSeverity};
use crate::{chat_input, paste_files, paste_path};

mod store;

pub use store::{clipboard_image_path, write_clipboard_image};

pub const PNG_MAGIC: &[u8] = b"\x89PNG\r\n\x1a\n";
pub const MAX_IMAGE_BYTES: usize = 10 * 1024 * 1024;
pub const CHANNEL_CAP: usize = 8;
const READ_TIMEOUT: Duration = Duration::from_secs(5);
const WARNING_SECS: u64 = 5;

#[derive(Default)]
pub struct State {
    pub tx: Option<Sender<Event>>,
    pub in_flight: usize,
}

impl State {
    pub fn has_slot(&self) -> bool {
        self.tx.is_some() && self.in_flight < CHANNEL_CAP
    }
}

pub enum Event {
    Empty {
        notify: bool,
    },
    TooLarge(usize),
    Failed,
    Pasted {
        path: PathBuf,
    },
    ImageFiles(Vec<PathBuf>),
    Probed {
        start: usize,
        raw: String,
        paths: Option<Vec<String>>,
    },
}

pub fn is_supported() -> bool {
    cfg!(any(target_os = "macos", target_os = "linux"))
}

pub fn is_paste_image_key(key: &KeyEvent, supported: bool) -> bool {
    supported && key.modifiers == KeyModifiers::CONTROL && key.code == KeyCode::Char('v')
}

pub fn request(app: &mut App, notify_when_empty: bool) {
    if is_supported() {
        paste_files::spawn_job(
            app,
            move || read_and_store(notify_when_empty),
            Event::Failed,
        );
    }
}

pub fn apply_event(app: &mut App, event: Event) {
    app.paste_image.in_flight = app.paste_image.in_flight.saturating_sub(1);
    match event {
        Event::Empty { notify: false } => {}
        Event::Empty { notify: true } => app.show_toast(
            "No image found on the clipboard.".to_owned(),
            ToastSeverity::Warning,
            3,
        ),
        Event::TooLarge(size) => app.show_toast(
            format!(
                "Clipboard image is {}; max is {}.",
                natural_size(size),
                natural_size(MAX_IMAGE_BYTES)
            ),
            ToastSeverity::Warning,
            WARNING_SECS,
        ),
        Event::Failed => app.show_toast(
            "Failed to save pasted image to disk.".to_owned(),
            ToastSeverity::Warning,
            WARNING_SECS,
        ),
        Event::Pasted { path } => paste_files::apply_image_files(app, vec![path]),
        Event::ImageFiles(paths) => paste_files::apply_image_files(app, paths),
        Event::Probed { start, raw, paths } => paste_files::apply_probed(app, start, &raw, paths),
    }
}

/// Warn and return true when the active model cannot take images.
pub(crate) fn rejects_images(app: &mut App) -> bool {
    if app.session.startup_config.images_supported || matches!(app.session.status, Status::Starting)
    {
        return false;
    }
    let name = &app.session.startup_config.active_model_display_name;
    app.show_toast(
        format!(
            "Model `{name}` does not support images. Switch with /model or ask me to enable image support for this model."
        ),
        ToastSeverity::Warning,
        WARNING_SECS,
    );
    true
}

// Finder copies also carry the file icon as an image, so file URLs win.
fn read_and_store(notify: bool) -> Event {
    let files = paste_files::read_clipboard_files();
    if !files.is_empty() {
        let images = paste_files::image_files(files);
        return match images.is_empty() {
            true => Event::Empty { notify },
            false => Event::ImageFiles(images),
        };
    }
    let Some(data) = read_clipboard_image() else {
        return Event::Empty { notify };
    };
    if data.len() > MAX_IMAGE_BYTES {
        return Event::TooLarge(data.len());
    }
    match write_clipboard_image(&data) {
        Ok(path) => Event::Pasted { path },
        Err(error) => {
            tracing::warn!(%error, "failed to write pasted clipboard image");
            Event::Failed
        }
    }
}

pub fn read_clipboard_image() -> Option<Vec<u8>> {
    #[cfg(target_os = "macos")]
    let data = macos::read();
    #[cfg(target_os = "linux")]
    let data = linux::read();
    #[cfg(not(any(target_os = "macos", target_os = "linux")))]
    let data = None;
    data.filter(|data| data.starts_with(PNG_MAGIC))
}

pub(crate) fn run_with_timeout(command: &mut Command, stdout: Stdio) -> bool {
    let Ok(mut child) = command.stdout(stdout).stderr(Stdio::null()).spawn() else {
        return false;
    };
    let deadline = Instant::now() + READ_TIMEOUT;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return status.success(),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(10)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return false;
            }
        }
    }
}

/// Insert an image token at the caret, spaced from its neighbours, and return its byte span.
pub fn insert_image_token(
    input: &mut String,
    cursor: &mut usize,
    anchor: &mut Option<usize>,
    token: &str,
) -> (usize, usize) {
    if let Some((lo, hi)) = chat_input::selection_range(input, *cursor, *anchor) {
        input.replace_range(lo..hi, "");
        *cursor = lo;
    }
    *anchor = None;
    let insertion = paste_path::with_image_mention_boundaries(input, *cursor, token);
    let start = *cursor + insertion.find(token).unwrap_or_default();
    crate::utils::input_edit::insert(input, cursor, &insertion);
    (start, start + token.len())
}

fn natural_size(bytes: usize) -> String {
    if bytes < 1024 {
        return format!("{bytes} Bytes");
    }
    let mut value = bytes as f64;
    let mut unit = "Bytes";
    for next in ["KiB", "MiB", "GiB"] {
        value /= 1024.0;
        unit = next;
        if value < 1024.0 {
            break;
        }
    }
    format!("{value:.1} {unit}")
}
