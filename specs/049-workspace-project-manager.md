# 049 — Workspace / Project Manager (P29)

Status: Complete
Date: 2026-06-07
Depends on: profile cwd scoping (`specs/018-run-profile-backend-patch.md`)
Blocks: `specs/050-provider-model-switchboard-ui.md`, `specs/053-daily-operator-dashboard.md`

## Scope

| Owns | Does not own |
|------|--------------|
| Server-side workspace registry + active cwd | File explorer / full-disk scan |
| `GET/POST/PUT /workspaces`, `GET /workspaces/dashboard` | Cloud sync |
| Workspace selector UI + cwd threading through editors | Duplicate cwd model |

## Acceptance

- Switching workspace re-scopes profile list, harness config, catalog scan
- Active workspace visible in UI; remote reads OK, writes localhost-only (§2A)
