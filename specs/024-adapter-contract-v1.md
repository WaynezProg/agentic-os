# 024 — Adapter Contract v1

Status: Implemented  
Date: 2026-05-30  
Depends on: 007, 018  
Design: `docs/superpowers/specs/2026-05-30-024-026-debt-closure-design.md`

## Owns

- `HarnessAdapterContract` schema and `GET /harness-contracts` APIs
- `agentctl harness-contracts list|show`
- Deterministic contract for all registry harness instances (including `cursor`)

## Does not own

- Harness CLI execution, attach runtime (023), profile resolution (025)

## Verification

```bash
uv run pytest tests/test_api.py -k harness_contract -q
uv run agentctl harness-contracts list
```
