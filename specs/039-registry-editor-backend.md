# 039 — Harness Instance Registry Editor Backend (P20)

Status: Implemented
Date: 2026-06-07
Depends on: multi-harness registry pack (`specs/018-multi-harness-registry-pack.md`), harness instance profile schema (`specs/007-harness-instance-profile-p3.7.md`), safe-edit engine (`specs/027-safe-native-config-editing.md`)
Blocks: P21 (`specs/040-registry-editor-ui.md`)

## Positioning

`registry.py` is **read-only today**: `_load`, `list_agents`, `get`, `build_run`,
`validate_registry`. Editing harness instances requires hand-editing `agents.toml`.
P20 adds **safe write** (create / update / disable) to the agentic-os registry —
backend only — without touching harness-native logic.

## Scope

| Owns | Does not own |
|------|--------------|
| Create / update / disable harness instance in `agents.toml` | Harness-native config (that's `/harness-config/*`, P17) |
| Validation + backup + atomic write + reload | Harness internals / planning / tool execution |
| Reuse `validate_registry` as the pre-write gate | Starting harness processes |

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Create instance → appears in `list_agents` after reload | `tests/test_registry.py` (new) |
| Invalid instance rejected by `validate_registry` pre-write (422) | unit |
| Backup written; rollback restores prior `agents.toml` | unit |
| Only `agentd` writes `agents.toml` (no second writer) | code review |

## Conflicts & resolutions

- **Single-writer + corruption risk** — `agents.toml` is launch-critical; an ad-hoc or concurrent
  writer can break every run. **→ Resolution**: route registry writes through `SafeEditEngine.apply`
  with a new registered kind `("agentic_os","registry")` (whitelist entry +
  `schemas/agentic_os/registry.json`). The engine already gives in-process atomic write +
  snapshot/backup + `/patches/{id}/rollback` + audit + `base_mtime`. Only `agentd` ever calls it,
  preserving the single-writer invariant.
- **Launch safety / validation** — **→ Resolution**: run `validate_registry` as a pre-commit gate
  *inside* the patch path — `errors` → `422` reject; `warnings` → returned but allowed. Combined
  with the engine's atomic replace + snapshot, a bad write can neither half-apply nor be
  unrecoverable.
- **Domain confusion** — registry (agentic-os instance list) vs harness-native config (027/036).
  **→ Resolution**: distinct engine kind `("agentic_os","registry")` and distinct file
  (`agents.toml`); the path whitelist keeps the two from cross-writing.
- **Schema alignment** — **→ Resolution**: `schemas/agentic_os/registry.json` mirrors the P3.7
  instance fields (`007`) so the registry schema and the profile schema stay in lockstep.
