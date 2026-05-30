# 014 — Workflow Surface Catalog (P6)

Status: Implemented with gaps
Date: 2026-05-30

## Positioning

Scans harness-specific directories across user/project/local scopes,
classifies surfaces, provides merged/diff views. Read-only.

| Phase | Owns | Does not own |
|-------|------|--------------|
| P6 | scan paths, classify surfaces, merged view, diff | executing hooks, loading skills, modifying configs |

## Supported Harnesses

| Harness | User Path | Project Path |
|---------|-----------|--------------|
| Claude Code | `~/.claude/` | `<repo>/.claude/` |
| OpenClaw | `~/.openclaw/` | `<repo>/.openclaw/` |
| Hermes | `~/.hermes/` | `<repo>/.hermes/` |

## Surface Types

| Type | Source |
|------|--------|
| hook | `settings.json` hooks section |
| command | `commands/*.md`, `commands/*.toml` |
| skill | `skills/<name>/SKILL.md` |
| subagent | `agents/*.md`, `settings.json` customAgents |
| mcp_server | `settings.json` mcpServers |
| permission | `settings.json` permissions |

## Implementation Status

### Completed
- `src/agentic_os/catalog.py` — scan(), merge(), diff(), per-surface scanners
- 4 API endpoints in `api.py` (surfaces, merged, diff)
- 3 CLI commands in `cli.py` (list, merged, diff)
- 4 client methods in `client.py`
- `tests/test_catalog.py` — 16 tests
- `tests/test_api.py` — 4 API tests
- UI "Surfaces" tab in `index.html` + `app.js` loadCatalog()

### Gaps
- **Claude Code managed scope** — only user/project/local scanned, not system-managed settings
- **OpenClaw/Hermes config.toml scanning** — `_scan_toml_config()` is a stub, returns empty
- **Settings display** — spec says "settings" should be catalogued but currently only extracts hooks/MCP/permissions/subagents, not general settings keys

### Not Doing
- Executing hooks, commands, or skills
- Modifying config files
- Parsing harness-internal prompt routing

## Acceptance Criteria & Verification

| Criterion | Status | How to verify |
|-----------|--------|---------------|
| Scans Claude Code hooks from settings.json | ✅ | `test_scan_hooks_from_settings` |
| Scans commands/ directory | ✅ | `test_scan_commands_directory` |
| Scans skills/ with SKILL.md | ✅ | `test_scan_skills_directory` |
| Scans agents/ (subagents) | ✅ | `test_scan_subagents_from_settings` |
| Scans MCP servers from settings.json | ✅ | `test_scan_mcp_servers_from_settings` |
| Scans permissions from settings.json | ✅ | `test_scan_permissions_from_settings` |
| user/project/local scope labels | ✅ | All tests use separate home_dir for isolation |
| merged view with override info | ✅ | `test_merge_local_overrides_user` |
| diff between scopes/projects | ✅ | `test_diff_added_and_removed`, API test |
| Empty dirs don't error | ✅ | `test_scan_empty_cwd` |
| UI shows override_by/overrides columns | ✅ | loadCatalog renders both columns |
| OpenClaw/Hermes scanning | ❌ | TOML scanner is stub |
| managed scope | ❌ | Not implemented |
| settings keys catalogued | ❌ | Only hooks/MCP/permissions/subagents extracted |
