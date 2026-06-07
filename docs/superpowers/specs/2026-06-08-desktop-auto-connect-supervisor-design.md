# Desktop App Auto-Connect Supervisor — Design

Date: 2026-06-08
Status: Approved (brainstorm), pending implementation plan
Area: `apps/desktop` (Tauri shell + lifecycle scripts + bundled web UI). No Python backend change.
Relates to: P11 (desktop app shell), P11.5 (packaged macOS app), P12 (remote access adapter).

## Problem

The desktop app already auto-starts the local daemon once at launch
(`lib.rs` `setup()` → `daemon::start_stack()` → `desktop-daemon.sh start`),
and the tray polls health every 5s (`refresh_tray_title`). But:

1. **No supervision after launch.** `start_stack()` runs once. If the daemon
   later dies (crash, machine sleep/wake, OOM), the app never restarts it. The
   user sees "no connection" and must start it from a terminal. This is the
   reported incident.
2. **Start failures are swallowed.** `start_stack()` uses `let _ = ...`. A
   failed start produces no surfaced error — only the tray title eventually
   reads "down" and the webview shows a bare "no connection".
3. **Webview does not wait for health.** It loads immediately; if the daemon is
   not yet healthy (start can take up to ~15s) the UI shows "no connection"
   until a manual refresh.
4. **Packaged build PATH risk.** macOS GUI apps launched from Finder/Dock do
   not inherit the user's shell PATH. Lifecycle scripts and the Rust spawner
   rely on `bash`/`python3`/(dev: `rtk`,`uv`) being on PATH. Dev runs from a
   terminal so it works today; a packaged `.app` launched from Finder is at
   risk.

## Goals

- When the user opens the app, a healthy local daemon is reachable without any
  terminal step — at launch **and** continuously while the app runs.
- If the daemon goes down mid-session, the app auto-restarts it with bounded
  backoff; after a retry ceiling it stops and surfaces an actionable error.
- The webview shows an honest connecting / restarting / failed state and
  recovers automatically when the daemon becomes healthy.
- A packaged `.app` launched from Finder/Dock can start its bundled daemon
  without relying on the user's shell PATH.

## Non-goals

- No new long-lived process owner (no launchd agent, no separate supervisor
  daemon). The Tauri app process remains the single owner of its child daemon,
  consistent with the repo principle "no new daemons/process owners".
- The app never kills a process it does not own. A foreign process occupying
  port 8767 is surfaced for **manual** reclaim, not force-killed automatically.
- No change to the Python daemon, API, or remote-access adapter behavior.
- Remote (gateway) connection mode keeps its existing probe path; supervision
  applies to **local** mode only.

## Chosen approach

**Rust supervisor + event-driven webview connection gate.**

The existing 5s tray-poll loop is upgraded into a supervisor that owns health
monitoring and bounded-backoff auto-restart, and emits connection-state events.
The webview owns only the connecting/failed overlay, driven by those events
(with a polling fallback for plain-web mode). This respects the single-owner
model: Rust supervises the child; the webview never makes restart decisions.

Rejected alternatives:
- **Script/launchd supervisor** — introduces a new persistent process owner,
  conflicts with the no-new-daemon principle, complicates lifecycle/teardown,
  and is overkill for "connect when I open the app".
- **Frontend-only retry** — the webview as supervisor is fragile (multi-window,
  reload races, cannot recover when no window is open / tray-only), and does
  not fix the "app in tray, daemon died" case.

## Design

### 1. Connection state machine (`supervisor.rs`, new)

States: `connecting`, `connected`, `restarting`, `failed`.

Per supervisor tick (every 5s) and on demand:
1. Query local daemon health (via `daemon::status()` parsed JSON; `health == "ok"`).
2. `health ok` → state `connected`; reset `fail_count = 0`; clear cooldown.
3. `down` and `fail_count < MAX` and not inside backoff cooldown:
   - emit `restarting`, call `daemon::start()` (the script blocks up to ~15s
     waiting for health). Re-check health:
     - ok → `connected`, reset `fail_count`.
     - still down → `fail_count += 1`, set next-attempt time to
       `now + backoff(fail_count)`.
4. `fail_count >= MAX` → state `failed`; stop auto-restart until a manual
   trigger (tray "Start daemon" or webview "Retry") resets `fail_count = 0`.
5. **Port-occupied guard:** if `down` and `listener_pid(8767)` is non-empty and
   that pid is not our managed pid, go straight to `failed` with
   `detail = "port_occupied"` and the offending pid — do **not** crash-loop a
   bind that will fail. Surfaced with a manual reclaim affordance.

Constants: `MAX_RESTART_ATTEMPTS = 5`; `BACKOFF_SECS = [0, 5, 15, 30, 60]`
(index by `fail_count`, clamped to last = 60s cap); tick interval `5s`
(unchanged from current poll).

Only one start may be in flight at a time (an in-flight guard / mutex) so
overlapping ticks cannot launch duplicate daemons.

The core decision is a **pure function** for testability:

```
next_action(health: Health, fail_count: u32, now: Instant, next_attempt_at: Option<Instant>)
    -> SupervisorAction
// SupervisorAction ∈ { None, Attempt, MarkFailed }
```

On each transition, emit Tauri event `connection://state` with payload
`{ state, detail, api_url, log_path, pid }`.

### 2. `daemon.rs` changes

- `status() -> DaemonStatus` — typed parse of the `desktop-daemon.sh status`
  JSON (`running`, `managed`, `pid`, `api_url`, `health`).
- `restart()` — convenience over existing start/stop (used by manual Retry).
- `listener_pid(port) -> Option<u32>` — best-effort, mirrors the shell helper,
  for the port-occupied guard.
- **PATH hardening in `run_script`:** invoke `/bin/bash` (absolute) and set a
  clean `PATH` env (`/usr/bin:/bin:/usr/sbin:/sbin` plus the bundled runtime
  `bin` dir in bundle mode), while passing through existing `AGENTIC_OS_*`
  env. This makes Finder-launched scripts resolve `bash`/`python3`/the bundled
  `agentd` reliably without the user's shell PATH.

### 3. Webview connection gate (`web/ui/connection-gate.js`, new)

- On load: if `window.__TAURI__` present → subscribe to `connection://state`.
  Otherwise (plain-web mode served by `http.server`) → poll `GET /health`
  every 3s.
- Render a full-area overlay for `connecting` / `restarting`; hide it on
  `connected` and trigger a (re)load of dashboard data.
- `failed` state: show `detail`, plus a **Retry** button (invokes
  `daemon_start` / resets the supervisor in Tauri mode; resumes polling in web
  mode) and an **Open log** affordance (the `log_path` from the event).
- Feature-detected so both Tauri and plain-web modes work and neither throws.
- Mounted from `app.js`; `<script src="ui/connection-gate.js">` added to
  `index.html` before `app.js`.

### 4. Lifecycle script hardening (`desktop-daemon.sh`, `desktop-ui.sh`, `lib/desktop-common.sh`)

- Prefer an absolute `python3` (`/usr/bin/python3`) when `python3` is not on
  PATH, for `health_check` / `status` / the UI server. Bundle mode already uses
  an absolute `agentd` binary and has no `rtk`/`uv` dependency — keep it that
  way.
- The `status` JSON contract is unchanged. The port-occupied guard is computed
  Rust-side via `daemon::listener_pid` (single source), so the scripts gain no
  new fields.

### 5. lib.rs wiring

- Replace the title-only 5s poll task with the supervisor tick (which both
  refreshes the tray title and runs `next_action`). Keep `reconcile_stack()` +
  initial `start_stack()` at setup; the supervisor takes over thereafter.
- Tray "Start daemon" / "Stop daemon" remain and additionally reset the
  supervisor `fail_count` (Start) so a user can recover from `failed`.
- Register any new commands needed by the webview gate (e.g. a `retry_daemon`
  that resets fail_count and forces an attempt). Remote mode is unchanged.

## Files touched

- `apps/desktop/src-tauri/src/supervisor.rs` (new)
- `apps/desktop/src-tauri/src/lib.rs` (wire supervisor, command registration)
- `apps/desktop/src-tauri/src/daemon.rs` (typed status, restart, listener_pid, PATH-hardened run_script)
- `apps/desktop/src-tauri/bundle-resources/agentic-os/scripts/desktop-daemon.sh`
- `apps/desktop/src-tauri/bundle-resources/agentic-os/scripts/desktop-ui.sh`
- `apps/desktop/src-tauri/bundle-resources/agentic-os/scripts/lib/desktop-common.sh`
- Web UI — **two copies kept in sync**:
  - `apps/web/ui/connection-gate.js` (new), `apps/web/app.js`, `apps/web/index.html`
  - `apps/desktop/src-tauri/bundle-resources/agentic-os/web/ui/connection-gate.js` (new), `.../web/app.js`, `.../web/index.html`

## Testing

- **Rust unit tests** (mirror existing `daemon.rs` test style):
  - `next_action` backoff/cap/`MarkFailed` at `MAX`, and reset semantics.
  - `DaemonStatus` JSON parse (healthy, down, missing fields).
  - PATH builder produces the expected clean PATH in bundle vs dev mode.
- **Manual e2e:**
  - Launch app → `kill` the daemon → observe `restarting` → `connected` and the
    webview overlay clearing automatically.
  - Occupy port 8767 with a foreign process → observe `failed (port_occupied)`
    with reclaim affordance, and no crash-loop in `daemon.log`.
  - Packaged `.app` launched from Finder → daemon starts (PATH-independent).
- The Python suite (`uv run pytest -q`) and `ruff` must remain green (no
  backend change expected); `cargo`/Rust tests for the desktop crate run for
  the new logic.

## Risks / decisions

- **Crash-loop burn:** bounded by `MAX=5` + backoff, then `failed` with surfaced
  error (decided: stop + show error, not infinite retry).
- **Killing foreign processes:** explicitly out of scope — port-occupied is
  surfaced for manual reclaim only.
- **Two web copies drift:** the plan must update both `apps/web/` and the
  bundled `web/` and note this in verification.
- **Tick coupling to tray:** the supervisor and tray-title refresh share one
  5s loop; the start attempt is run on a blocking task so it does not stall the
  loop, guarded so only one start is in flight.

## Out of scope

- Remote/gateway-mode supervision (keeps existing probe).
- Windows/Linux packaging specifics (design is macOS-first; PATH hardening is
  written portably but verified on macOS).
- Any change to the daemon, API surface, or policy gate.
