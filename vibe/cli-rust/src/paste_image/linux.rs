//! Linux clipboard reads (fork feature, AGENTS.md): `wl-paste` (Wayland) or `xclip` (X11), else
//! the native clipboard; any image type the session takes, and file-manager copies.

use std::env;
use std::io::Read;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

const READ_TIMEOUT: Duration = Duration::from_secs(5);

/// The clipboard image types the session takes, best first.
pub const IMAGE_TYPES: &[&str] = &[
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
];
/// How file managers offer copied files.
pub const URI_LIST: &str = "text/uri-list";

#[derive(Clone, Copy)]
enum Tool {
    WlPaste,
    Xclip,
}

impl Tool {
    /// The tools the session's displays allow: Wayland's first, then X11's (XWayland too).
    fn reachable() -> impl Iterator<Item = Tool> {
        let wayland = env::var_os("WAYLAND_DISPLAY").map(|_| Tool::WlPaste);
        let x11 = env::var_os("DISPLAY").map(|_| Tool::Xclip);
        wayland.into_iter().chain(x11)
    }

    /// The types on offer; `None` when the tool is missing or nothing is copied.
    fn types(self) -> Option<Vec<String>> {
        let mut command = match self {
            Tool::WlPaste => Self::command("wl-paste", &["--list-types"]),
            Tool::Xclip => self.reader("TARGETS"),
        };
        let listed = capture_with_timeout(&mut command)?;
        Some(
            String::from_utf8_lossy(&listed)
                .lines()
                .map(|t| t.trim().to_owned())
                .collect(),
        )
    }

    fn read(self, mime: &str) -> Option<Vec<u8>> {
        capture_with_timeout(&mut self.reader(mime))
    }

    fn reader(self, mime: &str) -> Command {
        match self {
            Tool::WlPaste => Self::command("wl-paste", &["-t", mime]),
            Tool::Xclip => Self::command("xclip", &["-selection", "clipboard", "-t", mime, "-o"]),
        }
    }

    fn command(program: &str, args: &[&str]) -> Command {
        let mut command = Command::new(program);
        command.args(args);
        command
    }
}

/// The first reachable tool and what it lists.
fn offered() -> Option<(Tool, Vec<String>)> {
    Tool::reachable().find_map(|tool| tool.types().map(|types| (tool, types)))
}

/// Whether any display is set; without one there is no clipboard to read natively.
fn has_display() -> bool {
    Tool::reachable().next().is_some()
}

/// The clipboard image, in the best type it offers, else from the native clipboard as PNG.
pub fn read() -> Option<Vec<u8>> {
    match offered() {
        Some((tool, types)) => tool.read(best_image_type(&types)?),
        None if has_display() => native_image(),
        None => None,
    }
}

/// The files a file manager copied, else the native clipboard's.
pub fn read_files() -> Vec<PathBuf> {
    match offered() {
        Some((tool, types)) if types.iter().any(|t| t == URI_LIST) => tool
            .read(URI_LIST)
            .map(|list| parse_uri_list(&String::from_utf8_lossy(&list)))
            .unwrap_or_default(),
        Some(_) => Vec::new(),
        None if has_display() => arboard::Clipboard::new()
            .and_then(|mut clipboard| clipboard.get().file_list())
            .unwrap_or_default(),
        None => Vec::new(),
    }
}

/// The first of `IMAGE_TYPES` among the offered `types`.
pub fn best_image_type(types: &[String]) -> Option<&'static str> {
    IMAGE_TYPES.iter().copied().find(|wanted| {
        types
            .iter()
            .any(|offered| offered.eq_ignore_ascii_case(wanted))
    })
}

/// The local files of a `text/uri-list`; comments and other schemes are skipped.
pub fn parse_uri_list(list: &str) -> Vec<PathBuf> {
    list.lines()
        .map(str::trim)
        .filter(|line| !line.is_empty() && !line.starts_with('#'))
        .filter_map(|line| url::Url::parse(line).ok())
        .filter(|url| url.scheme() == "file")
        .filter_map(|url| url.to_file_path().ok())
        .collect()
}

fn native_image() -> Option<Vec<u8>> {
    let image = arboard::Clipboard::new().ok()?.get_image().ok()?;
    encode_png(image.width, image.height, &image.bytes)
}

/// RGBA8 pixels as a PNG file.
pub fn encode_png(width: usize, height: usize, rgba: &[u8]) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    let (width, height) = (u32::try_from(width).ok()?, u32::try_from(height).ok()?);
    let mut encoder = png::Encoder::new(&mut out, width, height);
    encoder.set_color(png::ColorType::Rgba);
    encoder.set_depth(png::BitDepth::Eight);
    let mut writer = encoder.write_header().ok()?;
    writer.write_image_data(rgba).ok()?;
    writer.finish().ok()?;
    Some(out)
}

/// Runs a clipboard tool and captures stdout, bounded by a timeout.
/// A reader thread drains the pipe so images larger than the pipe buffer
/// cannot block the tool against the try_wait loop.
pub fn capture_with_timeout(command: &mut Command) -> Option<Vec<u8>> {
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    let mut stdout = child.stdout.take()?;
    let reader = thread::spawn(move || {
        let mut data = Vec::new();
        stdout.read_to_end(&mut data).ok()?;
        Some(data)
    });
    let deadline = Instant::now() + READ_TIMEOUT;
    loop {
        match child.try_wait() {
            Ok(Some(status)) if status.success() => {
                return reader.join().ok().flatten().filter(|data| !data.is_empty());
            }
            Ok(Some(_)) => return None,
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(10)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    }
}
