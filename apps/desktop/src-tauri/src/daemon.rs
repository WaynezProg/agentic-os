use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::OnceLock;

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
    let output = Command::new("bash")
        .arg(script_path)
        .arg(command)
        .current_dir(working_dir)
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

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
}
