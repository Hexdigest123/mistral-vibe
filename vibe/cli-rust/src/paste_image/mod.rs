//! Clipboard-image ingestion and composer token insertion.

#[cfg(target_os = "linux")]
pub mod linux;
#[cfg(target_os = "macos")]
pub mod macos;

use std::io::{self, Write};
use std::path::{Path, PathBuf};

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use tempfile::Builder;
use tokio::sync::mpsc::Sender;

use crate::app::{App, Status, ToastSeverity};
use crate::{chat_input, completion_manager, paste_path};

pub const PNG_MAGIC: &[u8] = b"\x89PNG\r\n\x1a\n";
pub const MAX_IMAGE_BYTES: usize = 10 * 1024 * 1024;
pub const CHANNEL_CAP: usize = 8;
const WARNING_SECS: u64 = 5;

#[derive(Default)]
pub struct State {
    pub tx: Option<Sender<Event>>,
    pub in_flight: usize,
}

pub enum Event {
    Empty { notify: bool },
    TooLarge(usize),
    Failed,
    Pasted { path: PathBuf, size: usize },
}

pub fn is_supported() -> bool {
    cfg!(any(target_os = "macos", target_os = "linux"))
}

pub fn is_paste_image_key(key: &KeyEvent, supported: bool) -> bool {
    supported && key.modifiers == KeyModifiers::CONTROL && key.code == KeyCode::Char('v')
}

pub fn request(app: &mut App, notify_when_empty: bool) {
    if !is_supported() || app.paste_image.in_flight >= CHANNEL_CAP {
        return;
    }
    let Some(tx) = app.paste_image.tx.clone() else {
        return;
    };
    app.paste_image.in_flight += 1;
    let pending = app.commit_started();
    tokio::spawn(async move {
        let event = tokio::task::spawn_blocking(move || read_and_store(notify_when_empty))
            .await
            .unwrap_or(Event::Failed);
        crate::input::deliver(Some(tx), event, &pending).await;
    });
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
        Event::Pasted { path, size } => {
            if !app.session.startup_config.active_model_supports_images
                && !matches!(app.session.status, Status::Starting)
            {
                let name = &app.session.startup_config.active_model_display_name;
                app.show_toast(
                    format!(
                        "Model `{name}` does not support images. Switch with /model or ask me to enable image support for this model."
                    ),
                    ToastSeverity::Warning,
                    WARNING_SECS,
                );
                return;
            }
            crate::input::reset_history_state(app);
            insert_image_token(
                &mut app.chat_input.input,
                &mut app.chat_input.cursor,
                &mut app.chat_input.anchor,
                &path,
            );
            app.chat_input.scroll = None;
            completion_manager::input_changed(app);
            let name = path
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("image.png");
            app.show_toast(
                format!("Image pasted as {name} ({})", natural_size(size)),
                ToastSeverity::Information,
                2,
            );
        }
    }
}

fn read_and_store(notify: bool) -> Event {
    let Some(data) = read_clipboard_image() else {
        return Event::Empty { notify };
    };
    if data.len() > MAX_IMAGE_BYTES {
        return Event::TooLarge(data.len());
    }
    match write_clipboard_image(&data) {
        Ok(path) => Event::Pasted {
            path,
            size: data.len(),
        },
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

pub fn write_clipboard_image(data: &[u8]) -> io::Result<PathBuf> {
    let mut file = Builder::new()
        .prefix("vibe-clipboard-")
        .suffix(".png")
        .tempfile()?;
    file.write_all(data)?;
    file.flush()?;
    let (_file, path) = file.keep().map_err(|error| error.error)?;
    Ok(path)
}

pub fn insert_image_token(
    input: &mut String,
    cursor: &mut usize,
    anchor: &mut Option<usize>,
    path: &Path,
) {
    if let Some((lo, hi)) = chat_input::selection_range(input, *cursor, *anchor) {
        input.replace_range(lo..hi, "");
        *cursor = lo;
    }
    *anchor = None;
    let token = paste_path::image_path_mention(&path.to_string_lossy());
    let insertion = paste_path::with_image_mention_boundaries(input, *cursor, &token);
    crate::utils::input_edit::insert(input, cursor, &insertion);
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
