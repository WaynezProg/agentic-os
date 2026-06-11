# 060 — P40 Capability Radar

Status: implemented (branch `feat/p34-p38-dual-track-product`)
Design: `docs/superpowers/specs/2026-06-12-capability-radar-design.md`

## Problem

Skill/MCP/plugin/memory management surfaces only knew the daemon's own
catalog (P3 control plane), which stays empty. Real capabilities live in
each tool's own config locations and were invisible to the operator.

## Owns

- `src/agentic_os/capability_inventory.py`: read-only readers per tool —
  claude (`~/.claude/skills`, `~/.claude.json` mcpServers, `~/.claude/plugins/cache`,
  `~/.claude/CLAUDE.md`), codex (`~/.codex/config.toml` mcp_servers via tomllib,
  `~/.codex/prompts`, `~/.codex/AGENTS.md`), gemini (`~/.gemini/settings.json`,
  `extensions`, `GEMINI.md`), qwen (`~/.qwen/skills`, `settings.json`, `QWEN.md`),
  opencode (`~/.config/opencode/{skills,plugins,opencode.json,AGENTS.md}`),
  cursor (`~/.cursor/mcp.json`).
- `GET /tools/capabilities` (home injectable via `create_app(capability_home=…)`).
- `agentctl tools capabilities`.
- 工具 tab "Capabilities（真實設定）" card grid: count + name chips per
  category, memory file metadata (path, size, mtime).

## Invariants

- **Names only.** Commands, env values, and URLs never leave the module —
  test-asserted end-to-end (fixture plants fake secrets, asserts absence).
- Configs parsed with json/tomllib, never regex.
- Per-file read guard `_MAX_CONFIG_BYTES` (20MB); oversized → `error` field.
- One broken tool config cannot break the inventory (per-tool error isolation).
- Memory files: declared path reported, symlink target measured (codex
  `AGENTS.md` → shared instructions file).

## Does not own

- Writing/installing/enabling any capability in external tools.
- MCP server contents (command/env/url display).
- Memory file content reading or diffing — metadata only.
- OpenClaw/Hermes/n8n (P37 agentic inventory owns those).
