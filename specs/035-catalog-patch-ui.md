# 035 — Catalog Patch UI + Frontend Operation Shell (P16)

Status: Implemented
Date: 2026-06-07
Depends on: P10/P11 catalog patch engine (`specs/012-workflow-surface-catalog.md`, `specs/014-workflow-surface-catalog.md`, `specs/019-workflow-catalog-expansion.md`), safe-edit engine (`specs/027-safe-native-config-editing.md`)
Blocks: P17 (`specs/036-config-patch-ui.md`)

## Positioning

`apps/web` today is a read-only console: the Catalog tab loads and displays surfaces
but cannot mutate them. P16 turns the **most mature backend patch flow** — catalog
surface patch + rollback — into the first operable UI vertical, and extracts the
shared frontend operation shell *while building it*.

This is explicitly **not** a standalone "frontend refactor phase". The `app.js`
split happens in service of the Catalog editor; abstractions fall out of one working
vertical, not speculation. APNs push (the original P16 placeholder in `034`) is
deferred indefinitely and is not a numbered phase.

## Backend already in place (no new endpoints)

- `GET /catalog/{harness}/surfaces`, `/merged`, `/diff`
- `POST /catalog/{harness}/surfaces/patch?dry_run=…` → returns `patch_id` + `diff`
- `GET /patches`, `GET /patches/{patch_id}`, `POST /patches/{patch_id}/rollback`

Fixed flow for every action: **load → edit → dry-run (diff preview) → apply → rollback**.

## Scope

| Owns | Does not own |
|------|--------------|
| Catalog editor: MCP enable/disable, hook upsert, command/skill upsert | Harness-native config editing (P17) |
| Dry-run diff preview, apply, patch history, rollback UI | Starting MCP servers / installing capabilities |
| Shared operation shell extracted from `app.js` | Mutating on-disk skill files beyond catalog patch semantics |

Frontend architecture introduced here (serving the catalog editor):

- `apps/web/api.js` — local/remote `apiFetch`, Tauri bridge
- `apps/web/ui/actions.js` — button → action dispatcher
- `apps/web/ui/catalog-editor.js` — catalog patch UI
- `apps/web/ui/rollback.js` — patch history / rollback UI (domain-agnostic, reused by P17/P19/P21/P23)

`app.js` shrinks to wiring; tabs not yet migrated stay as-is (incremental, no big-bang rewrite).

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| MCP enable/disable produces a dry-run diff before apply | `tests/test_web.py` + manual |
| Apply returns `patch_id`; rollback restores prior state | reuse `tests/test_*catalog*`/`test_patch*` |
| Catalog editor works against both local and remote `apiFetch` | manual local + remote-gateway |
| No new backend route added | route inventory diff = ∅ |

## Conflicts & resolutions

- **Phase renumber** — `034` listed "Blocks: P16 (APNs)". **→ Resolved**: P16 reassigned to this
  spec; APNs deferred; `034` corrected in the same change.
- **Refactor trap** — a pure `app.js` split ships no value and is hard to verify. **→ Resolution**:
  gate P16 "done" on a working MCP enable/disable round-trip through the shell; the split is
  reviewed *inside* that PR, never as a standalone refactor PR. `ui/rollback.js` is built
  domain-agnostic from day one so later phases reuse it instead of re-splitting.
- **Remote-mode writes** — catalog patch routes are not under `require_localhost_operator`, so
  they are reachable via the gateway before P25 defines remote-safe actions. **→ Resolution**:
  the operation shell reads one `mode` flag; until P25 lands, write actions render only in local
  mode and the Catalog tab is read-only in remote mode. No ungated remote writes ship before P25.
