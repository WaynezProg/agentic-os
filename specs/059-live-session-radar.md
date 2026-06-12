# 059 — P39 Live Session Radar

Status: implemented (branch `feat/p34-p38-dual-track-product`)
Design: `docs/superpowers/specs/2026-06-12-live-session-radar-design.md`
Plan: `docs/superpowers/plans/2026-06-12-live-session-radar.md`

## Problem

Every operator surface read only the daemon's own sessions DB, which stays
empty because real vibe coding happens in terminals / Cursor / Codex Desktop.
The dashboard was structurally guaranteed to show "No sessions yet". P39 flips
the data source from "what the manager launched" to "what the real tools wrote".

## Owns

- `src/agentic_os/live_sessions.py`: read-only scanners over real session
  stores — Claude Code (`~/.claude/projects/<encoded-cwd>/<id>.jsonl`) and
  Codex (`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`).
- `GET /sessions/live?within_hours=&limit=`: merged, newest-first list with
  per-tool error isolation. Read-only; no policy gate (same class as
  `/tools/discovery`, `/agentic/inventory`). Registered before
  `/sessions/{session_id}` so `live` is not captured as a session id.
- `POST /sessions/live/open-terminal` (macOS only): opens Terminal.app at the
  session workspace running the resume command. The shell command is rebuilt
  server-side from a tool whitelist + validated session id + existing-directory
  check; clients never submit raw commands. Non-darwin returns 501.
- `agentctl sessions live`: CLI table of discovered sessions.
- Dashboard v2 left column "Live Sessions" card: active/idle dot, tool badge,
  workspace, title, relative time, copy-resume and Terminal actions. Own-DB
  card renamed "Managed Runs".

## Contract

`LiveSession` fields: `tool` (`claude|codex`), `session_id`, `workspace`,
`title` (first real prompt or summary, ≤120 chars), `started_at`,
`last_activity_at` (file mtime, ISO8601 UTC), `active` (mtime within 300s),
`source` (codex originator), `log_path`, `resume_command`
(`cd <ws> && claude --resume <id>` / `cd <ws> && codex resume <id>`,
shell-quoted).

Response envelope: `{"sessions": [...], "errors": [{"tool", "error"}],
"generated_at"}`. `within_hours` clamps to [1, 720], `limit` to [1, 200].

## Bounded IO requirements

- stat/mtime pruning before any file open; files older than the window are
  never read.
- At most 64KB read per file (head only); a truncated trailing line is dropped.
- Claude `agent-*.jsonl` sidechain transcripts and session subdirectories
  (`<id>/subagents/`) are excluded — only top-level `*.jsonl` files are
  resumable sessions.
- A scanner exception must not break the endpoint: per-tool try/except reports
  into `errors`.

## Does not own

- Writing to, launching, or modifying external session stores.
- Gemini / Qwen / OpenCode / OpenClaw / Hermes scanners (extension point:
  `_SCANNERS` dict).
- Filesystem watching or push updates — pull on load + manual refresh.
- Cross-machine aggregation.
