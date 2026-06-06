# 029 — Packaged macOS App (P11.5)

Status: Planned
Date: 2026-06-07
Depends on: P11 (`specs/028-desktop-app-shell.md`)
Blocks: P12 (`specs/030-remote-access-adapter.md`)

## Positioning

Close the P11 **dev shell → production bundle** gap. P11.5 adds **no product features** — only
bundled resources, path resolution, build pipeline, and lifecycle convergence for macOS `.app`.

| Owns | Does not own |
|------|--------------|
| Bundled `agentic-os/` resources inside `.app` | remote gateway, pairing, token auth, event stream (P12) |
| `prepare-desktop-bundle.sh` + Tauri `bundle.resources` | Code signing, notarization, auto-update |
| Release `bundle_root()` / `AGENTIC_OS_BUNDLE_ROOT` | New web UI features, harness runtime changes |
| Quit / crash / relaunch listener convergence | Windows/Linux bundle validation |

## Components

- `scripts/prepare-desktop-bundle.sh` — stage web, scripts, registry, venv for Tauri bundle
- `apps/desktop/src-tauri/bundle-resources/agentic-os/` — generated staging (gitignored)
- Updated `desktop-*.sh` — bundle-aware paths for agentd and static UI
- `apps/desktop/src-tauri/src/daemon.rs` — `runtime_root()` for dev vs release

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Build does not start daemon/UI | Inspect `beforeBuildCommand`; no listeners after build |
| Bundled `.app` opens web UI | Manual `pnpm desktop:build` + open `.app` |
| Tray start/stop daemon | Manual tray smoke |
| Tray Quit leaves no listeners on 8767/5173 | `lsof` after Quit |
| Relaunch after Quit is clean | Manual second open |
| `pnpm desktop:dev` unchanged | P11 dev smoke regression |
| Script tests with bundle fixture | `tests/test_desktop_scripts.py` |
| Bundle layout test | `tests/test_desktop_bundle.py` |
| Python CI unchanged | `uv run pytest -q && uv run ruff check .` |

## P12 boundary

P12 adds **remote connection** only via the Remote Access Adapter: remote gateway / reverse
tunnel, pairing flow, token handling, revoke, event stream client. Tunnel product is not specified.
P11.5 keeps `desktop.toml` `[remote]` placeholders; no wire-up.

## Design

`docs/superpowers/specs/2026-06-07-p11.5-packaged-macos-app-design.md`
