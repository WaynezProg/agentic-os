use std::path::{Path, PathBuf};
use std::process::Command;

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

pub fn run_script(script: &str, command: &str) -> Result<String, String> {
    let root = repo_root();
    let script_path = root.join("scripts").join(script);
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

pub fn start_stack() {
    let _ = run_script("desktop-ui.sh", "start");
    let _ = run_script("desktop-daemon.sh", "start");
}

pub fn stop_stack() {
    let _ = run_script("desktop-ui.sh", "stop");
    let _ = run_script("desktop-daemon.sh", "stop");
}
