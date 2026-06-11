use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::OnceLock;

use serde::Deserialize;
use tauri::{AppHandle, Manager};

static BUNDLE_ROOT: OnceLock<Option<PathBuf>> = OnceLock::new();

pub fn repo_root() -> PathBuf {
    if let Ok(root) = std::env::var("AGENTIC_OS_ROOT") {
        return PathBuf::from(root);
    }
    let mut dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    loop {
        if dir.join("pyproject.toml").exists() {
            return dir;
        }
        if !dir.pop() {
            break;
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

pub fn bundle_root(app: &AppHandle) -> Option<PathBuf> {
    let root = app.path().resource_dir().ok()?.join("agentic-os");
    if root.join("scripts").join("desktop-daemon.sh").exists() {
        Some(root)
    } else {
        None
    }
}

pub fn init_bundle_root(app: &AppHandle) {
    let resolved = if cfg!(debug_assertions) {
        None
    } else {
        bundle_root(app)
    };
    let _ = BUNDLE_ROOT.set(resolved.clone());
    if let Some(root) = resolved {
        std::env::set_var("AGENTIC_OS_BUNDLE_ROOT", root);
    }
}

pub fn runtime_root() -> PathBuf {
    if let Ok(root) = std::env::var("AGENTIC_OS_BUNDLE_ROOT") {
        if !root.is_empty() {
            return PathBuf::from(root);
        }
    }
    if let Some(Some(root)) = BUNDLE_ROOT.get() {
        return root.clone();
    }
    if cfg!(debug_assertions) {
        repo_root()
    } else {
        repo_root()
    }
}

fn script_path(script: &str) -> PathBuf {
    runtime_root().join("scripts").join(script)
}

pub fn run_script(script: &str, command: &str) -> Result<String, String> {
    let root = runtime_root();
    let script_path = script_path(script);
    run_script_at(&script_path, &root, command)
}

fn run_script_at(script_path: &Path, working_dir: &Path, command: &str) -> Result<String, String> {
    let output = Command::new("/bin/bash")
        .arg(script_path)
        .arg(command)
        .current_dir(working_dir)
        .env("PATH", hardened_path())
        .output()
        .map_err(|error| error.to_string())?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stdout = String::from_utf8_lossy(&output.stdout);
        return Err(format!("{stderr}{stdout}").trim().to_string());
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

pub fn reconcile_stack() {
    let _ = run_script("desktop-ui.sh", "reconcile");
    let _ = run_script("desktop-daemon.sh", "reconcile");
}

pub fn start_stack() {
    let _ = run_script("desktop-ui.sh", "start");
    let _ = run_script("desktop-daemon.sh", "start");
}

pub fn stop_stack() {
    let _ = run_script("desktop-ui.sh", "stop");
    let _ = run_script("desktop-daemon.sh", "stop");
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct DaemonStatus {
    #[serde(default)]
    pub running: bool,
    #[serde(default)]
    pub managed: bool,
    #[serde(default)]
    pub pid: Option<u32>,
    #[serde(default)]
    pub api_url: String,
    #[serde(default)]
    pub health: String,
}

impl DaemonStatus {
    pub fn is_healthy(&self) -> bool {
        self.health == "ok"
    }
}

pub fn parse_status(json: &str) -> Result<DaemonStatus, String> {
    serde_json::from_str(json).map_err(|error| error.to_string())
}

pub fn status() -> Result<DaemonStatus, String> {
    let raw = run_script("desktop-daemon.sh", "status")?;
    parse_status(&raw)
}

pub fn start_daemon() -> Result<String, String> {
    run_script("desktop-daemon.sh", "start")
}

/// PID of the process holding `port` in LISTEN state, best-effort.
pub fn listener_pid(port: u16) -> Option<u32> {
    let output = Command::new("/usr/sbin/lsof")
        .args(["-nP", &format!("-iTCP:{port}"), "-sTCP:LISTEN", "-t"])
        .output()
        .ok()?;
    String::from_utf8_lossy(&output.stdout)
        .split_whitespace()
        .next()?
        .parse()
        .ok()
}

fn state_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("AGENTIC_OS_STATE_DIR") {
        if !dir.is_empty() {
            return PathBuf::from(dir);
        }
    }
    let bundle = std::env::var("AGENTIC_OS_BUNDLE_ROOT")
        .map(|value| !value.is_empty())
        .unwrap_or(false);
    if bundle {
        if let Some(home) = dirs::home_dir() {
            return home.join(".agentic-os");
        }
    }
    repo_root().join(".agentic-os")
}

/// Mirrors `desktop-common.sh`'s `desktop_runtime_dir`/daemon log location.
pub fn daemon_log_path() -> PathBuf {
    state_dir().join("desktop").join("daemon.log")
}

fn ensure_path_dirs(current: &str, extra_front: &[PathBuf]) -> String {
    // GUI launches (Finder/Dock) inherit the launchd PATH, which lacks
    // Homebrew dirs — without them `uv` is unresolvable and the
    // dev-mode daemon start fails before the supervisor can help.
    let required = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ];
    let mut parts: Vec<String> = Vec::new();
    for path in extra_front {
        let value = path.to_string_lossy().to_string();
        if !value.is_empty() && !parts.iter().any(|existing| existing == &value) {
            parts.push(value);
        }
    }
    for segment in current.split(':').filter(|segment| !segment.is_empty()) {
        if !parts.iter().any(|existing| existing == segment) {
            parts.push(segment.to_string());
        }
    }
    for req in required {
        if !parts.iter().any(|existing| existing == req) {
            parts.push(req.to_string());
        }
    }
    parts.join(":")
}

pub fn hardened_path() -> String {
    let current = std::env::var("PATH").unwrap_or_default();
    let mut extra_front = Vec::new();
    if let Ok(root) = std::env::var("AGENTIC_OS_BUNDLE_ROOT") {
        if !root.is_empty() {
            extra_front.push(PathBuf::from(&root).join("runtime").join(".venv").join("bin"));
        }
    }
    ensure_path_dirs(&current, &extra_front)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn ensure_path_includes_homebrew_dirs() {
        let result = ensure_path_dirs("/usr/bin:/bin", &[]);
        assert!(result.contains("/opt/homebrew/bin"));
        assert!(result.contains("/usr/local/bin"));
        assert!(result.contains("/usr/sbin"));
    }

    #[test]
    fn runtime_root_prefers_bundle_env() {
        let temp = std::env::temp_dir().join(format!(
            "agentic-os-runtime-root-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&temp);
        fs::create_dir_all(&temp).unwrap();
        std::env::set_var("AGENTIC_OS_BUNDLE_ROOT", &temp);
        assert_eq!(runtime_root(), temp);
        std::env::remove_var("AGENTIC_OS_BUNDLE_ROOT");
        let _ = fs::remove_dir_all(&temp);
    }

    #[test]
    fn script_path_joins_under_runtime_root() {
        let temp = std::env::temp_dir().join(format!(
            "agentic-os-script-path-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&temp);
        fs::create_dir_all(temp.join("scripts")).unwrap();
        std::env::set_var("AGENTIC_OS_BUNDLE_ROOT", &temp);
        assert_eq!(
            script_path("desktop-daemon.sh"),
            temp.join("scripts").join("desktop-daemon.sh")
        );
        std::env::remove_var("AGENTIC_OS_BUNDLE_ROOT");
        let _ = fs::remove_dir_all(&temp);
    }

    #[test]
    fn parse_status_reads_health_and_pid() {
        let status = parse_status(
            r#"{"running": true, "managed": true, "pid": 4242, "api_url": "http://127.0.0.1:8767", "health": "ok"}"#,
        )
        .unwrap();
        assert!(status.running);
        assert_eq!(status.pid, Some(4242));
        assert_eq!(status.api_url, "http://127.0.0.1:8767");
        assert!(status.is_healthy());
    }

    #[test]
    fn parse_status_handles_down_and_null_pid() {
        let status =
            parse_status(r#"{"running": false, "managed": false, "pid": null, "health": "down"}"#)
                .unwrap();
        assert_eq!(status.pid, None);
        assert!(!status.is_healthy());
    }

    #[test]
    fn ensure_path_dirs_appends_required_and_dedups() {
        let out = ensure_path_dirs("/opt/homebrew/bin:/usr/bin", &[]);
        assert!(out.starts_with("/opt/homebrew/bin:/usr/bin"));
        for req in ["/usr/bin", "/bin", "/usr/sbin", "/sbin"] {
            assert!(out.split(':').any(|s| s == req), "missing {req}");
        }
        assert_eq!(out.split(':').filter(|s| *s == "/usr/bin").count(), 1);
    }

    #[test]
    fn ensure_path_dirs_prepends_extra_front() {
        let out = ensure_path_dirs(
            "/usr/bin",
            &[std::path::PathBuf::from("/bundle/runtime/.venv/bin")],
        );
        assert!(out.starts_with("/bundle/runtime/.venv/bin:"));
    }
}
