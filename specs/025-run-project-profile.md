# 025 — Run / Project Profile

Status: Implemented  
Date: 2026-05-30  
Depends on: 024  
Design: `docs/superpowers/specs/2026-05-30-024-026-debt-closure-design.md`

## Owns

- Global/local `profiles.toml`, project bindings, profile resolution on `POST /sessions`
- `GET /profiles`, `GET /profiles/{name}`, `POST /profiles` (upsert), `POST /projects/{path}/bind-profile`
- `agentctl profiles list|show|set|bind`

## Write semantics

- `POST /profiles` and `profiles set` default to **local** (`<cwd>/.agentic-os/profiles.toml`)
- `scope=global` or `--global` writes `~/.agentic-os/profiles.toml`

## Does not own

- UI profile editor, provider billing, quota enforcement inside harness

## Verification

```bash
uv run pytest tests/test_profiles.py tests/test_api.py -k profile -q
```
