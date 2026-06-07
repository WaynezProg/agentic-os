# 040 — Harness Instance Registry Editor UI (P21)

Status: Implemented
Date: 2026-06-07
Depends on: P20 (`specs/039-registry-editor-backend.md`), harness instance profile schema (`specs/007-harness-instance-profile-p3.7.md`)
Blocks: —

## Positioning

Form-based UI to add/modify/disable harness instances once the P20 backend exists.
Pure frontend over the registry write API.

## Scope

| Owns | Does not own |
|------|--------------|
| Form for `label`, `command`, `cwd_mode`, `health_command`, `attach_command`, `log_paths`, `default_provider` | Registry write semantics (P20) |
| dry-run validate → diff → apply → rollback via operation shell | Harness-native logic |
| Surface `validate_registry` errors/warnings inline | Launching/attaching processes |

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Create/edit/disable instance via form round-trips | `tests/test_web.py` |
| Validation errors/warnings shown before apply | manual |
| Rollback restores prior instance state | manual |

## Conflicts & resolutions

- **Command/argv sensitivity** — `command`, `health_command`, `attach_command` are shell surfaces
  that may carry secrets. **→ Resolution**: the preview renders the engine's diff, which already
  passes through `_redact_value`; the UI displays the redacted diff verbatim and never reconstructs
  raw values for display.
- **`cwd_mode` enum** — free text invites invalid states. **→ Resolution**: render a dropdown whose
  options come from a backend-provided enum (P20), not a hardcoded JS list.
- **Blocked by P20** — **→ Held**: this UI ships only after the registry write backend exists.
