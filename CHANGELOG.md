# Changelog

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
