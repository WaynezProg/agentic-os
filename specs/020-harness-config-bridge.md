# 020 — Harness Config Bridge (Read-Only)

Status: Implemented
Date: 2026-05-30
Depends on: 018 (`config_path`), 019 (harness id table)
Blocks: 021 (Harnesses tab display)

## Positioning

Read **harness-native** configuration (e.g. `~/.claude/settings.json`,
`~/.codex/config.toml`) and expose effective/merged/diff/explain views.
Strictly separated from **013 Configuration Scope Mapper**, which only reads
`~/.agentic-os/` and project `.agentic-os/` files.

| System | Scope paths | Spec |
|--------|-------------|------|
| agentic-os config | `~/.agentic-os/`, `<cwd>/.agentic-os/` | 013 |
| harness-native config | per 018 `config_path` + harness layout | **020** |

## Module

New `src/agentic_os/harness_config.py`:

- `resolve_harness_config_paths(harness: str, cwd: Path) -> dict[str, Path]`
- `read_harness_config(harness: str, scope: str, cwd: Path) -> dict`
- `effective(harness, cwd) -> dict`
- `diff(harness, scope_a, scope_b, cwd) -> dict`
- `explain(harness, cwd) -> list[dict]`

Reuse merge priority pattern from `config_scope.py` but **separate code path**
— no import of agentic-os config readers into harness readers.

## Per-harness config layout

| harness | user config | project config | format |
|---------|-------------|----------------|--------|
| claude | `~/.claude/settings.json` | `.claude/settings.json` | JSON |
| codex | `~/.codex/config.toml` | `.codex/config.toml` | TOML |
| opencode | `~/.config/opencode/config.json` | `.opencode/config.json` | JSON |
| qwen | `~/.qwen/settings.json` | `.qwen/settings.json` | JSON |
| openclaw | `~/.openclaw/config.toml` | `.openclaw/config.toml` | TOML |
| hermes | `~/.hermes/config.toml` | `.hermes/config.toml` | TOML |

Local scope: `<cwd>/.<harness>/local/` mirroring catalog local paths from 019.

## API

```
GET /harness-config/{harness_id}/effective?cwd=
GET /harness-config/{harness_id}/diff?scope_a=user&scope_b=project&cwd=
GET /harness-config/{harness_id}/explain?cwd=
```

Prefix **`/harness-config/`** — never `/config/` (013 namespace).

## CLI

```bash
agentctl harness-config effective <harness_id> --cwd .
agentctl harness-config diff <harness_id> --scope-a user --scope-b project --cwd .
agentctl harness-config explain <harness_id> --cwd .
```

## UI

Harnesses tab: expandable "Native config" panel per instance showing effective
JSON/TOML snippet (truncated to 4 KB, redacted via existing `_redact_*` patterns
from `control_plane.py`).

## Security

- Read-only file access under expanded `config_path` and project `.*/` dirs.
- Apply secret redaction before API/UI response (reuse `_SECRET_*` patterns).
- Never write or suggest write-back commands in 020.

## Does not own

- Writing harness configs
- Migration between harness versions
- agentic-os config (013)
- Validating harness config semantics

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| `/harness-config/claude/effective` distinct from `/config/shell/effective` | API test |
| Project overrides user for same key (claude JSON) | unit test with tmp dirs |
| Missing config files → empty dict, not 500 | unit test |
| Redaction masks API keys in snippet | unit test |
| Harnesses tab shows truncated effective config | manual UI |
| 013 routes unchanged | regression test |

## Implementation plan

`docs/superpowers/plans/2026-05-30-020-harness-config-bridge.md`
