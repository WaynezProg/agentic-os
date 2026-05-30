# 026 — Usage Ledger

Status: Implemented  
Date: 2026-05-30  
Depends on: 024, 025  
Design: `docs/superpowers/specs/2026-05-30-024-026-debt-closure-design.md`

## Owns

- `UsageRecord` / `UsageStore`, session-end collection in supervisor
- Parsers: `openclaw`, `claude`, `codex`, `opencode`, `cursor` (+ fallback)
- `GET /usage/summary`, `GET /usage/sessions/{id}`, `GET /usage/quotas`
- `agentctl usage summary|session|quotas`

## Quota semantics

`/usage/quotas` reports **profile budgets** (`max_tokens_budget`), not provider billing.

| scope | meaning |
|-------|---------|
| `daily` | per-profile token sum for UTC day |
| `session` | per-session usage vs profile budget |

Statuses: `ok`, `warning` (≥80%), `exceeded`.

## Does not own

- Live provider billing, `limit_cost_usd` enforcement

## Verification

```bash
uv run pytest tests/test_usage.py tests/test_api.py -k usage -q
```
