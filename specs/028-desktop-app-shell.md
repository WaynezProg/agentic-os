# 028 — Desktop App Shell (P11)

Status: Implemented
Date: 2026-06-07
Depends on: P10 (`specs/027-safe-native-config-editing.md`), P2 (`specs/003-thin-ui.md`)
Blocks: P12 (iOS Remote Companion)

## Positioning

Tauri desktop shell wrapping `apps/web/` and managing local `agentd` + static UI server lifecycle.
Desktop is a **client only** — no harness runtime, no new agent features.

| Owns | Does not own |
|------|--------------|
| Tauri app, tray, daemon/ui lifecycle scripts | iOS, frp, pairing backend, SSE |
| `~/.agentic-os/desktop.toml` via Tauri commands | Remote connection logic (P12) |
| Embedded UI on `localhost:5173` | Web UI redesign, build pipeline for `apps/web` |

## Components

- `scripts/desktop-daemon.sh` — agentd on `127.0.0.1:8767`
- `scripts/desktop-ui.sh` — static server for `apps/web` on `127.0.0.1:5173`
- `apps/desktop/` — Tauri 2 app (`pnpm desktop:dev` / `desktop:build`)
- `apps/web/desktop-settings.html` — settings placeholder UI

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| `desktop-daemon.sh status` valid JSON | `tests/test_desktop_scripts.py` |
| `desktop-ui.sh status` valid JSON | `tests/test_desktop_scripts.py` |
| Tauri settings round-trip defaults | `cargo test` in `apps/desktop/src-tauri` |
| Python CI unchanged | `uv run pytest -q && uv run ruff check .` |
| macOS app opens web UI | Manual `pnpm desktop:dev` |
| Tray start/stop daemon | Manual |
| Windows/Linux | Documented untested |

## Design

`docs/superpowers/specs/2026-06-07-p11-desktop-app-shell-design.md`
