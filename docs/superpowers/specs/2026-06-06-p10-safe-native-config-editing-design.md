# P10 — Safe Native Config Editing Design

Date: 2026-06-06
Status: Implemented
Author: agentic-os team
Builds on: `specs/013-configuration-scope-mapper.md`, `specs/020-harness-config-bridge.md`,
`specs/014-workflow-surface-catalog.md`, `docs/superpowers/specs/2026-05-30-harness-manager-extension-design.md`
Blocks: P11 Tauri Desktop App, P12 iOS Remote Companion

## Summary

`agentic-os` today reads harness-native config (020), agentic-os config (013), and workflow
surfaces (014/019) but explicitly does not write any of them. Without a safe write layer, the
static UI and future Desktop App remain dashboards only.

P10 adds a **Safe Edit Engine**: dry-run patch, schema validation, hybrid backup, rollback, and
audit for all three write targets — delivered in three sub-phases:

| Sub-phase | Target | Primary API |
|-----------|--------|-------------|
| P10a | Workflow surfaces (semantic ops) | `POST /catalog/{harness}/surfaces/.../patch` |
| P10b | Harness-native config (path merge) | `POST /harness-config/{harness_id}/patch` |
| P10c | Agentic-os config (path merge) | `POST /config/{harness_id}/patch` |

Architecture choice: **Unified Patch Engine** — one pipeline (`resolve → load → apply → validate →
backup → commit → audit`) with a thin semantic-op compiler for surfaces and per-harness path
resolvers. All writes are immediate with audit; P7 launch-policy approval is not involved.

## Product Context

Long-term product goal: a macOS desktop console (P11) and iOS remote companion (P12) that manage
local coding/agent tools (Claude Code, Codex, Cursor Agent, OpenCode, OpenClaw, Hermes, Qwen).

Core capabilities across the product line:

- Start, stop, retry, attach, logs, session timeline (existing P0–P9 substrate).
- Run profiles, provider, model, quota (024–026).
- **Safe editing of local agent config** — hooks, MCP, skills, commands, subagents (P10).

Architecture boundary (unchanged):

- macOS `agentd` is the sole process and file owner.
- Desktop App and iOS are HTTP clients only; iOS reaches Mac via frp + token/HMAC gateway (P12).

P10 is API/CLI-first. No Tauri shell, no iOS app, no SSE/WebSocket in this phase (reserved for P11).

## Non-goals

- No harness-internal planning, tool execution, or MCP server lifecycle.
- No P7 approval queue for config writes (audit + rollback only).
- No cloud sync or multi-user RBAC.
- No full-fidelity JSON Schema for every harness config field in P10a (registry grows incrementally).
- No UI editor forms (static UI may add dry-run display later; not required for P10 acceptance).
- No Remote Gateway, Pairing API, or SSE event stream (P11/P12).

## Architecture

```
CLI / Desktop (P11) / iOS (P12)
        │ HTTP
        ▼
   api.py  ──►  surface_ops.py     (semantic ops: enable_mcp_server, upsert_hook, …)
                      │ compile to PatchOp[]
                      ▼
                 safe_edit.py       (orchestration)
                   ├─ patch_engine.py    (path-directed deep merge)
                   ├─ schema_registry.py (versioned JSON Schema per harness/kind)
                   ├─ backup_store.py    (hybrid snapshot + sidecar index)
                   └─ audit.py           (domain=config_patch)
                      │
                      ▼
         harness_config paths │ catalog paths │ config_scope paths
```

### New modules (`src/agentic_os/`)

| Module | Responsibility |
|--------|----------------|
| `safe_edit.py` | `PatchTarget`, `PatchOp`, `PatchResult`, pipeline entry `apply_patch()` |
| `patch_engine.py` | In-memory `merge` / `remove` ops; preserve unknown top-level keys |
| `schema_registry.py` | Load bundled schemas; validate ops + post-merge document |
| `surface_ops.py` | Semantic op → `PatchOp[]` compiler per harness × surface type |
| `backup_store.py` | Create backups, index in `index.jsonl`, restore for rollback |
| `toml_io.py` | `atomic_write_toml()` mirroring `jsonio.atomic_write_json` |

### Extensions to existing modules

| Module | Change |
|--------|--------|
| `harness_config.py` | Add `resolve_write_paths()` — write path resolution only, no read/write logic |
| `config_scope.py` | Add `resolve_write_path(scope, cwd)` for P10c |
| `catalog.py` | Add `resolve_surface_path(surface_id, cwd)` for P10a |
| `api.py` | Patch + rollback routes |
| `cli.py` | `catalog patch`, `harness-config patch`, `config patch`, `patches` commands |
| `client.py` | Mirror new endpoints |
| `audit.py` | No schema change; new `domain=config_patch` events |

**Invariant**: daemon remains the only writer. No CLI or UI direct filesystem access to harness
config paths.

## Patch Pipeline

Every write (including rollback) runs the same six steps:

1. **Resolve** — `PatchTarget` → `(file_path, format, scope, harness_id, target_kind)`
2. **Load** — read current content; missing file → empty `dict` (create-on-write allowed)
3. **Apply (in-memory)** — `PatchEngine.apply(doc, ops)`
4. **Validate** — `SchemaRegistry.validate(harness, kind, doc)`; failure → HTTP 422, zero disk writes
5. **Backup** — hybrid strategy (see Backup section)
6. **Commit + Audit** — atomic write + `AuditStore.record(domain="config_patch", ...)`

### Dry-run

`?dry_run=1` (or `--dry-run` on CLI) executes steps 1–4 only. Response includes:

```json
{
  "patch_id": "p_preview_...",
  "applied": false,
  "diff": {"added": {}, "modified": {}, "removed": {}},
  "validation": {"ok": true, "errors": []},
  "would_backup": {"kind": "snapshot|sidecar", "path": "..."}
}
```

### PatchOp format (core — path-directed merge)

```json
{"op": "merge", "path": "mcpServers.my-server", "value": {"command": "npx", "args": ["-y", "mcp"]}}
{"op": "remove", "path": "hooks.PreToolUse[0]"}
```

Rules:

- `merge` deep-merges `value` at `path`; creates intermediate objects as needed.
- `remove` deletes the key or array index at `path`.
- Paths use dot notation; array indices as `[n]`.
- Only paths in the per-harness **write whitelist** are permitted; others → HTTP 403.
- Unknown keys outside the merge path are never deleted or overwritten.

### Semantic ops (surface layer)

High-level ops compile to `PatchOp[]` before entering the pipeline:

```json
{"op": "enable_mcp_server", "name": "github", "config": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}, "scope": "project"}
{"op": "upsert_hook", "event": "PreToolUse", "matcher": "Bash", "command": "echo check"}
{"op": "disable_mcp_server", "name": "github", "scope": "project"}
```

`surface_ops.py` owns the per-harness mapping table. Adding a new semantic op does not change the
core pipeline.

## P10a — Surface MVP matrix

All seven harnesses get MCP server semantic ops in P10a. Claude and Cursor additionally get hook
ops. Skills and slash commands are deferred to **P10a.1** (same pipeline, new semantic ops).

| harness | surface 1 | surface 2 | config file |
|---------|-----------|-----------|-------------|
| claude | `mcp_server` | `hook` | `.claude/settings.json` |
| cursor | `mcp_server` | `hook` | `.cursor/mcp.json`, `.cursor/hooks.json` |
| codex | `mcp_server` | — | `.codex/config.toml` |
| opencode | `mcp_server` | — | `.opencode/config.json` or `~/.config/opencode/config.json` |
| qwen | `mcp_server` | — | `.qwen/settings.json` |
| openclaw | `mcp_server` | — | `.openclaw/config.toml` |
| hermes | `mcp_server` | — | `.hermes/config.toml` |

Path resolution reuses `catalog.py` scope layout and `harness_config.py` file naming. TOML harnesses
round-trip through `tomllib` load → dict patch → `tomli-w` write.

## API Contract

### Surface patch (P10a)

```
POST /catalog/{harness}/surfaces/{surface_id}/patch
  ?cwd=<path>&dry_run=1
Body: { "ops": [...], "source": "cli|ui|ios" }

POST /catalog/{harness}/surfaces/patch
  ?cwd=<path>&dry_run=1
Body: { "ops": [...], "source": "cli" }
```

`surface_id` format matches catalog: `mcp_server:<name>@<scope>`, `hook:<event>@<scope>`, etc.

### Harness config patch (P10b)

```
POST /harness-config/{harness_id}/patch
  ?cwd=<path>&scope=user|project|local&dry_run=1
Body: { "ops": [...], "source": "cli" }
```

For Cursor multi-file scopes, `file` query param selects `cli-config.json`, `mcp.json`, or
`hooks.json` (default: primary config file for harness).

### Agentic-os config patch (P10c)

```
POST /config/{harness_id}/patch
  ?cwd=<path>&scope=user|project|local&dry_run=1
Body: { "ops": [...], "source": "cli" }
```

Note: `harness_id` here is the config namespace key used by 013 routes (not a filter on harness
native files). Scope maps to `~/.agentic-os/`, `<cwd>/.agentic-os/`, `<cwd>/.agentic-os.local/`.

### Rollback and history

```
GET  /patches?harness=<id>&cwd=<path>&limit=50
GET  /patches/{patch_id}
POST /patches/{patch_id}/rollback
```

Rollback restores from snapshot or sidecar, writes `config_patch_rolled_back` audit event, returns
new `patch_id` for the rollback operation itself.

### Success response shape

```json
{
  "patch_id": "p_01JABCDEF",
  "applied": true,
  "diff": {"added": {}, "modified": {}, "removed": {}},
  "backup": {"kind": "snapshot|sidecar", "path": "..."},
  "audit_event_id": 42
}
```

### CLI mirror

```bash
agentctl catalog patch <harness> --cwd . [--dry-run] --op '<json>'
agentctl catalog patch <harness> --cwd . --file ops.json
agentctl harness-config patch <harness> --scope project --cwd . --file ops.json
agentctl config patch <harness> --scope user --cwd . --file ops.json
agentctl patches list [--harness <id>] [--cwd .]
agentctl patches show <patch_id>
agentctl patches rollback <patch_id>
```

## Backup and Rollback

Hybrid strategy (locked decision):

| Target type | Backup location | Rollback |
|-------------|-----------------|----------|
| Structured JSON/TOML (config files) | `.agentic-os/patches/<patch_id>/before/<relative_path>` | Copy snapshot over target |
| Standalone surface files (future P10a.1: `SKILL.md`, commands) | `<original>.bak.<ISO8601>` adjacent to file | Copy sidecar back |

**Index**: `.agentic-os/patches/index.jsonl` — append-only, one JSON object per line:

```json
{
  "patch_id": "p_01J...",
  "harness_id": "claude",
  "cwd": "/Users/me/project",
  "target_kind": "surface",
  "surface_id": "mcp_server:github@project",
  "backup_kind": "snapshot",
  "backup_paths": [".agentic-os/patches/p_01J.../before/.claude/settings.json"],
  "source": "cli",
  "created_at": "2026-06-06T12:00:00Z",
  "rolled_back_at": null,
  "rollback_of": null
}
```

Rollback of patch A creates patch B with `"rollback_of": "p_A"`. Patch A's index entry gets
`rolled_back_at` set. Re-rollback is idempotent: second rollback of same patch → 409.

## Audit

All writes record `AuditStore` events:

| Field | Value |
|-------|-------|
| `domain` | `config_patch` |
| `entity_id` | `patch_id` |
| `event_type` | `config_patch_applied` / `config_patch_failed` / `config_patch_rolled_back` |
| `message` | Human-readable summary |
| `metadata` | See below |

Metadata (secrets redacted via existing `_redact_*` patterns):

```json
{
  "patch_id": "p_01J...",
  "harness_id": "claude",
  "scope": "project",
  "cwd": "/Users/me/project",
  "target_kind": "surface|harness_config|agentic_config",
  "surface_id": "mcp_server:github@project",
  "ops": [{"op": "enable_mcp_server", "name": "github", "...": "..."}],
  "before_hash": "sha256:abc...",
  "after_hash": "sha256:def...",
  "backup_path": ".agentic-os/patches/p_01J.../before/...",
  "source": "cli",
  "dry_run": false
}
```

`GET /audit/events?domain=config_patch` works with existing audit API.

## Schema Registry

Bundled schemas under `src/agentic_os/schemas/`:

```
schemas/
  _common/patch_op@v1.json
  claude/mcp_server@v1.json
  claude/hook@v1.json
  cursor/mcp_server@v1.json
  cursor/hook@v1.json
  codex/mcp_server@v1.json
  opencode/mcp_server@v1.json
  qwen/mcp_server@v1.json
  openclaw/mcp_server@v1.json
  hermes/mcp_server@v1.json
  agentic_os/config@v1.json          # P10c
```

Validation layers:

1. **Op structure** — each `PatchOp` / semantic op validated against `_common/patch_op@v1.json`
2. **Post-merge document** — full doc validated against harness/kind schema
3. **Path whitelist** — only registered path prefixes writable per harness × kind

Schema versions are explicit (`@v1`). Non-breaking additions use new optional fields in `@v1`;
breaking changes require `@v2` with registry lookup by version field in request (default: latest).

Future: operator overlay schemas in `.agentic-os/schemas/` (not P10).

## Error Handling

| Condition | HTTP | Behavior |
|-----------|------|----------|
| Schema validation failure | 422 | `validation_errors[]`; no disk write |
| Path not in whitelist | 403 | `forbidden_path` |
| Unknown harness | 400 | Same as existing catalog/config routes |
| Target file mtime changed since dry-run token | 409 | `stale_target`; client must re-dry-run |
| Permission denied / disk full | 500 | Audit `config_patch_failed`; backup cleaned up |
| Rollback: patch not found | 404 | |
| Rollback: already rolled back | 409 | |
| Rollback: backup missing | 500 | `backup_missing`; manual recovery note in message |

**Stale detection**: optional `base_mtime` in request body (from dry-run response). If present and
file mtime differs at commit time → 409.

**Redaction**: API diff responses and audit metadata redact secret patterns. Request bodies may
contain secrets (operator is local trusted user).

## Security

- All routes bind to existing daemon host (`127.0.0.1` default); no new auth in P10.
- P12 Remote Gateway will wrap these endpoints with token/HMAC; P10 designs IDs and audit fields to
  be gateway-compatible (`source: ios`, `remote_device_id` reserved in metadata).
- Write whitelist prevents patching arbitrary filesystem paths.
- No shell execution during patch apply.

## Phase Plan and Acceptance

### P10a — Surfaces (semantic ops)

**Delivers**: `surface_ops.py`, semantic MCP + hook ops for 7 harnesses, catalog patch API/CLI,
backup/rollback/audit for structured config files.

| Criterion | Verification |
|-----------|--------------|
| Dry-run returns diff without writing | API test + CLI test |
| `enable_mcp_server` on claude project scope updates `catalog merged` | integration test |
| Invalid MCP config → 422, file unchanged | unit test |
| Rollback restores pre-patch state | integration test |
| Audit event with `domain=config_patch` | API test |
| 020/014 read routes unchanged | regression test |

### P10a.1 — Skills and commands

**Delivers**: `upsert_skill`, `upsert_command` semantic ops; sidecar backup for `.md` files.

| Criterion | Verification |
|-----------|--------------|
| Upsert `SKILL.md` creates file + sidecar backup | integration test |
| Rollback removes created file or restores previous content | integration test |

### P10b — Harness-native config patch

**Delivers**: `POST /harness-config/{id}/patch` with raw `PatchOp[]`; Cursor multi-file support.

| Criterion | Verification |
|-----------|--------------|
| Path merge preserves unknown keys | unit test with fixture JSON |
| TOML round-trip (codex) preserves comments where possible | unit test (comments may drop — document limitation) |
| `harness-config effective` reflects patch | integration test |

### P10c — Agentic-os config patch

**Delivers**: `POST /config/{id}/patch` for 013 scopes.

| Criterion | Verification |
|-----------|--------------|
| Patch `~/.agentic-os/config.toml` | integration test |
| `config effective` reflects patch | integration test |

## Testing Strategy

| Layer | Coverage |
|-------|----------|
| Unit | `PatchEngine` merge/remove; path parser; TOML round-trip |
| Unit | `surface_ops` compiler per harness × type |
| Unit | `SchemaRegistry` valid/invalid fixtures |
| Unit | `BackupStore` snapshot + sidecar + rollback |
| Integration | Full pipeline in `tmp_path`: dry-run → apply → audit → rollback |
| API | `tests/test_api.py` — happy path, 422, 403, 409 per route |
| CLI | `tests/test_cli.py` — dry-run, apply, list, rollback |
| Regression | Read-only 013/020/catalog tests unaffected |

Dependency: add `tomli-w` to `pyproject.toml` for TOML writes.

## P11 / P12 Touchpoints (reserved, not implemented)

| Interface | Purpose |
|-----------|---------|
| `GET /events` (SSE) | Stream `config_patch` events to Desktop App |
| Remote Gateway | frp tunnel + HMAC token; proxies patch APIs |
| Pairing API | One-time code binds iOS device to Mac daemon |
| Patch API | Unchanged paths; gateway adds auth headers → `source: ios` |

## Risks

| Risk | Mitigation |
|------|------------|
| TOML comment loss on round-trip | Document in spec; accept for P10; investigate `tomlkit` later if needed |
| Harness config shape drift | Versioned schema registry; `@v2` without breaking `@v1` clients |
| Concurrent edits outside agentic-os | `base_mtime` stale detection; operator education |
| Cursor multi-file partial patch | Explicit `file` param; per-file patch_id in index |
| Scope explosion of semantic ops | Compiler table per harness; core pipeline stable |

## Implementation Spec

After this design is approved, create `specs/027-safe-native-config-editing.md` mirroring acceptance
criteria above and update README phase table with P10 row.

Implementation plan path: `docs/superpowers/plans/2026-06-06-p10-safe-native-config-editing.md`
(produced by writing-plans skill).
