# 019 — Workflow Catalog Expansion

Status: Implemented
Date: 2026-05-30
Depends on: 018 (registry ids align with catalog harness keys)
Blocks: 020

## Positioning

Extend `catalog.py` `_HARNESS_SCOPES` from three harnesses to six, matching
registry ids from 018. Surfaces tab and CLI must list/merge/diff for all six.

| Phase | Owns | Does not own |
|-------|------|--------------|
| P6+ | scope paths, scan coverage, merged/diff for 6 harnesses | executing skills/hooks, installing MCP |

## Scope path table

| harness id | user | project | local |
|------------|------|---------|-------|
| `claude` | `~/.claude` | `.claude` | `.claude/local` |
| `codex` | `~/.codex` | `.codex` | `.codex/local` |
| `opencode` | `~/.config/opencode` | `.opencode` | `.opencode/local` |
| `qwen` | `~/.qwen` | `.qwen` | `.qwen/local` |
| `openclaw` | `~/.openclaw` | `.openclaw` | `.openclaw/local` |
| `hermes` | `~/.hermes` | `.hermes` | `.hermes/local` |

## Scanner behavior per harness

| harness | settings.json | commands/ | skills/ | config.toml | notes |
|---------|---------------|-----------|---------|-------------|-------|
| claude | yes | yes | yes | no | existing scanners |
| codex | yes (if present) | yes | yes | no | reuse JSON scanners |
| opencode | yes | yes | yes | no | JSON in config dir |
| qwen | yes | yes | yes | no | same layout as claude family |
| openclaw | partial | yes | yes | **yes** | implement `_scan_toml_config` (014 gap) |
| hermes | partial | yes | yes | **yes** | implement `_scan_toml_config` |

Empty scan → HTTP 200 with `surfaces: []` and `empty: true` in metadata — not
404.

## API / CLI (unchanged routes, expanded harness param)

```
GET /catalog/{harness}/surfaces?cwd=
GET /catalog/{harness}/merged?cwd=
GET /catalog/{harness}/diff?scope_a=&scope_b=&cwd=
```

CLI:

```bash
agentctl catalog list <harness> --cwd .
agentctl catalog merged <harness> --cwd .
agentctl catalog diff <harness> --scope-a user --scope-b project --cwd .
```

Invalid harness id → **HTTP 400** (matches existing catalog routes) with JSON
detail:

```json
{
  "message": "unsupported harness: unknown",
  "supported": ["claude", "codex", "opencode", "qwen", "openclaw", "hermes"]
}
```

Replace the three hardcoded allowlists in `api.py` (lines ~1062, 1076, 1090)
with `catalog.SUPPORTED_HARNESSES` via a shared `_require_catalog_harness()`
helper.

## UI

Surfaces tab harness `<select>` populated from `GET /agents` filtered to
non-shell ids (or `SUPPORTED_HARNESSES`). Show explicit "No surfaces found"
when merged is empty.

## Does not own

- Executing hooks/commands/skills
- MCP server process start
- Harness-native config effective merge (020)
- managed/org scope (future)

## Gap closure from 014

This spec **owns** closing 014 gaps:

- OpenClaw/Hermes TOML scanner (was stub)
- Six-harness Surfaces tab selector

Does **not** own:

- Claude managed scope
- General settings key cataloguing beyond hooks/MCP/permissions/subagents

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| `SUPPORTED_HARNESSES` has 6 entries | unit test |
| Each harness: `catalog merged` returns 200 | 6 CLI smokes on real `$HOME` |
| Real repo: merged non-empty OR explicit empty flag | manual on `agentic-os` repo |
| Unknown harness → 400 with `supported` list | API test |
| `api.py` uses `SUPPORTED_HARNESSES` (no duplicate tuple) | code review |
| OpenClaw/Hermes TOML surfaces when config.toml exists | `test_catalog.py` fixtures |
| UI harness dropdown has 6 options | `test_web.py` |

## Implementation plan

`docs/superpowers/plans/2026-05-30-019-workflow-catalog-expansion.md`
