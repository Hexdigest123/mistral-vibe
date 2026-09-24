//! Linux clipboard-image readers: Wayland `wl-paste`, X11 `xclip`.

use std::env;
use std::io::Read;
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

const READ_TIMEOUT: Duration = Duration::from_secs(5);

pub fn read() -> Option<Vec<u8>> {
    read_wayland().or_else(read_x11)
}

fn read_wayland() -> Option<Vec<u8>> {
    // wl-paste exits nonzero when the clipboard does not offer the mime type.
    env::var_os("WAYLAND_DISPLAY")?;
    let mut command = Command::new("wl-paste");
    command.args(["-t", "image/png"]);
    capture_with_timeout(&mut command)
}

fn read_x11() -> Option<Vec<u8>> {
    env::var_os("DISPLAY")?;
    let mut command = Command::new("xclip");
    command.args(["-selection", "clipboard", "-t", "image/png", "-o"]);
    capture_with_timeout(&mut command)
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
