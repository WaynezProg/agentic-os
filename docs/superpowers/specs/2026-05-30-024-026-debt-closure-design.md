# 024–026 Debt Closure Design

Date: 2026-05-30  
Status: Approved (brainstorm 2026-05-30)  
Author: agentic-os team  
Supersedes gaps in: `docs/superpowers/specs/2026-05-30-harness-manager-extension-design.md`

## Summary

Close the remaining gaps after the initial 024–026 implementation (`ea4590d`):
add **Cursor** as the seventh harness, complete **profile write** APIs, ship **text-first usage parsers**
for Claude/Codex/OpenCode/Cursor, wire **real quota semantics** from `max_tokens_budget`, and sync
docs/CI.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Cursor integration | Seventh registry harness with headless `cursor agent` (option A) |
| Launch output | Start with `--output-format text`; migrate registry to `json` later without API changes (option C) |
| Profile writes | Default **local** `profiles.toml`; `--global` / `scope=global` for home (option B) |
| Quotas | Join `usage_records` to profile `max_tokens_budget`; expose limit/used/remaining/status (option A) |

## Non-goals

- Provider billing APIs, `limit_cost_usd` enforcement, or cloud sync
- Cursor `--output-format json` switch in this closure (documented follow-up only)
- UI profile editor, RBAC, in-harness tool approval changes
- Renaming existing API route labels (`/agents`, `/sessions`, etc.)

## Delivery slices (recommended PR order)

1. **Cursor pack** — registry, contract, catalog, tests, manual smoke script  
2. **Profile write** — `POST /profiles`, `agentctl profiles set`  
3. **Usage parsers + quotas** — harness parsers + `/usage/quotas` semantics  
4. **Docs + CI** — formal specs 024–026, README phase table, GitHub Actions  

---

## 1. Cursor harness (`id = cursor`)

### Registry (`examples/agents.toml`)

Verified against Cursor 3.6.21 on Wayne's machine:

```toml
[[agents]]
id = "cursor"
label = "Cursor Agent"
command = ["cursor", "agent", "--print", "--trust", "--output-format", "text", "{{message}}"]
cwd_mode = "required"
stop_policy = "process_group"
health_command = ["cursor", "agent", "-v"]
version_command = ["cursor", "agent", "-v"]
config_fingerprint_command = ["cursor", "agent", "-v"]
config_path = "~/.cursor"
workspace_roots = ["~/bootstrap", "~/work"]
log_paths = ["~/.cursor/projects"]
default_provider = "cursor"
attach_command = ["cursor", "agent", "--resume"]
```

Supervisor sets process `cwd`; `cursor agent` defaults `--workspace` to cwd. Optional
`--workspace` in argv is a follow-up if attach/resume needs explicit paths.

### Catalog

Add to `_HARNESS_SCOPES` in `catalog.py`:

```python
"cursor": {
    "user": ".cursor",
    "project": ".cursor",
    "local": ".cursor/local",
},
```

Bump `SUPPORTED_HARNESSES` to seven entries everywhere tests assert the tuple (catalog,
contract list, unknown-harness 400 bodies).

### Adapter contract

- `launch.supported = true`
- `supports_attach = true` (`--resume`)
- `supports_session_id = false` in v1 (until log parser extracts chat id)
- `required_env`: `CURSOR_API_KEY` (name only; never store value)
- `error_modes`: same v1 set as other harnesses

### Verification

- **pytest**: contract count, catalog scan smoke with fixture `.cursor` tree, API 400 `supported` list length 7  
- **manual**: `scripts/smoke-seven-harnesses.sh` (not in CI; same policy as 018 six-harness smoke)

---

## 2. Profile write (`025` completion)

### API

`POST /profiles`

| Query | Default | Behavior |
|-------|---------|----------|
| `scope` | `local` | `local` → `<cwd>/.agentic-os/profiles.toml`; `global` → `~/.agentic-os/profiles.toml` |
| `cwd` | optional | Resolves local path (same as `GET /profiles`) |

Body: `RunProfileInput` (existing Pydantic model). **Upsert** by `name`.

Responses: `201` with saved profile dict; `400` invalid scope; `422` validation errors.

No `DELETE` in this closure (YAGNI).

### CLI

```
agentctl profiles set --name <name> --harness <id> --provider <p> --model <m> \
  [--global] [--cwd <path>] [--message-prefix ...] [--max-tokens-budget N] ...
```

Maps to `POST /profiles` with matching `scope` / `cwd`.

### Implementation

`profiles.upsert_run_profile(name, payload, *, scope, cwd)` using existing `_read_bundle` /
`_write_bundle` (same file format as `bind_project_profile`).

Read precedence unchanged: global profiles loaded first, local overrides same `name`.

---

## 3. Usage parsers (`026` completion)

### New parsers (text-first)

| Parser | `harness_id` | `source` tag | Strategy |
|--------|--------------|--------------|----------|
| `ClaudeUsageParser` | `claude` | `claude` | JSONL lines + `usage` object; regex fallback |
| `CodexUsageParser` | `codex` | `codex` | Same pattern family as Codex CLI stdout |
| `OpencodeUsageParser` | `opencode` | `opencode` | OpenCode log line patterns |
| `CursorUsageParser` | `cursor` | `cursor` | Text v1: token regex + optional JSON lines; upgrade when registry uses `json` |

Register in `_PARSERS` **before** `FallbackUsageParser`. Keep `OpenclawUsageParser` unchanged.

### Supervisor metadata

Ensure `run_profile`, `provider`, `model` on stored `UsageRecord` match session resolved
fields (already partially done in `_collect_usage_for_session`; extend tests).

### Cursor json follow-up (out of scope)

When switching registry to `--output-format json`, only change:
`examples/agents.toml` argv and `CursorUsageParser` extraction — no API version bump.

---

## 4. Quota semantics (`026` completion)

Replace misleading `/usage/quotas` behavior (daily calendar rollup / raw session list).

### `GET /usage/quotas?scope=daily|session`

**`scope=daily`**

For each `run_profile` name that exists in merged profiles (global + local for request `cwd`)
with `max_tokens_budget IS NOT NULL`:

- `used_tokens` = `SUM(total_tokens)` from `usage_records` where `run_profile` matches and
  `date(updated_at) = date('now')` (UTC date in SQLite)
- `limit_tokens` = profile.`max_tokens_budget`
- `remaining_tokens` = `max(0, limit - used)`
- `status`: `ok` (<80%), `warning` (≥80%), `exceeded` (≥100%); profiles without budget omitted

Include `harness_id` from profile definition.

**`scope=session`**

One row per `usage_records` row where the linked profile has a budget:

- `session_id`, `run_profile`, `used_tokens` = row.`total_tokens`, `limit_tokens`, `remaining_tokens`, `status`

Profiles without budget: omitted (not `unlimited` rows).

### Breaking change

Response shape changes; update `tests/test_api.py`, `tests/test_usage.py`, CLI client mocks.
Do **not** keep old daily rollup under `/usage/quotas` (YAGNI). Consumers needing day totals
use `/usage/summary` filters.

### Dead code

Remove or repurpose unused `UsageStore.quotas()` provider/model aggregation if still present.

---

## 5. Documentation and CI

### Spec files

Create with `Status: Implemented`:

- `specs/024-adapter-contract-v1.md` — pointer to `adapter_contract.py` + tests  
- `specs/025-run-project-profile.md` — includes profile write completion  
- `specs/026-usage-ledger.md` — parsers + quota semantics  

Update `docs/superpowers/specs/2026-05-30-harness-manager-extension-design.md` → **Implemented**,
note Cursor seventh harness and quota behavior.

Update `specs/018-multi-harness-registry-pack.md` harness table with `cursor` row.

### README

Add phase row (e.g. **P10**) summarizing 024–026 closure; keep P0–P9+ table intact.
Limitations: quotas are local budget tracking, not provider billing.

### CI

Add `.github/workflows/ci.yml`:

```yaml
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run pytest -q
      - run: uv run ruff check .
```

---

## 6. Testing strategy

| Area | Tests |
|------|-------|
| Cursor | `test_catalog` seven harnesses; `test_adapter_contract` includes cursor; API contract list length |
| Profiles | `test_profiles` upsert local/global; `test_api` POST /profiles; `test_cli` profiles set |
| Parsers | `test_usage` per harness fixture stdout snippets |
| Quotas | `test_usage` budget warning/exceeded; `test_api` quotas scope + shape |
| Docs | `test_web.py` phase wording if README table asserted |

Run gate: `uv run pytest -q && uv run ruff check .`

---

## Risk register

| Risk | Mitigation |
|------|------------|
| Harness stdout formats drift | Text parsers + fallback; `source` field for audit |
| `/usage/quotas` breaking consumers | Single release note in spec 026; tests lock new shape |
| Cursor headless needs trust/API key | Document `CURSOR_API_KEY`; `--trust` in default argv |
| CI without cursor binary | pytest uses fixtures only; cursor smoke manual |

## References

- Initial extension design: `docs/superpowers/specs/2026-05-30-harness-manager-extension-design.md`
- Implementation commit: `ea4590d` (contracts, profiles read, usage ledger v1)
- Plan: `docs/superpowers/plans/2026-05-30-024-026-debt-closure.md`
