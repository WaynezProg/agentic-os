# 041 — MCP / Skill / Policy Rollback Backend (P22)

Status: Implemented
Date: 2026-06-07
Depends on: skills/MCP/policy catalog (`specs/004-skills-mcp-policy.md`), deprecation lifecycle (`specs/011-deprecation-lifecycle.md`)
Blocks: P23 (`specs/042-mcp-skill-policy-ui.md`)

## Positioning

`control_plane.py` exposes only `upsert_* / disable_* / deprecate_* / undeprecate_*`
for skills, MCP servers, and policies. There is **no history, no rollback, no backup**.
A "safe management UI" cannot be built on a mutation surface with no undo — so the
backend must come first. This is the load-bearing gap that blocks P23.

## The mechanism question (resolved)

Skills/MCP/policy live in **SQLite**, not files; the file-based `safe_edit_engine` does
not apply directly. The risk is two divergent rollback systems with two UIs.

**→ Resolution — one contract, DB-native impl.** Add DB-row versioning that emits the
**same envelope** the file engine already returns, so `ui/rollback.js` is identical
across all domains:

- mutation result includes `patch_id`, `applied`, `diff`, `audit_event_id`
- `GET /{skills|mcp|policy}/{id}/history`
- `POST /{skills|mcp|policy}/{id}/rollback?to=<patch_id|version>`

Preferred implementation: **reuse `BackupStore`** by snapshotting the prior record as
JSON under `patches/<patch_id>/before` and registering a restore callback that re-applies
it via the existing `upsert_*`. That lets `POST /patches/{id}/rollback` cover these domains
too, collapsing toward a single rollback entry point even though storage is a DB row.

## Scope

| Owns | Does not own |
|------|--------------|
| Versioned history + rollback for skills, MCP, policy records | UI (P23) |
| Snapshot-on-mutate wired into existing `upsert_*`/`disable_*`/`deprecate_*` | Starting MCP servers / live tool enforcement |
| Preserve secret redaction inside every snapshot | File-based engine reuse for the row data itself |

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Every mutation records a prior-version snapshot | `tests/test_control_plane.py` |
| Rollback restores a prior version exactly | unit |
| Snapshots never store secret values (redaction holds) | redaction assertion |
| Policy rollback re-takes effect on the policy gate immediately | `tests/test_policy_aware_run.py` |

## Conflicts & resolutions

- **Two rollback mechanisms** — **→ Resolved above**: same envelope + (preferably) same
  `BackupStore`/`/patches` entry point; only the restore callback differs (re-upsert vs file
  restore). UIs never branch on domain.
- **Policy gate coupling** — policy is read by the two-stage gate (P3.5/P3.6); a rollback changes
  enforcement instantly. **→ Resolution**: treat policy rollback as an ordinary policy change — it
  emits an audit event and the gate re-reads on the next evaluation; no special bypass path, and the
  audit trail records who rolled back what.
- **Redaction** — **→ Resolution**: snapshot the already-redacted record (env-var names only) using
  `_redact_value` at snapshot time, identical to display redaction; secret values never enter history.
