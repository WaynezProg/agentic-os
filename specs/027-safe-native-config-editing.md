# 027 — Safe Native Config Editing (P10)

Status: Implemented
Date: 2026-06-06
Depends on: 013 (configuration scope mapper), 020 (harness config bridge), 014 (workflow surface catalog)
Blocks: P11 (Tauri Desktop App), P12 (iOS Remote Companion)

## Positioning

`agentic-os` reads harness-native config (020), agentic-os config (013), and workflow
surfaces (014/019) but, before P10, did not write any of them. P10 adds a **Safe Edit
Engine**: dry-run patch, schema validation, hybrid backup, rollback, and audit for all
three write targets.

| Sub-phase | Target | Primary API |
|-----------|--------|-------------|
| P10a | Workflow surfaces (semantic ops) | `POST /catalog/{harness}/surfaces/.../patch` |
| P10b | Harness-native config (path merge) | `POST /harness-config/{harness_id}/patch` |
| P10c | Agentic-os config (path merge) | `POST /config/{harness_id}/patch` |

Architecture: **Unified Patch Engine** — one pipeline (`resolve → load → apply → validate →
backup → commit → audit`) with a thin semantic-op compiler for surfaces and per-harness path
resolvers. All writes are immediate with audit; P7 launch-policy approval is not involved.

Daemon remains the only writer. CLI and UI never touch harness config paths directly.

## Modules

| Module | Responsibility |
|--------|----------------|
| `safe_edit.py` | `PatchTarget`, `PatchOp`, `PatchResult`, pipeline entry `apply_patch()` |
| `patch_engine.py` | In-memory `merge` / `remove` ops; preserve unknown top-level keys |
| `schema_registry.py` | Load bundled schemas; validate ops + post-merge document |
| `surface_ops.py` | Semantic op → `PatchOp[]` compiler per harness × surface type |
| `backup_store.py` | Create backups, index in `index.jsonl`, restore for rollback |
| `toml_io.py` | `atomic_write_toml()` mirroring `jsonio.atomic_write_json` |

Extensions: `harness_config.py` (`resolve_write_paths`), `config_scope.py`
(`resolve_write_path`), `catalog.py` (`resolve_surface_path`), `api.py`, `cli.py`,
`client.py`.

## API

### Surface patch (P10a)

```
POST /catalog/{harness}/surfaces/{surface_id}/patch?cwd=<path>&dry_run=1
POST /catalog/{harness}/surfaces/patch?cwd=<path>&dry_run=1
Body: { "ops": [...], "source": "cli|ui|ios", "base_mtime": <optional> }
```

### Harness config patch (P10b)

```
POST /harness-config/{harness_id}/patch?cwd=<path>&scope=user|project|local&dry_run=1&file=<optional>
Body: { "ops": [...], "source": "cli" }
```

### Agentic-os config patch (P10c)

```
POST /config/{harness_id}/patch?cwd=<path>&scope=user|project|local&dry_run=1
Body: { "ops": [...], "source": "cli" }
```

### Rollback and history

```
GET  /patches?harness=<id>&cwd=<path>&limit=50
GET  /patches/{patch_id}
POST /patches/{patch_id}/rollback
```

Success response includes `patch_id`, `applied`, `diff`, `backup`, `audit_event_id`.
Dry-run (`?dry_run=1`) executes resolve → load → apply → validate only; no disk writes.

Audit events use `domain=config_patch`, `event_type=config_patch_applied|config_patch_failed|config_patch_rolled_back`.

## CLI

```bash
agentctl catalog patch <harness> --cwd . [--dry-run] --op '<json>'
agentctl catalog patch <harness> --cwd . --file ops.json
agentctl harness-config patch <harness> --scope project --cwd . --file ops.json
agentctl config patch <harness> --scope user --cwd . --file ops.json
agentctl patches list [--harness <id>] [--cwd .]
agentctl patches show <patch_id>
agentctl patches rollback <patch_id>
```

## Backup and rollback

| Target type | Backup location | Rollback |
|-------------|-----------------|----------|
| Structured JSON/TOML | `.agentic-os/patches/<patch_id>/before/<relative_path>` | Copy snapshot over target |
| Standalone surface files (P10a.1) | `<original>.bak.<ISO8601>` adjacent to file | Copy sidecar back |

Index: `.agentic-os/patches/index.jsonl` (append-only). Rollback of patch A creates patch B
with `rollback_of: p_A`. Re-rollback → HTTP 409.

## Does not own

- Harness-internal planning, tool execution, or MCP server lifecycle
- P7 approval queue for config writes (audit + rollback only)
- Cloud sync or multi-user RBAC
- Full-fidelity JSON Schema for every harness config field (registry grows incrementally)
- UI editor forms (static UI dry-run display optional, not required)
- Remote Gateway, Pairing API, or SSE event stream (P11/P12)
- Tauri Desktop App (P11) or iOS Remote Companion (P12)

## Acceptance criteria

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
| TOML round-trip (codex) preserves comments where possible | unit test (comments may drop — documented limitation) |
| `harness-config effective` reflects patch | integration test |

### P10c — Agentic-os config patch

**Delivers**: `POST /config/{id}/patch` for 013 scopes.

| Criterion | Verification |
|-----------|--------------|
| Patch `~/.agentic-os/config.toml` | integration test |
| `config effective` reflects patch | integration test |

## Implementation plan

`docs/superpowers/plans/2026-06-06-p10-safe-native-config-editing.md`

Design: `docs/superpowers/specs/2026-06-06-p10-safe-native-config-editing-design.md`
