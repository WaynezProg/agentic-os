# P11 Desktop App Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Tauri desktop shell that embeds the static web UI on `localhost:5173`, manages `agentd` via shell scripts, and persists local/remote-placeholder settings in `~/.agentic-os/desktop.toml`.

**Architecture:** pnpm workspace with `apps/desktop` (Tauri 2). Rust invokes `scripts/desktop-daemon.sh` and `scripts/desktop-ui.sh` only — no direct harness logic. Webview loads existing `apps/web`. Settings via Tauri commands; daemon API stays `127.0.0.1:8767`.

**Tech Stack:** Tauri 2, Rust, pnpm, bash, existing Python `agentd` + `apps/web` static files.

**Design reference:** `docs/superpowers/specs/2026-06-07-p11-desktop-app-shell-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `pnpm-workspace.yaml` | Create | Monorepo root |
| `package.json` | Create | Workspace root scripts |
| `scripts/desktop-daemon.sh` | Create | agentd start/stop/status |
| `scripts/desktop-ui.sh` | Create | Static UI server start/stop/status |
| `scripts/lib/desktop-common.sh` | Create | Shared PID/log/path helpers |
| `tests/test_desktop_scripts.py` | Create | Script JSON contract tests |
| `apps/desktop/package.json` | Create | Tauri frontend package |
| `apps/desktop/src-tauri/Cargo.toml` | Create | Rust deps |
| `apps/desktop/src-tauri/tauri.conf.json` | Create | App metadata, bundle |
| `apps/desktop/src-tauri/src/main.rs` | Create | Lifecycle + commands |
| `apps/desktop/src-tauri/src/daemon.rs` | Create | Script invocation |
| `apps/desktop/src-tauri/src/settings.rs` | Create | desktop.toml read/write |
| `apps/desktop/index.html` | Create | Optional splash / redirect (minimal) |
| `specs/028-desktop-app-shell.md` | Create | Phase spec |
| `README.md` | Modify | P11 phase row + desktop dev instructions |

---

## Task 1: pnpm workspace scaffold

**Files:**
- Create: `pnpm-workspace.yaml`
- Create: `package.json`

- [ ] **Step 1: Create workspace files**

`pnpm-workspace.yaml`:

```yaml
packages:
  - "apps/desktop"
```

Root `package.json`:

```json
{
  "name": "agentic-os",
  "private": true,
  "packageManager": "pnpm@9.15.0",
  "scripts": {
    "desktop:dev": "pnpm --filter @agentic-os/desktop tauri dev",
    "desktop:build": "pnpm --filter @agentic-os/desktop tauri build"
  }
}
```

- [ ] **Step 2: Verify pnpm available**

Run: `corepack enable && pnpm --version`
Expected: version prints (use mise-managed Node if present).

- [ ] **Step 3: Commit**

```bash
git add pnpm-workspace.yaml package.json
git commit -m "chore: add pnpm workspace for desktop app"
```

---

## Task 2: Shared desktop script helpers

**Files:**
- Create: `scripts/lib/desktop-common.sh`

- [ ] **Step 1: Implement helpers**

```bash
#!/usr/bin/env bash
# scripts/lib/desktop-common.sh — sourced by desktop-*.sh

set -euo pipefail

desktop_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd
}

desktop_state_dir() {
  echo "${AGENTIC_OS_STATE_DIR:-$(desktop_root)/.agentic-os}"
}

desktop_runtime_dir() {
  mkdir -p "$(desktop_state_dir)/desktop"
  echo "$(desktop_state_dir)/desktop"
}

read_pid() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    cat "$pid_file"
  fi
}

write_pid() {
  echo "$2" > "$1"
}

is_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}
```

- [ ] **Step 2: Commit**

```bash
git add scripts/lib/desktop-common.sh
git commit -m "chore: add shared helpers for desktop lifecycle scripts"
```

---

## Task 3: desktop-daemon.sh

**Files:**
- Create: `scripts/desktop-daemon.sh`
- Create: `tests/test_desktop_scripts.py`

- [ ] **Step 1: Write failing status test**

```python
# tests/test_desktop_scripts.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_daemon_status_json_when_down(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_OS_STATE_DIR", str(tmp_path / ".agentic-os"))
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/desktop-daemon.sh"), "status"],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    payload = json.loads(result.stdout)
    assert payload["health"] in ("ok", "down")
    assert "running" in payload
    assert "managed" in payload
    assert payload["api_url"] == "http://127.0.0.1:8767"
```

- [ ] **Step 2: Run test — FAIL** (script missing)

Run: `rtk uv run pytest tests/test_desktop_scripts.py::test_desktop_daemon_status_json_when_down -v`

- [ ] **Step 3: Implement desktop-daemon.sh**

Key behavior:
- `source scripts/lib/desktop-common.sh`
- `start`: if `curl -sf http://127.0.0.1:8767/health` → exit 0 with message (external)
- else spawn `rtk uv run agentd serve ...` in background, save PID, redirect log
- `stop`: kill managed PID only
- `status`: emit JSON to stdout

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/desktop-common.sh
source "$ROOT/scripts/lib/desktop-common.sh"

API_URL="${AGENTIC_OS_API_URL:-http://127.0.0.1:8767}"
PID_FILE="$(desktop_runtime_dir)/daemon.pid"
LOG_FILE="$(desktop_runtime_dir)/daemon.log"

health_check() {
  curl -sf "${API_URL}/health" >/dev/null 2>&1
}

cmd_status() {
  local pid managed=false running=false health=down
  pid="$(read_pid "$PID_FILE" || true)"
  if is_running "$pid"; then managed=true; running=true; fi
  if ! $running && health_check; then running=true; fi
  if $running && health_check; then health=ok; fi
  python3 - <<EOF
import json
print(json.dumps({
  "running": ${running,,},
  "managed": ${managed,,},
  "pid": ${pid:-null},
  "api_url": "${API_URL}",
  "health": "${health}",
}))
EOF
}
```

Implement `start`, `stop`, `restart` dispatching on `$1`.

- [ ] **Step 4: Run test — PASS**

- [ ] **Step 5: Commit**

```bash
git add scripts/desktop-daemon.sh tests/test_desktop_scripts.py
git commit -m "feat: add desktop-daemon.sh lifecycle script"
```

---

## Task 4: desktop-ui.sh

**Files:**
- Create: `scripts/desktop-ui.sh`
- Modify: `tests/test_desktop_scripts.py`

- [ ] **Step 1: Add UI status test**

```python
def test_desktop_ui_status_json(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_OS_STATE_DIR", str(tmp_path / ".agentic-os"))
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/desktop-ui.sh"), "status"],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    payload = json.loads(result.stdout)
    assert payload["ui_url"] == "http://127.0.0.1:5173"
    assert "running" in payload
```

- [ ] **Step 2: Implement desktop-ui.sh**

Mirror daemon script:
- Serve `"$ROOT/apps/web"` via `rtk uv run python -m http.server 5173 --bind 127.0.0.1`
- PID: `.agentic-os/desktop/ui.pid`
- Status JSON: `{ running, managed, pid, ui_url }`

- [ ] **Step 3: Run tests — PASS**

Run: `rtk uv run pytest tests/test_desktop_scripts.py -v`

- [ ] **Step 4: Commit**

```bash
git add scripts/desktop-ui.sh tests/test_desktop_scripts.py
git commit -m "feat: add desktop-ui.sh static server lifecycle script"
```

---

## Task 5: Tauri app scaffold

**Files:**
- Create: `apps/desktop/package.json`
- Create: `apps/desktop/src-tauri/` via `pnpm create tauri-app` pattern

- [ ] **Step 1: Initialize Tauri 2 in apps/desktop**

From repo root:

```bash
cd apps/desktop
pnpm init
pnpm add -D @tauri-apps/cli@^2
pnpm add @tauri-apps/api@^2
pnpm tauri init --ci \
  --app-name "agentic-os" \
  --window-title "agentic-os" \
  --dev-url "http://127.0.0.1:5173" \
  --frontend-dist "../web"
```

Adjust generated `tauri.conf.json`:
- `identifier`: `dev.agentic-os.desktop`
- `app.windows[0].url`: `http://127.0.0.1:5173`
- `bundle.macOS.minimumSystemVersion`: `12.0`

Set `package.json` name to `@agentic-os/desktop`.

- [ ] **Step 2: Wire root scripts**

Run from root: `pnpm install`

- [ ] **Step 3: Commit**

```bash
git add apps/desktop pnpm-lock.yaml
git commit -m "feat: scaffold Tauri desktop app in apps/desktop"
```

---

## Task 6: Rust script bridge (daemon + ui)

**Files:**
- Create: `apps/desktop/src-tauri/src/daemon.rs`
- Modify: `apps/desktop/src-tauri/src/main.rs`
- Modify: `apps/desktop/src-tauri/src/lib.rs` (if created by scaffold)

- [ ] **Step 1: Implement run_script helper**

```rust
// apps/desktop/src-tauri/src/daemon.rs
use std::path::PathBuf;
use std::process::Command;

fn repo_root() -> PathBuf {
    // walk up from resource_dir or env AGENTIC_OS_ROOT
    std::env::var("AGENTIC_OS_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| std::env::current_dir().expect("cwd"))
}

pub fn run_desktop_script(script: &str, cmd: &str) -> Result<String, String> {
    let root = repo_root();
    let path = root.join("scripts").join(script);
    let output = Command::new("bash")
        .arg(path)
        .arg(cmd)
        .current_dir(&root)
        .output()
        .map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).into_owned());
    }
    Ok(String::from_utf8_lossy(&output.stdout).into_owned())
}
```

- [ ] **Step 2: Register Tauri commands**

```rust
#[tauri::command]
fn daemon_status() -> Result<String, String> {
    daemon::run_desktop_script("desktop-daemon.sh", "status")
}

#[tauri::command]
fn daemon_start() -> Result<String, String> {
    daemon::run_desktop_script("desktop-daemon.sh", "start")
}

#[tauri::command]
fn daemon_stop() -> Result<String, String> {
    daemon::run_desktop_script("desktop-daemon.sh", "stop")
}
```

Same pattern for `ui_*` commands.

- [ ] **Step 3: Manual smoke**

```bash
pnpm desktop:dev
```

Expected: app window attempts load of `http://127.0.0.1:5173` (may fail until Task 7 lifecycle).

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add Tauri commands wrapping desktop lifecycle scripts"
```

---

## Task 7: App launch lifecycle

**Files:**
- Modify: `apps/desktop/src-tauri/src/main.rs`

- [ ] **Step 1: On setup hook, start ui + daemon**

```rust
.setup(|app| {
    let handle = app.handle().clone();
    tauri::async_runtime::spawn(async move {
        let _ = daemon::run_desktop_script("desktop-ui.sh", "start");
        let _ = daemon::run_desktop_script("desktop-daemon.sh", "start");
        // poll health up to 15s
        for _ in 0..30 {
            if daemon::health_ok().await { break; }
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;
        }
    });
    Ok(())
})
```

- [ ] **Step 2: On exit, stop managed processes**

```rust
.run(|app_handle, event| {
    if let RunEvent::Exit = event {
        let _ = daemon::run_desktop_script("desktop-ui.sh", "stop");
        let _ = daemon::run_desktop_script("desktop-daemon.sh", "stop");
    }
})
```

- [ ] **Step 3: Manual smoke**

1. Quit any running agentd on 8767
2. `pnpm desktop:dev`
3. Web UI loads, sidebar shows agents
4. Quit app → `desktop-daemon.sh status` shows down (managed)

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: auto-start ui and daemon on desktop app launch"
```

---

## Task 8: desktop.toml settings module

**Files:**
- Create: `apps/desktop/src-tauri/src/settings.rs`
- Modify: `apps/desktop/src-tauri/src/main.rs`

- [ ] **Step 1: Define DesktopSettings struct**

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DesktopSettings {
    pub connection: ConnectionSettings,
    pub local: LocalSettings,
    pub remote: RemoteSettings,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoteSettings {
    pub gateway_url: String,
    pub event_stream_url: String,
    pub token: String,
    pub pairing_code: String,
    pub paired_device_id: String,
}
```

Defaults match design doc. Path: `~/.agentic-os/desktop.toml` using `dirs::home_dir()`.

Use `toml` crate for parse/serialize.

- [ ] **Step 2: Tauri commands**

```rust
#[tauri::command]
fn get_desktop_settings() -> Result<DesktopSettings, String> { ... }

#[tauri::command]
fn save_desktop_settings(settings: DesktopSettings) -> Result<(), String> { ... }
```

- [ ] **Step 3: Rust unit test for defaults round-trip**

In `settings.rs`:

```rust
#[cfg(test)]
mod tests {
    #[test]
    fn default_settings_serialize() {
        let settings = DesktopSettings::default();
        let toml = toml::to_string(&settings).unwrap();
        assert!(toml.contains("mode = \"local\""));
    }
}
```

Run: `cd apps/desktop/src-tauri && cargo test`

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add desktop.toml settings read/write in Tauri"
```

---

## Task 9: System tray + minimal settings window

**Files:**
- Modify: `apps/desktop/src-tauri/tauri.conf.json`
- Modify: `apps/desktop/src-tauri/src/main.rs`
- Create: `apps/desktop/settings.html` (minimal form)

- [ ] **Step 1: Enable tray in tauri.conf.json**

Add tray icon and menu items: `Daemon: Start`, `Daemon: Stop`, `Settings`, `Quit`.

- [ ] **Step 2: Wire menu events to daemon_* commands**

On `Daemon: Stop` → `daemon_stop()` + refresh tray label.

Tray title shows `agentd: ok` / `agentd: down` (poll every 5s).

- [ ] **Step 3: Settings window**

Small secondary window loading `settings.html` with form fields for `[remote]` placeholders and `[local].api_url`. Save calls `invoke('save_desktop_settings')`.

**P11:** fields are editable but remote mode does not change webview URL yet.

- [ ] **Step 4: Manual smoke**

Tray stop → web UI health indicator fails → tray start → recovers.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add system tray and settings shell for desktop app"
```

---

## Task 10: Spec, README, CI note

**Files:**
- Create: `specs/028-desktop-app-shell.md`
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml` (comment or optional job only — do not block Linux CI on Tauri macOS build)

- [ ] **Step 1: Create spec 028**

Copy acceptance table from design doc. Status: `Implemented` after tasks pass.

- [ ] **Step 2: README section**

```markdown
## Desktop app (P11)

macOS-validated Tauri shell. Requires Node (pnpm) + Rust toolchain for local build.

pnpm install
pnpm desktop:dev      # opens app, starts ui:5173 + agentd:8767
pnpm desktop:build    # macOS .app bundle
```

Add P11 row to phase table.

- [ ] **Step 3: Python CI unchanged**

Run: `rtk uv run pytest -q && rtk uv run ruff check .`
Expected: all pass (desktop scripts tests included).

- [ ] **Step 4: Commit**

```bash
git add specs/028-desktop-app-shell.md README.md
git commit -m "docs: add P11 desktop app shell spec and README"
```

---

## Task 11: macOS build smoke + PR

- [ ] **Step 1: Production build**

```bash
pnpm desktop:build
```

Expected: `apps/desktop/src-tauri/target/release/bundle/macos/agentic-os.app`

- [ ] **Step 2: Launch built app**

Open `.app`, confirm web UI + daemon lifecycle.

- [ ] **Step 3: PR checklist**

- [ ] `pytest -q` (N passed)
- [ ] `ruff check .`
- [ ] Manual: tray start/stop
- [ ] Manual: settings save `desktop.toml`
- [ ] Document: Windows/Linux untested

---

## Self-Review (plan vs design)

| Design requirement | Task |
|--------------------|------|
| Embedded static server :5173 | 4, 7 |
| desktop-daemon.sh | 3 |
| Tauri invokes scripts only | 6 |
| desktop.toml schema + Tauri API | 8, 9 |
| Remote placeholders, no connection | 8, 9 |
| pnpm workspace | 1, 5 |
| macOS validate, cross-platform config | 5, 11 |
| No iOS/SSE/pairing backend | Enforced by scope |
| No new agent features | Enforced by scope |

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-06-07-p11-desktop-app-shell.md`.

**1. Subagent-Driven (recommended)** — one task per subagent  
**2. Inline Execution** — sequential in one session

Which approach?
