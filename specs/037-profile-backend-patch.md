# 037 — Run Profile Backend: Delete / Diff / Rollback (P18)

Status: Draft
Date: 2026-06-07
Depends on: run/project profile (`specs/025-run-project-profile.md`), safe-edit engine (`specs/027-safe-native-config-editing.md`)
Blocks: P19 (`specs/038-profile-provider-ui.md`)

## Positioning

Run profiles already have **create and edit** via `upsert_run_profile`, plus
`list_profiles`, `show_profile`, `bind_project_profile`, `resolve_profile`. What is
missing for a safe operable UI is **delete, diff, and rollback**. P18 is backend-only
— no UI — so P19 can be pure frontend.

> Correction to the roadmap table: "edit" is *not* missing (upsert covers it). P18 scope
> is delete + diff + rollback + orphan-binding handling.

## Scope

| Owns | Does not own |
|------|--------------|
| `DELETE /profiles/{name}` with orphan-binding handling | Profile UI (P19) |
| Profile diff (scope-to-scope or before/after a patch) | Provider/model semantics changes |
| Rollback/history for the profile TOML bundle | Launch-path profile resolution (frozen, `025`) |

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Delete profile removes it and reports/clears dependent bindings | `tests/test_*profile*` |
| Diff returns structured before/after | unit |
| Rollback restores prior profile bundle via `/patches/{id}/rollback` | unit |
| Single write path to the profile TOML | code review + test |

## Conflicts & resolutions

- **Two-writer hazard** — `profiles.py` writes via `_write_bundle`, bypassing `safe_edit_engine`;
  bolting on a second history path means two writers to the same TOML. **→ Resolution**: route all
  profile mutations through `SafeEditEngine.apply` with a new registered kind
  `("agentic_os","run_profile")` — add the path-whitelist entry in `schema_registry._PATH_WHITELIST`
  and a `schemas/agentic_os/run_profile.json` (else `validate_document` returns "no schema" and
  blocks). This yields `patch_id` + `/patches/{id}/rollback` + audit + `base_mtime` for free, exactly
  like config. `_write_bundle` is demoted to the engine's TOML serializer (or replaced by
  `atomic_write_toml`); it is no longer an independent mutation path. **One writer = the engine.**
  Caveat: if the bundle's inline-table formatting must be preserved, the engine's TOML writer must
  preserve it; otherwise generic formatting is acceptable.
- **Orphan bindings** — deleting a profile bound to a project leaves dangling bindings.
  **→ Resolution**: `DELETE` is safe-by-default — it returns `409` with the list of bound projects
  unless `?cascade=true`, which removes the bindings in the same patch (so the delete + unbind roll
  back together).
- **Launch path frozen** — `resolve_profile` / launch behavior (025) is unchanged. **→ Held**.
