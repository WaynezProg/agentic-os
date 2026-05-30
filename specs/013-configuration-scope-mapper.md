# 013 — Configuration Scope Mapper (P5)

Status: Implemented
Date: 2026-05-30

## Positioning

Reads agentic-os config files across scopes, merges with priority resolution,
provides diff/explain views. Read-only — does NOT modify config files.

| Phase | Owns | Does not own |
|-------|------|--------------|
| P5 | config scope resolution, effective merge, diff, explain | modifying configs, harness-internal config loading, validation |

## Scope

### Scope Levels

| Scope | Location | Priority |
|-------|----------|----------|
| user | `~/.agentic-os/config.toml` | 2 |
| project | `<cwd>/.agentic-os/config.toml` | 3 |
| local | `<cwd>/.agentic-os.local/config.toml` | 4 |

managed scope: Not implemented — reserved for future org-wide baseline.

### CLI Commands

```bash
agentctl config effective <harness_id> --cwd <path>
agentctl config diff <harness_id> --scope-a user --scope-b project --cwd <path>
agentctl config explain <harness_id> --cwd <path>
```

### API Endpoints

```
GET /config/{harness_id}/effective?cwd=<path>
GET /config/{harness_id}/diff?scope_a=user&scope_b=project&cwd=<path>
GET /config/{harness_id}/explain?cwd=<path>
```

## Implementation Status

### Completed
- `src/agentic_os/config_scope.py` — effective(), diff(), explain(), read_config()
- managed scope path included in `resolve_paths()` and `effective()`
- 3 API endpoints in `api.py`
- 3 CLI commands in `cli.py`
- 4 client methods in `client.py`
- `tests/test_config_scope.py` — 10 tests
- `tests/test_api.py` — 3 API tests

### Gaps
- **explain() only shows winning entries** — does not show overridden/losing entries
- **4-way merge not fully tested** — managed scope test would require writing to `/etc/agentic-os`

### Not Doing
- Config modification or writing
- Config validation or hinting

## Acceptance Criteria & Verification

| Criterion | Status | How to verify |
|-----------|--------|---------------|
| Can read user/project/local configs | ✅ | `uv run pytest tests/test_config_scope.py -q` |
| project overrides user for same key | ✅ | `test_effective_project_overrides_user` |
| local overrides project for same key | ✅ | `test_effective_local_overrides_project` |
| diff detects added/removed/modified keys | ✅ | `test_diff_added_removed` |
| explain returns entries with scope+source | ✅ | `test_explain_returns_entries` |
| API returns valid response structure | ✅ | 3 API tests in `test_api.py` |
| managed scope support | ❌ | Not implemented — reserved |
