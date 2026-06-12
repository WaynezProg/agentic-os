# 062 — P42 MCP Alignment

Status: implemented (branch `feat/p34-p38-dual-track-product`)
Design: `docs/superpowers/specs/2026-06-12-mcp-alignment-design.md`

## Problem

P40 made per-tool MCP servers visible but tools drift, and the operator's
goal is identical behavior across Claude Code / Codex / Gemini / Qwen /
OpenCode / Cursor. Aligning meant hand-editing six differently-shaped
configs. This is the project's first write path into real tool configs.

## Owns

- `src/agentic_os/mcp_alignment.py`:
  - Path table (single source of truth with P40 reads): claude
    `~/.claude.json#mcpServers`, cursor `~/.cursor/mcp.json#mcpServers`,
    gemini/qwen `settings.json#mcpServers`, opencode
    `~/.config/opencode/opencode.json#mcp`, codex
    `~/.codex/config.toml#mcp_servers`.
  - `CanonicalServer` translation adapters (opencode array-command ↔
    command+args, environment ↔ env, enabled flag; remote/url servers;
    extras carried only within the mcpServers-shaped family).
  - `build_copy_patch` / `build_remove_patch` → P10 `PatchTarget` +
    `PatchOp` (`merge`/`remove`), `kind="mcp_server"`.
  - `summarize_def(raw, tool=…)` keys-only summary (routed by tool —
    claude entries can carry `type: "stdio"` legitimately).
  - `target_config_parse_error`: refuse-to-write guard, because
    SafeEditEngine treats unparseable JSON as `{}` and would rewrite the
    file wholesale.
- Schema registry: gemini `mcp_server` schema + whitelist; opencode
  whitelist gains real `mcp` prefix (legacy `mcpServers` kept) and the
  schema models the real shape.
- API: `GET /tools/mcp/matrix`; `POST /tools/mcp/copy` and
  `POST /tools/mcp/remove` (dry-run **default**; 404 unknown source,
  409 already in target, 400 unsupported tool/shape/unparseable target).
  All writes go through `SafeEditEngine` — schema validation, atomic
  write, backup snapshot, audit event, rollback via existing
  `/patches/{id}/rollback`.
- CLI: `agentctl tools mcp-matrix | mcp-copy --server --from --to [--apply]
  | mcp-remove --tool --server [--apply]` — dry-run unless `--apply`.
- UI (工具 tab): alignment matrix (drift rows highlighted), hover cell
  actions, two-step confirm (dry-run summary + backup path +
  active-session warning from the P39 radar) before any write.

## Invariants

- **Server definition values (command/env/url) never leave the daemon.**
  Definitions move file-to-file in-process; API responses and UI carry
  key names only (`summarize_def`), asserted by tests end-to-end.
- Every write is dry-run-first, schema-validated, backed up, audited,
  and rollbackable (verified end-to-end: copy → rollback restores the
  original document exactly).
- Unparseable target config → 400 refuse, file untouched.
- TOML writes via tomli-w round-trip (`tomllib` re-reads asserted);
  comments in TOML are not preserved — backup covers recovery.

## Does not own

- Creating MCP servers from scratch or editing fields (copy/remove only).
- Skills / plugins writes; enable/disable toggles.
- Bulk "sync all" operations; project-scope configs (user scope only).
- openclaw / hermes configs (P37 territory).
