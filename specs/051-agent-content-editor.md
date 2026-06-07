# 051 — Agent Content Editor (P31)

Status: Complete
Date: 2026-06-07
Depends on: control-plane history (`specs/041-mcp-skill-policy-rollback-backend.md`)

## Scope

Form-based editing for skills/MCP/policy; skill content field; hook patch via harness-config; policy evaluate wired to live evaluator. All writes via control-plane history + rollback.

## UI

- Extended `ui/control-plane-editor.js`
