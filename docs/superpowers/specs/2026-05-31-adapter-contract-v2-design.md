# Adapter Contract v2 Design

Date: 2026-05-31
Status: Approved
Author: agentic-os team
Supersedes: Adapter-contract portions of `docs/superpowers/specs/2026-05-30-harness-manager-extension-design.md`
Related specs: `specs/024-adapter-contract-v1.md`, `docs/superpowers/specs/2026-05-30-024-026-debt-closure-design.md`

## Summary

`agentic-os` currently exposes an adapter contract v1 derived mostly from registry command
templates. That is enough to launch processes, but it is not enough to manage heterogeneous
harnesses as semantic peers. Codex, Claude, Cursor, OpenClaw, Hermes, OpenCode, and Qwen differ
in prompt input mode, output mode, native session identity, resume/attach semantics, usage output,
config locations, workflow surface layout, and policy enforceability.

Adapter Contract v2 adds a semantic harness contract while keeping the existing process supervisor
and v1 API stable. This first slice exposes v2 through API and CLI, backed by golden fixture tests.
It does not change session persistence, runtime policy enforcement, or UI behavior.

## Locked Scope

- Add `HarnessAdapterContractV2` models in `src/agentic_os/adapter_contract.py`.
- Add `contract_from_agent_v2(agent)` that maps existing registry data plus per-harness metadata to v2.
- Add `version=v2` support to `GET /harness-contracts` and `GET /harness-contracts/{harness_id}`.
- Add `--version v2` support to `agentctl harness-contracts list|show`.
- Add golden fixtures for the seven non-shell harnesses: `claude`, `codex`, `cursor`, `hermes`,
  `openclaw`, `opencode`, and `qwen`.
- Add parser/contract tests that prove launch, health, version, resume/attach, usage, config,
  surface, and policy contract fields are deterministic.

## Non-goals

- No SessionRecord schema changes.
- No `events.jsonl`, artifacts manifest, or upstream conversation model.
- No live runtime policy proxy or in-harness enforcement.
- No UI changes.
- No registry TOML redesign beyond derived contract metadata.
- No forced switch from current text output modes to JSON output modes.

## Versioning

v1 remains the default response for compatibility:

```http
GET /harness-contracts
GET /harness-contracts/claude
```

v2 is explicit:

```http
GET /harness-contracts?version=v2
GET /harness-contracts/claude?version=v2
```

CLI mirrors the same default:

```bash
agentctl harness-contracts list
agentctl harness-contracts list --version v2
agentctl harness-contracts show claude --version v2
```

Unsupported versions return `400` with:

```json
{"detail":"unsupported contract version: v3","supported":["v1","v2"]}
```

## Contract Shape

### Top level

`HarnessAdapterContractV2`

- `harness_id`: registry id.
- `contract_version`: literal `"v2"`.
- `launch`: prompt input and process launch contract.
- `resume`: native session resume contract.
- `attach`: attach contract for already-created native sessions.
- `log`: log source and parser expectations.
- `usage`: usage parser contract.
- `config`: native config scope contract.
- `surface`: workflow surface scan contract.
- `policy`: policy capability contract.
- `capability_matrix`: flattened booleans used by management views and CLI.
- `required_env`: environment variable names only.
- `error_modes`: known failure classes.

### Launch contract

`launch` answers how `agentic-os` passes a prompt into the harness.

- `supported`: bool.
- `command_template`: argv template from registry.
- `prompt_input_mode`: one of `argv`, `stdin`, `file`, `json`.
- `output_mode`: one of `plain_text`, `json`, `jsonl`, `tool_events`, `mixed`.
- `cwd_mode`: registry cwd mode.
- `requires_workspace`: true when cwd is semantically required by the harness.

Initial mapping:

| Harness | prompt_input_mode | output_mode |
|---------|-------------------|-------------|
| claude | argv | plain_text |
| codex | argv | plain_text |
| cursor | argv | plain_text |
| hermes | argv | plain_text |
| openclaw | argv | json |
| opencode | argv | plain_text |
| qwen | argv | plain_text |

### Resume and attach contracts

`resume` describes native conversation continuation. `attach` describes joining an existing
native session or terminal-capable session.

- `supported`: bool.
- `command_template`: argv template when available.
- `identity_kind`: one of `none`, `upstream_session_id`, `conversation_id`, `thread_id`.
- `requires_discovered_identity`: true when resume needs a parsed upstream id.
- `strategy`: one of `unsupported`, `command`, `best_effort`.

Initial identity mapping:

| Harness | resume identity |
|---------|-----------------|
| claude | none |
| codex | none |
| cursor | upstream_session_id |
| hermes | upstream_session_id |
| openclaw | upstream_session_id |
| opencode | upstream_session_id |
| qwen | none |

`cursor`, `hermes`, `openclaw`, and `opencode` may expose attach or resume commands today, but
this slice only describes the contract. It does not guarantee the supervisor can recover an
upstream id for every run.

### Log contract

`log` describes where evidence comes from and how strong the parser contract is.

- `paths`: registry log paths.
- `stdout_contract`: one of `none`, `text`, `json`, `jsonl`, `mixed`.
- `stderr_contract`: one of `none`, `text`, `json`, `jsonl`, `mixed`.
- `event_timeline`: `stdout_stderr_only` for this slice.

Future session evidence work will extend this into standard event types such as
`model_selected`, `tool_called`, `file_changed`, `approval_required`, `upstream_error`, and
`usage_reported`.

### Usage contract

`usage` tells consumers whether `agentic-os` expects usage extraction and what kind of evidence
backs it.

- `supported`: bool.
- `source`: parser source id from `usage.py` when implemented, otherwise `fallback`.
- `evidence_mode`: one of `json`, `jsonl`, `text_regex`, `none`.
- `fields`: expected fields from `UsageRecord`.

Initial mapping keeps current behavior:

| Harness | evidence_mode |
|---------|---------------|
| claude | text_regex |
| codex | text_regex |
| cursor | text_regex |
| hermes | text_regex |
| openclaw | json |
| opencode | text_regex |
| qwen | text_regex |

### Config contract

`config` standardizes native settings scope.

- `native_supported`: bool.
- `scopes`: ordered list of `user`, `project`, `local` when supported.
- `primary_path`: registry config path.
- `file_kinds`: list of `json`, `toml`, or `markdown`.
- `redacts_secrets`: true for all supported harnesses.

Cursor v2 must explicitly include native JSON files:

- `.cursor/cli-config.json`
- `.cursor/mcp.json`
- `.cursor/hooks.json`

### Surface contract

`surface` describes workflow/catalog scan coverage.

- `mcp_scan`: bool.
- `skill_scan`: bool.
- `command_scan`: bool.
- `hook_scan`: bool.
- `subagent_scan`: bool.
- `native_config_scan`: bool.

This mirrors `catalog.py` and must stay fixture-tested so future harness additions cannot silently
drop a surface class.

### Policy contract

`policy` is intentionally explicit about limits.

- `launch_gate`: true when `agentic-os` can evaluate policy before starting a run.
- `preflight_config_warning`: true when config diffs can warn before launch.
- `runtime_enforcement`: false for this slice.
- `native_policy`: false unless a harness provides enforceable native policy integration.
- `notes`: short human-readable limitation.

This clarifies that current policy is a launch/preflight gate, not a runtime MCP, shell, browser, or
file-write enforcer.

### Capability matrix

`capability_matrix` is a flattened management summary:

- `launch`
- `resume`
- `attach`
- `json_output`
- `mcp_scan`
- `skill_scan`
- `usage_parse`
- `native_policy`
- `sandbox`
- `config_scopes`

`sandbox` is false for all harnesses in this slice unless a registry-backed harness exposes a
stable sandbox contract later.

## Golden Fixtures

Fixtures live under:

```text
tests/fixtures/adapter_contract_v2/
```

Each harness gets one JSON file named `<harness_id>.json`. The file is the expected v2 contract
payload for that harness after `contract_from_agent_v2()` normalization. Tests compare exact
model-dumped JSON with sorted keys.

Fixture tests own these guarantees:

- all seven non-shell harnesses have v2 fixtures;
- each fixture validates as `HarnessAdapterContractV2`;
- API list and show v2 payloads match fixture-backed contracts;
- CLI list and show can request v2;
- unsupported versions fail with a deterministic `400`.

`shell` remains a smoke harness and is not part of the semantic harness matrix.

## API and CLI Behavior

API list endpoint:

```python
@app.get("/harness-contracts")
def list_harness_contracts(version: str = Query(default="v1")) -> dict[str, object]:
    ...
```

API show endpoint:

```python
@app.get("/harness-contracts/{harness_id}")
def show_harness_contract(harness_id: str, version: str = Query(default="v1")) -> dict[str, object]:
    ...
```

CLI:

- `agentctl harness-contracts list --version v2` prints `{"contracts":[...],"count":...}`.
- `agentctl harness-contracts show cursor --version v2` prints one v2 contract.

No existing command output changes unless `--version v2` is passed.

## Testing Strategy

Focused tests:

```bash
rtk uv run pytest tests/test_adapter_contract.py -q
rtk uv run pytest tests/test_api.py -k harness_contract -q
rtk uv run pytest tests/test_cli.py -k harness_contract -q
```

Full gate:

```bash
rtk uv run pytest -q
rtk uv run ruff check .
rtk uv run ruff format --check .
```

## Follow-up Roadmap

1. Session Evidence Model: add standard event evidence beside stdout/stderr logs.
2. Harness Session Model: persist upstream session identity, effective config snapshots,
   artifacts manifest, and resume strategy.
3. Runtime Policy Evolution: preflight policy first, config diff warnings second, runtime proxy or
   native enforcer only after harness-specific evidence exists.

