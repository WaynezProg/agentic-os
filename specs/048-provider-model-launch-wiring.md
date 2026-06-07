# 048 — Provider / Model Launch Wiring (P28a)

Status: Complete
Date: 2026-06-07
Depends on: run profile backend (`specs/018-run-profile-backend-patch.md`), harness instance registry (`specs/020-registry-editor-backend.md`)
Blocks: `specs/047-product-smoke.md`, `specs/050-provider-model-switchboard-ui.md`

## Positioning

Profiles already record `resolved_provider` and `resolved_model` on Harness Run
records, but those values never reached spawned harness argv/env. P28a closes that
gap with backward-compatible per-harness templating — no harness-runtime changes.

## Scope

| Owns | Does not own |
|------|--------------|
| Optional `model_arg` / `provider_env` on `AgentDefinition` | Harness-internal model loading |
| `{{model}}` / `{{provider}}` substitution in registry argv/env | Cheapest-model heuristics |
| Thread resolved profile model/provider through `_prepare_session_run` | Billing APIs |

## Design

- `model_arg = ["--model", "{{model}}"]` appends argv fragments when a profile
  resolves a model.
- `provider_env = "ANTHROPIC_PROVIDER"` sets that env var when a profile resolves
  a provider.
- Harnesses without these fields behave exactly as before.
- Retry reuses stored session argv, preserving the resolved model fragments.

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Profile model reaches spawned argv when harness defines `model_arg` | `tests/test_api.py::test_profile_model_reaches_spawned_argv` |
| Harness without `model_arg` unchanged | `tests/test_registry.py::test_harness_without_model_arg_unchanged_by_profile_model` |
| Retry preserves model argv | `tests/test_api.py::test_retry_preserves_profile_model_in_argv` |
| `examples/agents.toml` documents `model_arg` for claude/codex | manual |
