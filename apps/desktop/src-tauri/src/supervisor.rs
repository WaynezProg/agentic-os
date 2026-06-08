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
                let ok = started && daemon::status().map(|s| s.is_healthy()).unwrap_or(false);
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
