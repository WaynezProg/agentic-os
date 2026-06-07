# Desktop App Auto-Connect Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the desktop app keep a healthy local daemon reachable — at launch and continuously — auto-restarting it with bounded backoff, surfacing a failed state, and showing an honest connecting overlay; plus harden the spawn PATH so a packaged `.app` launched from Finder works.

**Architecture:** A dedicated OS thread in the Tauri app (the "supervisor") probes daemon health every 5s, runs a pure-function state machine to decide restart/backoff/fail, restarts the child daemon via the existing lifecycle script, and emits `connection-state` events. The webview owns only a connecting/failed overlay driven by those events (Tauri) or `/health` polling (plain web). PATH hardening is applied at the Rust spawn point so child scripts resolve `bash`/`python3`/`lsof`/the bundled `agentd` without the user's shell PATH.

**Tech Stack:** Rust (Tauri 2.11, `serde`, `dirs`, std threads + `tauri::Emitter`), vanilla JS webview, bash lifecycle scripts. Spec: `docs/superpowers/specs/2026-06-08-desktop-auto-connect-supervisor-design.md`.

---

## File Structure

- `apps/desktop/src-tauri/src/daemon.rs` (modify) — typed status parse, `status()`, `start_daemon()`, `restart()`, `listener_pid()`, `daemon_log_path()`, `hardened_path()`/`ensure_path_dirs()`, PATH-hardened `run_script_at`.
- `apps/desktop/src-tauri/src/supervisor.rs` (new) — pure state machine (`Health`, `Phase`, `Action`, `SupervisorState`, `next_action`, `after_attempt`, `backoff_secs`), `ConnectionStatePayload`, `SHUTDOWN`, `run_supervisor` thread.
- `apps/desktop/src-tauri/src/lib.rs` (modify) — declare `mod supervisor`, `SupervisorHandle` managed state, spawn supervisor thread (replacing the tokio title-only loop), register `retry_daemon` + `open_daemon_log` commands, make `refresh_tray_title` `pub(crate)`, reset supervisor on tray "Start daemon", set `SHUTDOWN` on quit/exit.
- `apps/desktop/src-tauri/capabilities/default.json` (modify) — add `core:event:default`.
- Web UI, kept in **two synced copies**:
  - `apps/web/ui/connection-gate.js` (new), `apps/web/index.html` (modify), `apps/web/styles.css` (modify), `apps/web/app.js` (modify)
  - `apps/desktop/src-tauri/bundle-resources/agentic-os/web/ui/connection-gate.js` (new) + the same three files under that `web/` dir.

**Note (deviation from spec §4):** No per-script interpreter edits. PATH hardening at the Rust spawn point (Task 2/3) guarantees `/usr/bin`, `/bin`, `/usr/sbin`, `/sbin` are on the child PATH, which is what the scripts' `python3`/`lsof`/`bash` need — so editing each script's heredocs would be redundant churn. The bundled `agentd` is already an absolute path with no `rtk`/`uv` dependency. This achieves the spec's Finder-launch goal with fewer touched files.

All work continues on branch `feat/desktop-auto-connect-supervisor` (the spec is already committed there).

---

### Task 1: `daemon.rs` — typed status parse

**Files:**
- Modify: `apps/desktop/src-tauri/src/daemon.rs`
- Test: same file, `#[cfg(test)] mod tests`

- [ ] **Step 1: Add the failing test**

Append inside the existing `mod tests` in `apps/desktop/src-tauri/src/daemon.rs`:

```rust
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
```

- [ ] **Step 2: Run the test, expect failure**

Run: `cd apps/desktop/src-tauri && cargo test --lib parse_status`
Expected: FAIL — `cannot find function parse_status` / `DaemonStatus` not found.

- [ ] **Step 3: Implement `DaemonStatus` + `parse_status`**

At the top of `apps/desktop/src-tauri/src/daemon.rs`, add `serde::Deserialize` to imports:

```rust
use serde::Deserialize;
```

Then add (above the `#[cfg(test)]` block):

```rust
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
```

- [ ] **Step 4: Run the test, expect pass**

Run: `cd apps/desktop/src-tauri && cargo test --lib parse_status`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/src-tauri/src/daemon.rs
git commit -m "feat(desktop): typed daemon status parse"
```

---

### Task 2: `daemon.rs` — PATH hardening helper

**Files:**
- Modify: `apps/desktop/src-tauri/src/daemon.rs`
- Test: same file

- [ ] **Step 1: Add the failing test**

Append inside `mod tests`:

```rust
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
```

- [ ] **Step 2: Run the test, expect failure**

Run: `cd apps/desktop/src-tauri && cargo test --lib ensure_path_dirs`
Expected: FAIL — `cannot find function ensure_path_dirs`.

- [ ] **Step 3: Implement `ensure_path_dirs` + `hardened_path`**

Add to `apps/desktop/src-tauri/src/daemon.rs` (above the test block):

```rust
fn ensure_path_dirs(current: &str, extra_front: &[PathBuf]) -> String {
    let required = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"];
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
```

- [ ] **Step 4: Run the test, expect pass**

Run: `cd apps/desktop/src-tauri && cargo test --lib ensure_path_dirs`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/src-tauri/src/daemon.rs
git commit -m "feat(desktop): PATH hardening helper for child scripts"
```

---

### Task 3: `daemon.rs` — status/start/restart/listener/log helpers + harden `run_script_at`

**Files:**
- Modify: `apps/desktop/src-tauri/src/daemon.rs`

These are I/O helpers (no unit test; verified by `cargo build` and the manual e2e in Task 11).

- [ ] **Step 1: Harden `run_script_at`**

In `apps/desktop/src-tauri/src/daemon.rs`, replace the body of `run_script_at` so it uses an absolute bash and a hardened PATH:

```rust
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
```

- [ ] **Step 2: Add the daemon-control helpers**

Add these public functions to `apps/desktop/src-tauri/src/daemon.rs` (near `start_stack`):

```rust
pub fn status() -> Result<DaemonStatus, String> {
    let raw = run_script("desktop-daemon.sh", "status")?;
    parse_status(&raw)
}

pub fn start_daemon() -> Result<String, String> {
    run_script("desktop-daemon.sh", "start")
}

pub fn restart_daemon() -> Result<String, String> {
    run_script("desktop-daemon.sh", "restart")
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
```

- [ ] **Step 3: Build to verify it compiles**

Run: `cd apps/desktop/src-tauri && cargo build`
Expected: build succeeds (warnings about unused `restart_daemon`/`listener_pid`/`daemon_log_path` are fine — they are used in later tasks).

- [ ] **Step 4: Commit**

```bash
git add apps/desktop/src-tauri/src/daemon.rs
git commit -m "feat(desktop): daemon control + log-path helpers, hardened spawn"
```

---

### Task 4: `supervisor.rs` — pure state machine

**Files:**
- Create: `apps/desktop/src-tauri/src/supervisor.rs`

- [ ] **Step 1: Create the file with types + the failing tests**

Create `apps/desktop/src-tauri/src/supervisor.rs`:

```rust
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter};

use crate::daemon;
use crate::settings;

pub const MAX_RESTART_ATTEMPTS: u32 = 5;
pub const BACKOFF_SECS: [u64; 5] = [0, 5, 15, 30, 60];
pub const TICK: Duration = Duration::from_secs(5);
pub const CONNECTION_EVENT: &str = "connection-state";

pub static SHUTDOWN: AtomicBool = AtomicBool::new(false);

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Health {
    Ok,
    Down,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Phase {
    Connecting,
    Connected,
    Restarting,
    Failed,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Action {
    None,
    Attempt,
    MarkFailed,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SupervisorState {
    pub phase: Phase,
    pub fail_count: u32,
    pub next_attempt_secs: Option<u64>,
}

impl SupervisorState {
    pub fn reset() -> Self {
        Self {
            phase: Phase::Connecting,
            fail_count: 0,
            next_attempt_secs: None,
        }
    }
}

pub fn phase_str(phase: Phase) -> &'static str {
    match phase {
        Phase::Connecting => "connecting",
        Phase::Connected => "connected",
        Phase::Restarting => "restarting",
        Phase::Failed => "failed",
    }
}

pub fn backoff_secs(fail_count: u32) -> u64 {
    let idx = (fail_count as usize).min(BACKOFF_SECS.len() - 1);
    BACKOFF_SECS[idx]
}

pub fn next_action(
    health: Health,
    fail_count: u32,
    now_secs: u64,
    next_attempt_secs: Option<u64>,
) -> Action {
    if health == Health::Ok {
        return Action::None;
    }
    if fail_count >= MAX_RESTART_ATTEMPTS {
        return Action::MarkFailed;
    }
    match next_attempt_secs {
        Some(deadline) if now_secs < deadline => Action::None,
        _ => Action::Attempt,
    }
}

pub fn after_attempt(prev: &SupervisorState, succeeded: bool, now_secs: u64) -> SupervisorState {
    if succeeded {
        return SupervisorState {
            phase: Phase::Connected,
            fail_count: 0,
            next_attempt_secs: None,
        };
    }
    let fail_count = prev.fail_count + 1;
    if fail_count >= MAX_RESTART_ATTEMPTS {
        SupervisorState {
            phase: Phase::Failed,
            fail_count,
            next_attempt_secs: None,
        }
    } else {
        SupervisorState {
            phase: Phase::Restarting,
            fail_count,
            next_attempt_secs: Some(now_secs + backoff_secs(fail_count)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn healthy_means_no_action() {
        assert_eq!(next_action(Health::Ok, 0, 100, None), Action::None);
    }

    #[test]
    fn down_attempts_when_no_cooldown() {
        assert_eq!(next_action(Health::Down, 0, 100, None), Action::Attempt);
    }

    #[test]
    fn down_waits_during_cooldown() {
        assert_eq!(next_action(Health::Down, 1, 100, Some(105)), Action::None);
        assert_eq!(next_action(Health::Down, 1, 105, Some(105)), Action::Attempt);
    }

    #[test]
    fn marks_failed_at_ceiling() {
        assert_eq!(
            next_action(Health::Down, MAX_RESTART_ATTEMPTS, 100, None),
            Action::MarkFailed
        );
    }

    #[test]
    fn backoff_progression_and_cap() {
        assert_eq!(backoff_secs(0), 0);
        assert_eq!(backoff_secs(1), 5);
        assert_eq!(backoff_secs(2), 15);
        assert_eq!(backoff_secs(3), 30);
        assert_eq!(backoff_secs(4), 60);
        assert_eq!(backoff_secs(99), 60);
    }

    #[test]
    fn after_success_resets() {
        let prev = SupervisorState {
            phase: Phase::Restarting,
            fail_count: 3,
            next_attempt_secs: Some(50),
        };
        let next = after_attempt(&prev, true, 100);
        assert_eq!(next.phase, Phase::Connected);
        assert_eq!(next.fail_count, 0);
        assert_eq!(next.next_attempt_secs, None);
    }

    #[test]
    fn after_failure_backs_off_then_fails() {
        let mut state = SupervisorState::reset();
        for expected in [Phase::Restarting; 4] {
            state = after_attempt(&state, false, 0);
            assert_eq!(state.phase, expected);
        }
        // 5th failure crosses the ceiling.
        state = after_attempt(&state, false, 0);
        assert_eq!(state.phase, Phase::Failed);
        assert_eq!(state.fail_count, MAX_RESTART_ATTEMPTS);
        assert_eq!(state.next_attempt_secs, None);
    }
}
```

(`Arc`, `Mutex`, `Instant`, `AppHandle`, `Emitter`, `Manager`, `daemon`, `settings`, `Serialize` are imported now and used by `run_supervisor` in Task 5; if `cargo test` warns about them being unused at this step, that is expected and resolved in Task 5.)

- [ ] **Step 2: Register the module so tests compile**

In `apps/desktop/src-tauri/src/lib.rs`, add to the module declarations near the top:

```rust
mod supervisor;
```

- [ ] **Step 3: Run the tests, expect pass**

Run: `cd apps/desktop/src-tauri && cargo test --lib supervisor::`
Expected: PASS (7 tests). Unused-import warnings are acceptable here.

- [ ] **Step 4: Commit**

```bash
git add apps/desktop/src-tauri/src/supervisor.rs apps/desktop/src-tauri/src/lib.rs
git commit -m "feat(desktop): supervisor connection state machine"
```

---

### Task 5: `supervisor.rs` — event payload + supervisor thread

**Files:**
- Modify: `apps/desktop/src-tauri/src/supervisor.rs`

I/O + threading; verified by `cargo build` and Task 11.

- [ ] **Step 1: Add the payload type and the thread runner**

Insert into `apps/desktop/src-tauri/src/supervisor.rs` (above the `#[cfg(test)]` block):

```rust
#[derive(Serialize, Clone)]
pub struct ConnectionStatePayload {
    pub state: String,
    pub detail: String,
    pub api_url: String,
    pub pid: Option<u32>,
}

/// Owns the supervisor handle managed in Tauri state (manual retry resets it).
pub struct SupervisorHandle(pub Arc<Mutex<SupervisorState>>);

fn emit(app: &AppHandle, last: &mut Option<String>, payload: ConnectionStatePayload) {
    let key = format!("{}|{}", payload.state, payload.detail);
    if last.as_deref() != Some(key.as_str()) {
        let _ = app.emit(CONNECTION_EVENT, payload);
        *last = Some(key);
    }
}

pub fn run_supervisor(app: AppHandle, shared: Arc<Mutex<SupervisorState>>) {
    let start = Instant::now();
    let mut last_emitted: Option<String> = None;

    loop {
        if SHUTDOWN.load(std::sync::atomic::Ordering::SeqCst) {
            return;
        }

        // Remote mode is out of scope for supervision — only keep the tray title fresh.
        let mode = settings::load_settings()
            .map(|settings| settings.connection.mode)
            .unwrap_or_else(|_| "local".to_string());
        if mode == "remote" {
            crate::refresh_tray_title(&app);
            std::thread::sleep(TICK);
            continue;
        }

        let now_secs = start.elapsed().as_secs();
        let status = daemon::status().ok();
        let healthy = status.as_ref().map(|s| s.is_healthy()).unwrap_or(false);
        let api_url = status.as_ref().map(|s| s.api_url.clone()).unwrap_or_default();
        let pid = status.as_ref().and_then(|s| s.pid);
        let health = if healthy { Health::Ok } else { Health::Down };

        let (action, snapshot) = {
            let state = shared.lock().expect("supervisor state poisoned");
            (
                next_action(health, state.fail_count, now_secs, state.next_attempt_secs),
                state.clone(),
            )
        };

        let payload = match action {
            Action::None if healthy => {
                let mut state = shared.lock().unwrap();
                *state = SupervisorState {
                    phase: Phase::Connected,
                    fail_count: 0,
                    next_attempt_secs: None,
                };
                ConnectionStatePayload {
                    state: "connected".to_string(),
                    detail: "ok".to_string(),
                    api_url: api_url.clone(),
                    pid,
                }
            }
            Action::None => ConnectionStatePayload {
                state: phase_str(snapshot.phase).to_string(),
                detail: "waiting".to_string(),
                api_url: api_url.clone(),
                pid: None,
            },
            Action::MarkFailed => {
                let mut state = shared.lock().unwrap();
                state.phase = Phase::Failed;
                ConnectionStatePayload {
                    state: "failed".to_string(),
                    detail: "daemon failed to start".to_string(),
                    api_url: api_url.clone(),
                    pid: None,
                }
            }
            Action::Attempt => {
                emit(
                    &app,
                    &mut last_emitted,
                    ConnectionStatePayload {
                        state: "restarting".to_string(),
                        detail: "starting daemon".to_string(),
                        api_url: api_url.clone(),
                        pid: None,
                    },
                );
                let started = daemon::start_daemon().is_ok();
                let ok = started
                    && daemon::status().map(|s| s.is_healthy()).unwrap_or(false);
                let next = after_attempt(&snapshot, ok, now_secs);
                {
                    let mut state = shared.lock().unwrap();
                    *state = next.clone();
                }
                let detail = if ok {
                    "ok".to_string()
                } else if let Some(pid) = daemon::listener_pid(8767) {
                    format!("port_occupied:{pid}")
                } else {
                    "retry scheduled".to_string()
                };
                ConnectionStatePayload {
                    state: phase_str(next.phase).to_string(),
                    detail,
                    api_url: api_url.clone(),
                    pid: None,
                }
            }
        };

        emit(&app, &mut last_emitted, payload);
        crate::refresh_tray_title(&app);
        std::thread::sleep(TICK);
    }
}
```

- [ ] **Step 2: Build to verify it compiles**

Run: `cd apps/desktop/src-tauri && cargo build`
Expected: FAIL until Task 6 makes `crate::refresh_tray_title` `pub(crate)`. If it fails only on `refresh_tray_title` visibility, proceed to Task 6 and rebuild there. Any other error must be fixed before continuing.

- [ ] **Step 3: Commit**

```bash
git add apps/desktop/src-tauri/src/supervisor.rs
git commit -m "feat(desktop): supervisor thread emits connection-state events"
```

---

### Task 6: `lib.rs` — wire supervisor, commands, lifecycle

**Files:**
- Modify: `apps/desktop/src-tauri/src/lib.rs`

- [ ] **Step 1: Imports and visibility**

In `apps/desktop/src-tauri/src/lib.rs`, add near the top imports:

```rust
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};

use supervisor::{SupervisorHandle, SupervisorState};
```

Change the signature of `refresh_tray_title` from:

```rust
fn refresh_tray_title(app: &AppHandle) {
```

to:

```rust
pub(crate) fn refresh_tray_title(app: &AppHandle) {
```

- [ ] **Step 2: Add the two new commands**

Add to `apps/desktop/src-tauri/src/lib.rs` (next to the other `#[tauri::command]` fns):

```rust
#[tauri::command]
fn retry_daemon(state: tauri::State<SupervisorHandle>) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|error| error.to_string())?;
    *guard = SupervisorState::reset();
    Ok(())
}

#[tauri::command]
fn open_daemon_log() -> Result<(), String> {
    let path = daemon::daemon_log_path();
    std::process::Command::new("/usr/bin/open")
        .arg(path)
        .spawn()
        .map(|_| ())
        .map_err(|error| error.to_string())
}
```

- [ ] **Step 3: Register the commands**

In the `tauri::generate_handler![...]` list, add `retry_daemon,` and `open_daemon_log,` (e.g. after `probe_remote_connection,`).

- [ ] **Step 4: Spawn the supervisor, remove the tokio title loop**

In the `.setup(|app| { ... })` block, the current code has:

```rust
            daemon::init_bundle_root(app.handle());
            daemon::reconcile_stack();
            daemon::start_stack();
```

Leave those. Then **delete** this existing block:

```rust
            let poll_handle = handle.clone();
            tauri::async_runtime::spawn(async move {
                loop {
                    refresh_tray_title(&poll_handle);
                    tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                }
            });
```

and **replace** it with:

```rust
            let shared = Arc::new(Mutex::new(SupervisorState::reset()));
            app.manage(SupervisorHandle(shared.clone()));
            let supervisor_handle = handle.clone();
            std::thread::spawn(move || supervisor::run_supervisor(supervisor_handle, shared));
```

(The `refresh_tray_title(app.handle());` call that follows stays as the initial paint.)

- [ ] **Step 5: Reset supervisor on tray "Start daemon"**

In the tray `on_menu_event` closure, replace the `"daemon_start"` arm:

```rust
                    "daemon_start" => {
                        let _ = daemon_start();
                        refresh_tray_title(app);
                    }
```

with:

```rust
                    "daemon_start" => {
                        let _ = daemon_start();
                        if let Some(handle) = app.try_state::<SupervisorHandle>() {
                            if let Ok(mut guard) = handle.0.lock() {
                                *guard = SupervisorState::reset();
                            }
                        }
                        refresh_tray_title(app);
                    }
```

- [ ] **Step 6: Set SHUTDOWN on quit and exit**

In the same `on_menu_event` closure, replace the `"quit"` arm:

```rust
                    "quit" => {
                        daemon::stop_stack();
                        app.exit(0);
                    }
```

with:

```rust
                    "quit" => {
                        supervisor::SHUTDOWN.store(true, Ordering::SeqCst);
                        daemon::stop_stack();
                        app.exit(0);
                    }
```

And at the bottom, replace the run handler:

```rust
    app.run(|_app_handle, event| {
        if let RunEvent::Exit = event {
            daemon::stop_stack();
        }
    });
```

with:

```rust
    app.run(|_app_handle, event| {
        if let RunEvent::Exit = event {
            supervisor::SHUTDOWN.store(true, Ordering::SeqCst);
            daemon::stop_stack();
        }
    });
```

- [ ] **Step 7: Build + run the full crate test suite**

Run: `cd apps/desktop/src-tauri && cargo build && cargo test --lib`
Expected: build succeeds; all `daemon::` and `supervisor::` unit tests PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/desktop/src-tauri/src/lib.rs
git commit -m "feat(desktop): run supervisor thread + retry/open-log commands"
```

---

### Task 7: capabilities — allow webview event listening

**Files:**
- Modify: `apps/desktop/src-tauri/capabilities/default.json`

- [ ] **Step 1: Add the event permission**

Edit `apps/desktop/src-tauri/capabilities/default.json` so `permissions` reads:

```json
  "permissions": [
    "core:default",
    "core:event:default"
  ]
```

- [ ] **Step 2: Build to verify the capability schema accepts it**

Run: `cd apps/desktop/src-tauri && cargo build`
Expected: build succeeds (no capability-validation error).

- [ ] **Step 3: Commit**

```bash
git add apps/desktop/src-tauri/capabilities/default.json
git commit -m "feat(desktop): allow webview to listen for connection-state events"
```

---

### Task 8: webview — connection gate module (`apps/web`)

**Files:**
- Create: `apps/web/ui/connection-gate.js`

- [ ] **Step 1: Create the gate module**

Create `apps/web/ui/connection-gate.js`:

```js
"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initConnectionGate(Ao) {
  let onConnected = null;
  let lastState = null;
  let pollTimer = null;

  function el() {
    return document.getElementById("connection-gate");
  }

  function setText(selector, text) {
    const node = el()?.querySelector(selector);
    if (node) node.textContent = text;
  }

  function render(stateName, detail) {
    const gate = el();
    if (!gate) return;
    const wasConnected = lastState === "connected";

    if (stateName === "connected") {
      gate.hidden = true;
      if (!wasConnected) onConnected?.();
      lastState = stateName;
      return;
    }

    gate.hidden = false;
    const failed = stateName === "failed";
    const occupied = (detail || "").startsWith("port_occupied:");
    setText("[data-gate-title]", failed ? "無法連線到本地 daemon" : "連線中…");
    setText(
      "[data-gate-detail]",
      failed
        ? occupied
          ? `埠 8767 已被其他程序佔用 (pid ${detail.split(":")[1]})；請先停止該程序再重試。`
          : "daemon 多次啟動失敗，已停止自動重試。"
        : "正在啟動 / 等待 agentd…",
    );
    const actions = gate.querySelector("[data-gate-actions]");
    if (actions) actions.hidden = !failed;
    lastState = stateName;
  }

  async function pollHealth() {
    try {
      await Ao.apiFetch(Ao.ENDPOINTS.health);
      render("connected", "ok");
      stopPolling();
    } catch {
      render("connecting", "");
    }
  }

  function startPolling() {
    if (pollTimer) return;
    pollHealth();
    pollTimer = window.setInterval(pollHealth, 3000);
  }

  function stopPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  Ao.ConnectionGate = {
    init({ onConnected: callback } = {}) {
      onConnected = callback || null;
      const tauri = window.__TAURI__;
      const listen = tauri?.event?.listen;
      const invoke = tauri?.core?.invoke;

      const retryBtn = document.querySelector("[data-gate-retry]");
      const logBtn = document.querySelector("[data-gate-log]");
      if (retryBtn) {
        retryBtn.addEventListener("click", async () => {
          render("connecting", "");
          if (invoke) {
            try {
              await invoke("retry_daemon");
            } catch (error) {
              console.warn("retry_daemon failed", error);
            }
          } else {
            startPolling();
          }
        });
      }
      if (logBtn) {
        logBtn.hidden = !invoke;
        logBtn.addEventListener("click", () => {
          invoke?.("open_daemon_log");
        });
      }

      if (listen) {
        // Seed initial state immediately (events emitted before we subscribed are missed),
        // then react to subsequent transitions.
        render("connecting", "");
        pollHealth();
        listen("connection-state", (event) => {
          const payload = event.payload || {};
          render(payload.state, payload.detail);
        });
      } else {
        startPolling();
      }
    },
  };
})(window.AgenticOs);
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/ui/connection-gate.js
git commit -m "feat(web): connection gate overlay module"
```

---

### Task 9: webview — overlay markup, styles, and app.js mount (`apps/web`)

**Files:**
- Modify: `apps/web/index.html`
- Modify: `apps/web/styles.css`
- Modify: `apps/web/app.js`

- [ ] **Step 1: Add the gate script tag**

In `apps/web/index.html`, add this line immediately before `<script src="app.js" defer></script>`:

```html
<script src="ui/connection-gate.js"></script>
```

- [ ] **Step 2: Add the overlay markup**

In `apps/web/index.html`, add this block as the first child inside `<body>` (before existing content):

```html
<div id="connection-gate" hidden>
  <div class="connection-gate__card">
    <div class="connection-gate__spinner" aria-hidden="true"></div>
    <h2 data-gate-title>連線中…</h2>
    <p data-gate-detail>正在啟動 / 等待 agentd…</p>
    <div class="connection-gate__actions" data-gate-actions hidden>
      <button type="button" data-gate-retry>重試</button>
      <button type="button" data-gate-log hidden>開啟 log</button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add the overlay styles**

Append to `apps/web/styles.css`:

```css
#connection-gate {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 17, 21, 0.92);
}
#connection-gate[hidden] {
  display: none;
}
.connection-gate__card {
  text-align: center;
  padding: 2rem 2.5rem;
  color: #f4f5f7;
}
.connection-gate__card h2 {
  margin: 0.75rem 0 0.25rem;
}
.connection-gate__spinner {
  width: 32px;
  height: 32px;
  margin: 0 auto;
  border: 3px solid rgba(255, 255, 255, 0.2);
  border-top-color: #fff;
  border-radius: 50%;
  animation: connection-gate-spin 0.8s linear infinite;
}
.connection-gate__actions {
  margin-top: 1rem;
}
.connection-gate__actions button {
  margin: 0 0.25rem;
}
@keyframes connection-gate-spin {
  to {
    transform: rotate(360deg);
  }
}
```

- [ ] **Step 4: Mount the gate in app.js**

In `apps/web/app.js`, in the `DOMContentLoaded` handler, replace the trailing call:

```js
  bindTabs();
  bindControls();
  refreshAll();
});
```

with:

```js
  bindTabs();
  bindControls();
  const mode = state.connectionProfile?.mode || "local";
  if (mode === "remote") {
    refreshAll();
  } else {
    Ao.ConnectionGate.init({ onConnected: () => refreshAll() });
  }
});
```

- [ ] **Step 5: Verify the plain-web path manually**

Ensure a daemon is running, then:

Run: `cd apps/web && python3 -m http.server 5199`
Open `http://127.0.0.1:5199` in a browser. Expected: the overlay shows "連線中…" briefly, then disappears and the dashboard loads (the gate's `pollHealth` succeeded against `:8767`). Stop the server with Ctrl-C.

- [ ] **Step 6: Commit**

```bash
git add apps/web/index.html apps/web/styles.css apps/web/app.js
git commit -m "feat(web): mount connection gate overlay"
```

---

### Task 10: mirror the webview changes into the bundled copy

**Files:**
- Create: `apps/desktop/src-tauri/bundle-resources/agentic-os/web/ui/connection-gate.js`
- Modify: `apps/desktop/src-tauri/bundle-resources/agentic-os/web/index.html`
- Modify: `apps/desktop/src-tauri/bundle-resources/agentic-os/web/styles.css`
- Modify: `apps/desktop/src-tauri/bundle-resources/agentic-os/web/app.js`

The packaged app serves its own `web/` copy, so it must match `apps/web/`.

- [ ] **Step 1: Copy the four files**

Run:

```bash
cd /Users/waynetu/bootstrap/agentic-os
BUNDLE=apps/desktop/src-tauri/bundle-resources/agentic-os/web
cp apps/web/ui/connection-gate.js "$BUNDLE/ui/connection-gate.js"
cp apps/web/app.js "$BUNDLE/app.js"
cp apps/web/index.html "$BUNDLE/index.html"
cp apps/web/styles.css "$BUNDLE/styles.css"
```

- [ ] **Step 2: Verify the copies are identical**

Run:

```bash
cd /Users/waynetu/bootstrap/agentic-os
BUNDLE=apps/desktop/src-tauri/bundle-resources/agentic-os/web
for f in ui/connection-gate.js app.js index.html styles.css; do
  diff -q "apps/web/$f" "$BUNDLE/$f" && echo "OK $f"
done
```

Expected: four `OK` lines, no `differ` output.

> If `apps/web/` and the bundled `web/` had pre-existing intentional differences in `app.js`/`index.html`/`styles.css`, do NOT blindly overwrite — instead apply the same three edits from Tasks 8–9 by hand to the bundled copy and re-run the diff on just `ui/connection-gate.js`. Inspect with `diff apps/web/app.js "$BUNDLE/app.js"` before copying.

- [ ] **Step 3: Commit**

```bash
git add apps/desktop/src-tauri/bundle-resources/agentic-os/web
git commit -m "feat(desktop): mirror connection gate into bundled web assets"
```

---

### Task 11: full verification

**Files:** none (verification only).

- [ ] **Step 1: Rust build + tests**

Run: `cd apps/desktop/src-tauri && cargo build && cargo test --lib`
Expected: build succeeds; all unit tests PASS.

- [ ] **Step 2: Backend suite unchanged**

Run: `cd /Users/waynetu/bootstrap/agentic-os && uv run pytest -q && uv run ruff check .`
Expected: full suite green and ruff clean (no backend files changed, so this confirms no accidental breakage).

- [ ] **Step 3: Manual e2e — auto-restart**

Launch the desktop app in dev mode (from a terminal so dev-mode `rtk`/`uv` resolve):

Run: `cd apps/desktop && npm run tauri dev` (or the project's usual dev command).

With the app connected (overlay gone, dashboard loaded):
- In another terminal: `pkill -f "agentd serve"`.
- Expected: within ~5s the tray title flips toward "down", the webview overlay reappears ("連線中…" / restarting), and within ~15s the daemon is back and the overlay disappears — without any terminal action.

- [ ] **Step 4: Manual e2e — failed/port-occupied surface**

With the app running, occupy the port with a non-serving process and kill the managed daemon:

Run: `pkill -f "agentd serve"; python3 -c "import socket,time; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('127.0.0.1',8767)); s.listen(); time.sleep(120)"`

Expected: after `MAX_RESTART_ATTEMPTS` (5) bounded attempts the overlay shows the failed state with a `port_occupied:<pid>` message, a working "重試" button, and an "開啟 log" button that opens `daemon.log`. No crash-loop spinning faster than the backoff. Stop the squatter (Ctrl-C) and click "重試" — the app recovers.

- [ ] **Step 5: Final commit (if any verification fixups were needed)**

```bash
git add -A
git commit -m "test(desktop): verify auto-connect supervisor end-to-end"
```

(Skip if nothing changed in this task.)

---

## Notes for the implementer

- Event name is `connection-state` (the spec's `connection://state` was a placeholder; `-` avoids URL-scheme parsing quirks in event names).
- The supervisor probes via the existing `desktop-daemon.sh status`/`start`, so it never bypasses the script's own idempotent "adopt healthy external daemon" logic — running your own `start-local.sh` daemon in a terminal will be adopted, not fought.
- The supervisor thread refreshes the tray title for both modes and only supervises/restarts in **local** mode; remote mode keeps its existing probe/title behavior.
- PATH hardening **appends** the required dirs to the inherited PATH (it does not replace it), so dev-mode `rtk`/`uv` on the user's PATH keep working while Finder-launched bundles still resolve `bash`/`python3`/`lsof`.
