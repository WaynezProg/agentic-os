# 018 — Multi-Harness Registry Pack

Status: Implemented
Date: 2026-05-30
Depends on: 007 (Harness Instance Profile — schema in code)
Blocks: 019, 020, 021, 023

## Positioning

Populate `examples/agents.toml` with six real harness instances and validate
that registry loading, profile API, and fleet health probes produce meaningful
results for every instance.

P3.7 profile fields are **implemented** in `AgentDefinition` and
`_harness_profile()`; 018 lands the data and verification, not new schema.

| Phase | Owns | Does not own |
|-------|------|--------------|
| P3.7+ | six-instance registry, profile validation, fleet probe coverage | resume, PTY, writing harness config files |

## Harness instance table

Canonical `id` matches future catalog key (019). One row per harness type in
`examples/agents.toml`. `shell` smoke agent remains for CI.

### Field contract (007 mapping)

| Profile field | TOML key | Required for 018 |
|---------------|----------|------------------|
| id | `id` | yes |
| name | `label` | yes |
| launch_command | `command` | yes |
| health_command | `health_command` | yes |
| attach_command | `attach_command` | optional (needed for 023 gate) |
| config_path | `config_path` | yes |
| workspace_roots | `workspace_roots` | yes (≥1 path) |
| log_paths | `log_paths` | yes (≥1 path or explicit `[]` with comment) |
| default_provider | `default_provider` | yes |
| — | `version_command` | yes (fleet drift) |
| — | `config_fingerprint_command` | yes (fleet drift) |
| — | `cwd_mode` | per harness |
| — | `stop_policy` | `process_group` |

### Six harness command matrix

Commands verified against Wayne's machine (2026-05-30). `{{message}}` is the
registry template token.

| id | launch (`command`) | health | version | config_fingerprint | config_path | log_paths | default_provider | attach (023 prep) |
|----|-------------------|--------|---------|-------------------|-------------|-----------|------------------|-------------------|
| `claude` | `claude -p {{message}} --output-format text` | `claude --version` | `claude --version` | `claude --version` | `~/.claude` | `~/.claude/projects` | `anthropic` | — (attach deferred to 023) |
| `codex` | `codex exec {{message}}` | `codex --version` | `codex --version` | `codex --version` | `~/.codex` | `~/.codex/log` | `openai` | — |
| `opencode` | `opencode run {{message}}` | `opencode --version` | `opencode --version` | `opencode --version` | `~/.config/opencode` | `~/.local/share/opencode/log` | `openai` | `opencode attach` (023) |
| `qwen` | `qwen {{message}}` | `qwen --version` | `qwen --version` | `qwen --version` | `~/.qwen` | `~/.qwen/debug` | `qwen` | — |
| `openclaw` | `openclaw agent --message {{message}} --json` | `openclaw status --json` | `openclaw --version` | `openclaw status --json` | `~/.openclaw` | `~/.openclaw/logs` | `openai` | `openclaw attach` |
| `hermes` | `hermes chat --query {{message}} --quiet --source agentic-os` | `hermes status` | `hermes --version` | `hermes status` | `~/.hermes` | `~/.hermes/logs` | `openai` | `hermes --resume` |

**Notes:**

- `config_fingerprint_command` uses `--version` for JSON/TOML CLI family; openclaw
  and hermes use status output for meaningful drift (P5 fleet goal).
- Upstream CLI failures (auth, gateway, model) are acceptable smoke outcomes if
  agentic-os captured stdout/stderr and session record exists.
- **Six-harness run smoke is manual only** (`scripts/smoke-six-harnesses.sh`) —
  not part of `pytest` (CI keeps `shell` only).
- `shell` agent unchanged for deterministic CI.
- Registry validation rejects duplicate `id`, empty `command`, missing
  `health_command` on non-shell agents.

## Registry validation

Add `validate_registry(agents: dict[str, AgentDefinition]) -> list[str]` in
`registry.py` (or `registry_validate.py` if file grows):

- Non-`shell` agents must have: `health_command`, `config_path`,
  `default_provider`, `version_command`, `config_fingerprint_command`.
- `workspace_roots` and `log_paths` must be lists (empty log_paths allowed with
  warning in validation output, not hard fail).
- `config_path` must expand to existing path **at validate time** only when
  `--strict-paths` flag passed (default off — CI uses stub paths in tests).

Expose validation via:

- `GET /harnesses/validate` → `{ "ok": bool, "warnings": [], "errors": [] }`
- `agentctl harnesses validate`

## Fleet probe coverage

Every non-shell instance must appear in `GET /fleet/health` after at least one
manual or automated probe cycle. Acceptance does not require all probes
`healthy` — `unreachable` with captured stderr is valid for harnesses missing
auth.

## Does not own

- Resume / fork / PTY attach execution
- Modifying harness-native config files
- Catalog scope scanning (019)
- Harness-native config read (020)

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Six harness rows in `examples/agents.toml` with full profile fields | File review + `test_registry.py` |
| `agentctl agents list` shows six + shell | CLI smoke |
| Each harness: one `agentctl run <id> --message "OK"` creates session | Manual or scripted smoke; session id + logs |
| `GET /harnesses` returns profile for each id | `test_api.py` |
| `GET /harnesses/validate` returns `ok: true` for default registry | API test |
| Fleet health table lists all six instance ids | `agentctl fleet health` after probe |
| 007 spec status → Implemented via 018 | Spec debt PR |

## Implementation plan

`docs/superpowers/plans/2026-05-30-018-multi-harness-registry-pack.md`
