# P11 — macOS Desktop App Shell Design

Date: 2026-06-07
Status: Approved for implementation
Author: agentic-os team
Builds on: P10 (`specs/027-safe-native-config-editing.md`), P2 (`specs/003-thin-ui.md`)
Blocks: P12 (`specs/030-remote-access-adapter.md`)

## Summary

Ship a **Tauri desktop shell** that wraps the existing static web UI (`apps/web/`) and manages
local **agentd** lifecycle. The desktop app is a client only — it does not own harness runs,
SQLite state, or config writes (those remain in `agentd`).

P11 scope: **desktop shell + daemon/UI lifecycle + local settings file with remote placeholders**.
No iOS, no remote gateway, no pairing backend, no SSE/WebSocket endpoint in daemon.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Web UI loading | Embed `python -m http.server` via `desktop-ui.sh`; webview → `http://127.0.0.1:5173` |
| agentd lifecycle | `scripts/desktop-daemon.sh` (`start\|stop\|status\|restart`); Tauri invokes scripts only |
| Remote companion | Settings UI + `~/.agentic-os/desktop.toml` schema + Tauri read/write API; connection logic P12 |
| Repo layout | pnpm workspace monorepo; `apps/desktop` Tauri project; `apps/web` unchanged static files |
| Platform | Tauri cross-platform config; **P11 validates macOS only**; Windows/Linux documented untested |

## Architecture

```
apps/desktop (Tauri)
  ├─ webview → http://127.0.0.1:5173   ← desktop-ui.sh → apps/web
  ├─ scripts/desktop-daemon.sh         ← agentd :8767
  ├─ tray: daemon status, start/stop, quit
  └─ Tauri commands → ~/.agentic-os/desktop.toml

agentd (Python)     sole owner of runs, DB, patch writes
apps/web/           thin HTTP client (DEFAULT_API_URL 127.0.0.1:8767)
```

## Script contracts

### `scripts/desktop-daemon.sh`

Commands: `start | stop | status | restart`

- PID file: `.agentic-os/desktop/daemon.pid`
- Log file: `.agentic-os/desktop/daemon.log`
- Start: `rtk uv run agentd serve --host 127.0.0.1 --port 8767 --state-dir … --registry …`
- Stop: kill process group from PID file (managed only)
- Status JSON: `{ "running": bool, "managed": bool, "pid": int|null, "api_url": str, "health": "ok"|"down" }`
- If `/health` OK but PID file missing → `running: true, managed: false` (external agentd)

### `scripts/desktop-ui.sh`

Commands: `start | stop | status | restart`

- PID file: `.agentic-os/desktop/ui.pid`
- Serves `apps/web` on `127.0.0.1:5173`
- Status JSON: `{ "running": bool, "managed": bool, "pid": int|null, "ui_url": str }`

## Desktop settings (`~/.agentic-os/desktop.toml`)

```toml
[connection]
mode = "local"  # local | remote (remote inactive in P11)

[local]
api_url = "http://127.0.0.1:8767"
ui_url = "http://127.0.0.1:5173"

[remote]
gateway_url = ""
event_stream_url = ""
token = ""
pairing_code = ""
paired_device_id = ""
```

Read/write via **Tauri commands only** in P11. `agentd` does not read this file.

## Tauri lifecycle

| Event | Behavior |
|-------|----------|
| App launch | `ui start` → `daemon start` (if not healthy) → poll `/health` → open main webview |
| Tray Stop daemon | `daemon stop` (managed) |
| App quit | Stop managed `ui` + `daemon` (configurable; default stop both) |

## Non-goals (P11)

- iOS app, remote gateway / reverse tunnel, pairing API, `GET /events` SSE
- New harness/agent features or web UI redesign
- Code signing / notarization (document only)
- Replacing `scripts/start-local.sh` (keep for CLI dev)

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Desktop app opens web UI against local static server | Manual macOS smoke |
| Tray reflects daemon health | Manual |
| Start/stop daemon from tray updates `/health` | Manual |
| `desktop-daemon.sh status` emits valid JSON | `tests/test_desktop_scripts.py` |
| `desktop.toml` round-trip via Tauri settings API | Rust/unit or integration test |
| Python CI unchanged (pytest + ruff) | GitHub Actions |
| macOS `tauri build` produces `.app` | Manual or optional workflow |

## P12 touchpoints (reserved)

- `remote.gateway_url`, `remote.token`, pairing fields in `desktop.toml`
- `remote.event_stream_url` → future `GET /events` on daemon or gateway
- Connection mode switch: local API vs remote gateway

Implementation plan: `docs/superpowers/plans/2026-06-07-p11-desktop-app-shell.md`
