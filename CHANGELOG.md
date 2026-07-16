# Changelog

## Unreleased — 2026-07-17

### Local Agent Environment Manager

- Added one built-in adapter model for Claude, Codex, Cursor, Hermes,
  OpenClaw, OpenCode, and Qwen. Each environment reports CLI, config,
  capability, runtime, Desktop, and IDE evidence independently.
- Added durable Verified Changes for MCP, catalog, agentic-os config,
  harness config, profile, and registry writes: non-mutating preview, stale
  rejection, post-apply verification, protected backup, and verified rollback.
- Replaced the fragmented top-level Desktop navigation with Home,
  Environments, Sessions, Capabilities, Changes, and Settings while preserving
  the mature editors as reachable subviews.

### Desktop and release hardening

- Unified local and remote WebView HTTP transport in Rust, restored
  authenticated remote event polling without exposing Keychain bearer tokens
  to JavaScript, and added immediate startup-failure state.
- Added Environment Manager, Change Center, attention routing, Settings owner
  links, keyboard skip/focus behavior, reduced motion, and responsive
  master-detail layouts down to the 960px minimum window width.
- Fixed packaged Python staging to copy the uv-managed standalone runtime
  instead of the project venv. Package tests now reject missing `libpython`,
  absolute runtime symlinks, repo path leaks, and false relocation checks.
- `pnpm desktop:build` now produces the documented `.app` without invoking the
  GUI-dependent DMG helper. Tauri applies an ad-hoc `-` signature so the local
  bundle has a valid resource seal.

### Verification

- 869 Python tests, Ruff, all Web JavaScript syntax checks, and 32 Rust tests
  pass. A nondeterministic Rust test race on process-global bundle environment
  state was reproduced and serialized.
- Product smoke passes 11 behavior steps, including seven adapters, six
  environment surfaces, verified Change round-trip, sessions, and approvals.
  Packaged remote transport passes the live Caddy internal-TLS smoke and token
  revoke check.
- The arm64 `.app` passed bundled-Python execution and strict deep codesign
  verification, two clean tray Quit cycles, crash-orphan termination, and
  relaunch recovery. Developer ID signing, notarization, DMG publication, and
  updater delivery remain external release work.

## v1.0.1 — 2026-06-12

Hardening release driven by an external code review (codex).

- **CI portability**: the macOS-only bundle staging test skips on
  non-darwin runners and the script guards `uname` — main is green
  again.
- **`/sessions/discover` is now actually workspace-scoped**: sessions
  must carry a resolvable `cwd` matching the requested workspace;
  unscopable files are excluded.
- **`/sessions/bind` validates caller paths**: the workspace must
  exist and the log must be a real `.jsonl` under the agent's
  configured log roots (bound sessions feed the logs API those paths
  verbatim).
- **MCP alignment rejects dotted server names**: PatchEngine paths
  split on `.`, so `copy`/`remove` now refuse names that would write a
  nested config shape.
- Desktop crash-orphan watchdog (`--parent-watch-pid`) and explanatory
  empty states for managed-run tabs (landed post-v1.0.0, first
  packaged here).


## v1.0.0 — 2026-06-12

First release. agentic-os is a local **Harness Manager**: the management
layer underneath vibe coding tools (Claude Code, Codex, Cursor, Gemini,
Qwen, OpenCode) and agentic runtimes (OpenClaw, Hermes, n8n). Everything
runs in a single local daemon (`agentd`) with a static web UI, a CLI
(`agentctl`), and a macOS desktop app.

### Observe-first operator surfaces

- **Live Session Radar** (P39): the 總覽 landing view lists your real
  Claude Code / Codex sessions scanned from `~/.claude/projects` and
  `~/.codex/sessions` — active indicator, workspace, first prompt,
  copy-resume command, open-in-Terminal (macOS).
- **Transcript preview** (P41): click any session to read its latest
  conversation inline (tail-bounded, path-validated).
- **Capability Radar** (P40): real skills / MCP servers / plugins /
  memory files per tool, names only — secret values never leave the
  reader module.
- **Agentic inventory** (P37): read-only OpenClaw / Hermes / n8n
  capability listing.
- **Tool discovery** (P34): installed tools, versions, non-secret config
  summaries.

### Safe write path

- **MCP Alignment** (P42): cross-tool MCP server matrix with drift
  highlighting; copy a server between tools or remove one through the
  safe-edit engine — dry-run by default, schema-validated, atomic write,
  backup snapshot, audit trail, one-command rollback. Definition values
  (commands, env, URLs) move file-to-file inside the daemon and never
  appear in API responses or the UI.
- **Safe native config editing** (P10): dry-run / backup / rollback
  patch engine with per-harness schema whitelists.

### Run management & governance

- Harness run lifecycle: launch, stop (process-group), retry, JSONL
  logs, evidence bundles (P0, P35).
- Two-stage launch policy gate with audit-linked deny/approval records
  (P3.5/P3.6), approval workbench (P7), governance audit & deprecation
  lifecycle (P6/P9), fleet health & capacity (P5).
- Deterministic session memory pipeline — summarize → review → approve,
  no LLM calls (P1).
- Workspaces, run templates, provider/model switchboard, daily operator
  dashboard (P29–P33), session discover/bind/attach (P36).
- Remote operator console with localhost-only admin and affordance-gated
  writes (P12–P15, P25); portable setup export/import (P26).

### Desktop app (macOS)

- Tauri shell with tray, embedded UI, and an auto-connect supervisor:
  the daemon starts on app launch, health-ticks every 5s, restarts with
  backoff, and surfaces connection state in the UI gate.
- v1.0.0 fixes the Finder/Dock launch failure: GUI PATH lacked Homebrew
  dirs, so the dev-mode daemon could never start (`ensure_path_dirs` now
  guarantees `/opt/homebrew/bin` and `/usr/local/bin`).

### Verification

782 Python tests + 24 Rust tests; every feature verified against real
local data (real session stores, real tool configs) before release.
