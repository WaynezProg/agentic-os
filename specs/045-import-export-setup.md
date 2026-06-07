# 045 — Project Agent Setup Import / Export (P26)

Status: Complete
Date: 2026-06-07
Depends on: profiles (`specs/025-run-project-profile.md`), catalog (`specs/012-workflow-surface-catalog.md`), skills/MCP/policy (`specs/004-skills-mcp-policy.md`), registry (`specs/039-registry-editor-backend.md`)
Blocks: —

## Positioning

Export a project's agent setup — profiles, policies, MCP servers, skills, commands,
hooks — as a portable bundle, and import it elsewhere with a **dry-run** first. Makes a
configured setup reproducible across machines.

## Scope

| Owns | Does not own |
|------|--------------|
| Export bundle of profiles/policies/MCP/skills/commands/hooks | Package management / dependency install |
| Import **dry-run** (diff vs current) then apply through existing gates | Bypassing patch/policy validation |
| Secret references by env-var name only | Storing/transferring secret values |

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Export round-trips back to an equivalent setup on import | `tests/test_*import_export*` (new) |
| Import dry-run shows a diff before any write | unit |
| Exported bundle contains zero secret values | redaction assertion |
| Import applies through patch/validation/policy paths, not raw writes | code review |

## Conflicts & resolutions

- **Secret leakage (#1 risk)** — an export that captures live config can serialize secret values.
  **→ Resolution**: the exporter runs every record through `_redact_value` and the bundle schema has
  **no value fields** for secrets — only env-var names. Import resolves names against the target
  machine's env and **fails loudly** on any missing name; it never accepts or prompts for plaintext.
- **Gate bypass** — a bulk raw write would skip validation, policy, and audit. **→ Resolution**:
  import is a driver over the existing per-domain endpoints (catalog patch, config patch, profile
  patch, skill/mcp/policy upsert+rollback), so every imported change gets its own `patch_id`,
  validation, and audit event — and the whole import is rollback-able item by item.
- **Path portability** — absolute `cwd_roots`/`log_paths`/bindings don't transfer. **→ Resolution**:
  export tokenizes paths (`${PROJECT_ROOT}`, `${HOME}`); import remaps them and lists any unresolved
  absolute path in the dry-run diff for the operator to fix before apply.
