# 036 — Harness / Agentic Config Patch UI (P17)

Status: Draft
Date: 2026-06-07
Depends on: P16 (`specs/035-catalog-patch-ui.md`), harness config bridge (`specs/020-harness-config-bridge.md`), configuration scope mapper (`specs/013-configuration-scope-mapper.md`), safe-edit engine (`specs/027-safe-native-config-editing.md`)
Blocks: P18 (`specs/037-profile-backend-patch.md`)

## Positioning

Two distinct config domains already have full read+patch backends through the shared
`safe_edit_engine`. The UI must expose both **without conflating them**:

| Route family | Edits | Scopes | Schema target |
|--------------|-------|--------|---------------|
| `/harness-config/{harness_id}/*` | harness-native config (Claude Code, Codex, …) | `HARNESS_CONFIG_SCOPES` (project/user) + `file` param | `SUPPORTED_HARNESSES` |
| `/config/{harness_id}/*` | agentic-os's own config | `CONFIG_PATCH_SCOPES` | `AGENTIC_CONFIG_SCHEMA_HARNESS` |

Both expose `effective`, `diff`, `explain`, and `POST …/patch?dry_run=…`.

## Backend behavior the UI must honor

- `dry_run=true` → preview diff, no write; the preview `PatchResult` carries `base_mtime`.
- `base_mtime` optimistic lock → `409 stale_target` if the file changed since.
- `422 {validation_errors}` → render schema validation errors inline.
- `403 {error: forbidden_path}` → edit target outside the `schema_registry` path whitelist; surface, do not retry.
- Rollback via `POST /patches/{patch_id}/rollback`; history via `GET /patches`.

## Scope

| Owns | Does not own |
|------|--------------|
| JSON/TOML path-patch editor with diff preview per route family | Starting/restarting harnesses |
| Schema validation error display, rollback history view | Harness runtime/internals (CLAUDE.md boundary) |
| Clear "harness-native" vs "agentic-os" labeling | Inventing a second config writer |

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Patch dry-run shows diff for both families | `tests/test_web.py` + `tests/test_*config*` |
| Stale `base_mtime` → 409 handled with re-preview, no overwrite | unit + manual |
| Schema error → inline validation_errors render | manual |
| Two families never cross-write (harness vs agentic) | route-target assertion |

## Conflicts & resolutions

- **Apparent duplication** — `/config/*` and `/harness-config/*` look redundant but are separate
  domains; binding the editor to the wrong family corrupts the wrong file. **→ Resolution**: one
  parameterized `ui/config-editor.js` taking a `domain` descriptor
  `{family, basePath, scopes, label, schemaHarness}`. The descriptor is the single binding point —
  no copy-pasted editors, no cross-write. Two descriptor instances, one component.
- **Concurrency / `base_mtime`** — the only guard against lost updates; the `effective` GET does
  **not** return mtime, so where does the client get the token? **→ Resolution**: take it from the
  mandatory dry-run preview — `PatchResult.base_mtime` = the target file's current mtime — and
  carry that value into the real apply. On `409 stale_target`, re-run the preview. **No backend
  change required**; the preview step already produces the token.
- **Scope boundary** — editing harness-native files brushes the "no harness internals" line.
  **→ Resolution**: the editor calls only the patch/diff/effective routes; it has no start/stop/
  restart route wired to it. Writing the file is in scope (027 drew this line); running the harness
  is not.
