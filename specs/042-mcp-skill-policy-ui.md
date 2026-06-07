# 042 — MCP / Skill / Policy Management UI (P23)

Status: Complete
Date: 2026-06-07
Depends on: P22 (`specs/041-mcp-skill-policy-rollback-backend.md`), skills/MCP/policy catalog (`specs/004-skills-mcp-policy.md`)
Blocks: —

## Positioning

Form-based management for skills, MCP servers, and policies — only **after** P22 gives
these domains history + rollback. Without P22 this UI would fake a safety contract that
the backend lacks.

## Scope

| Owns | Does not own |
|------|--------------|
| MCP server form: `name`, `transport`, `command`, `args`, env-var *names*, `scope` | Starting/connecting MCP servers |
| Skill / command editing, policy form editing | Installing capabilities |
| dry-run → diff → apply → rollback (same envelope as P22) | Live in-harness tool enforcement |

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| MCP/skill/policy create/edit/disable round-trips | `tests/test_web.py` |
| History view + rollback to prior version works (reuses `ui/rollback.js`) | manual |
| Secrets referenced by env name only; values never shown | redaction assertion |

## Conflicts & resolutions

- **Hard scope line (CLAUDE.md)** — a "test config / start server" button would cross into
  harness-runtime ownership ("does not own starting MCP servers"). **→ Resolution**: P23 ships
  **static validation only** — shape/schema/env-name checks, optionally "binary exists on PATH" — and
  spawns nothing. Any live connectivity test is explicitly out of scope and requires its own spec +
  process-ownership review before it can exist.
- **Secret redaction** — **→ Resolution**: env-var name inputs only; the form rejects any value that
  matches the `control_plane` secret patterns before submit, so a pasted token never reaches the API.
- **Blocked by P22** — **→ Held**: do not ship before DB rollback exists.
