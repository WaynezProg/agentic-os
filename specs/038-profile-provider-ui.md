# 038 — Profile / Provider UI (P19)

Status: Implemented
Date: 2026-06-07
Depends on: P18 (`specs/037-profile-backend-patch.md`), run/project profile (`specs/025-run-project-profile.md`)
Blocks: —

## Positioning

This is the phase that solves the **daily pain**: switching provider/model per project
(Codex / Claude / Cursor). Pure frontend over the profile backend once P18 lands.

## Scope

| Owns | Does not own |
|------|--------------|
| List / create / edit (upsert) / delete profiles in UI | Profile backend semantics (P18) |
| Bind project path → profile; show resolved profile | Launch path (frozen, `025`) |
| Display harness / provider / model / message_prefix / quota | Storing secret values |

Flow reuses the operation shell from P16: load → edit → dry-run/diff → apply → rollback.

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Create/edit/delete profile round-trips through API | `tests/test_web.py` |
| Bind project to profile, resolved profile shown | manual |
| Provider token referenced by env-var name, never value | redaction assertion |

## Conflicts & resolutions

- **Secrets** — provider credentials must never be stored as values. **→ Resolution**: the
  credential field is an **env-var name** input validated client-side against `^[A-Z][A-Z0-9_]*$`;
  there is no secret-value field in the form. This mirrors the `control_plane.py` redaction
  invariant (skills/MCP reference secrets by name).
- **Validation** — duplicating `message_prefix`/`quota` rules in JS drifts from the backend.
  **→ Resolution**: the server (P18) is the source of truth; the form submits and renders any
  returned `validation_errors`. JS does only lightweight shape hints, never authoritative rules.
- **Delete UX** — deleting a bound profile. **→ Resolution**: surface P18's safe-by-default
  behavior — show the bound projects returned by the `409`, and require an explicit "cascade
  unbind" confirmation before re-sending with `?cascade=true`.
