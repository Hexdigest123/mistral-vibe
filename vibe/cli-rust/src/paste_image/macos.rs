//! macOS clipboard-image readers (AppleScript pasteboard, sips conversion).

use std::fs;
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use tempfile::Builder;

use super::PNG_MAGIC;

const READ_TIMEOUT: Duration = Duration::from_secs(5);

pub fn read() -> Option<Vec<u8>> {
    // Preview's Copy, Screenshot, browser Copy Image, etc. each pick their own
    // image flavor on the pasteboard. Try PNG first, then TIFF via `sips`.
    if let Some(data) = read_macos_class("PNGf") {
        return Some(data);
    }
    let tiff = read_macos_class("TIFF")?;
    convert_to_png_via_sips(&tiff)
}

fn read_macos_class(four_cc: &str) -> Option<Vec<u8>> {
    let mut file = Builder::new().suffix(".bin").tempfile().ok()?;
    file.flush().ok()?;
    let path = applescript_string(file.path());
    let script = format!(
        "set targetFile to POSIX file \"{path}\"\ntry\n    set imgData to the clipboard as «class {four_cc}»\non error\n    return\nend try\nset fh to open for access targetFile with write permission\nset eof of fh to 0\nwrite imgData to fh\nclose access fh\n"
    );
    let mut command = Command::new("osascript");
    command.args(["-e", &script]);
    if !run_with_timeout(&mut command) {
        return None;
    }
    fs::read(file.path()).ok().filter(|data| !data.is_empty())
}

fn convert_to_png_via_sips(data: &[u8]) -> Option<Vec<u8>> {
    let mut source = Builder::new().suffix(".tiff").tempfile().ok()?;
    source.write_all(data).ok()?;
    source.flush().ok()?;
    let output = Builder::new().suffix(".png").tempfile().ok()?;
    let output_path = output.into_temp_path();
    fs::remove_file(&output_path).ok()?;
    let mut command = Command::new("sips");
    command.args([
        "-s",
        "format",
        "png",
        source.path().to_str()?,
        "--out",
        output_path.to_str()?,
    ]);
    if !run_with_timeout(&mut command) {
        return None;
    }
    fs::read(&output_path)
        .ok()
        .filter(|bytes| bytes.starts_with(PNG_MAGIC))
}

fn run_with_timeout(command: &mut Command) -> bool {
    let Ok(mut child) = command.stdout(Stdio::null()).stderr(Stdio::null()).spawn() else {
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

fn applescript_string(path: &Path) -> String {
    path.to_string_lossy()
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
}
