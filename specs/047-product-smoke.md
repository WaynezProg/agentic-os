# 047 — Product Smoke Harness (P28b)

Status: Complete
Date: 2026-06-07
Depends on: `specs/048-provider-model-launch-wiring.md`, catalog/config/profile/registry editors (P16–P27)
Blocks: P29–P33 daily-operator track

## Positioning

Prove the Harness Manager product end-to-end with **behavior-level** checks, not
endpoint liveness alone. Failures must name the first broken step and leave a
machine-readable report.

## Scope

| Owns | Does not own |
|------|--------------|
| `scripts/smoke-product.sh` with text + JSON report | Hosted CI orchestration |
| Model-in-argv assertion via shell harness + profile | Auto-update / notarization |
| Config round-trip smoke (catalog, harness-config, registry) | New agent features |
| Import/export diff gate + secret redaction check | Cloud sync |
| Remote localhost-only enforcement sample | Full remote write matrix |
| Approval approve → retry loop | In-harness tool approval |

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Smoke script exits 0 when product healthy | `bash scripts/smoke-product.sh` |
| Non-zero exit writes report with first failing step | inspect `report.json` on failure |
| Model appears in spawned argv and stdout | smoke step `run_model_in_argv` |
| README documents verification path | `tests/test_web.py` + manual |
