# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`agentic-os` is a local **Harness Manager** substrate — not a harness, not an agent runtime, not a second OpenClaw. It is the management layer underneath harnesses such as OpenClaw, Hermes, Codex, Claude Code, Gemini CLI, and OpenCode. It records configured harness instances, starts and observes harness runs, stores local run evidence, exposes a thin control UI, and evaluates launch-time policy.

The interface labels in code (`/agents`, `/sessions`, `/skills`, `/mcp`, `/policy`) are stable, but the product language is Harness Instance Registry, Harness Run, Shared Capability Catalog, and Harness Launch Policy. Do not rename these endpoints/CLI verbs; do match the product language in docs and specs. See README.md for the wording table.

## Toolchain

- Python 3.12+, managed by `uv` (see `pyproject.toml`, `uv.lock`). Do not pip-install into system Python.
- Commands run under `rtk` in real use (see `scripts/start-local.sh`); tests and lint do not need it.
- Console scripts (exposed via `pyproject.toml`):
  - `agentd` → `agentic_os.daemon:app` (FastAPI daemon)
  - `agentctl` → `agentic_os.cli:app` (Typer CLI client)

## Common commands

```bash
uv sync                                 # install deps
uv run pytest -q                        # run full test suite (~700 tests)
uv run pytest tests/test_api.py -q      # run a single test file
uv run pytest tests/test_api.py::test_health -q   # run a single test
uv run ruff check .                     # lint
uv run ruff format .                    # format

# Local stack (daemon + static UI):
rtk bash scripts/start-local.sh         # agentd on :8767, web UI on :5173
# Or split across terminals:
uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
cd apps/web && python -m http.server 5173
```

CI gate before commit: `uv run pytest -q && uv run ruff check .` (both must pass).

## Architecture (big picture)

Single-process FastAPI daemon (`agentd`) owns all state. The CLI (`agentctl`) and static web UI (`apps/web/`) are thin HTTP clients. There is no background worker, no message bus, no remote DB.

```
agentctl / web UI / desktop  --HTTP-->  agentd (FastAPI)
                                            │
                                            ├── Registry        (agents.toml → harness instances)
                                            ├── Store           (SQLite: sessions, events)
                                            ├── JsonlLogStore   (.agentic-os/sessions/<id>/{stdout,stderr}.jsonl)
                                            ├── ProcessSupervisor (subprocess.Popen + pgid stop)
                                            ├── MemoryStore     (SQLite: summaries, review, memories)
                                            ├── ControlPlaneStore (SQLite: skills, mcp, policy)
                                            ├── WorkspacesStore / RunTemplatesStore (SQLite)
                                            └── RemoteStore     (SQLite: remote devices/tokens; localhost-only admin)
```

State lives entirely under `--state-dir` (default `.agentic-os/`). Each SQLite DB and the JSONL log files are written directly by the daemon process; there is no concurrent writer.

### Module map (`src/agentic_os/`)

- `daemon.py` — Typer entry. Calls `create_app(state_dir, registry_path)` and runs uvicorn.
- `api.py` — All HTTP routes. Pydantic request models at top, `create_app` wires every dependency.
- `cli.py` — `agentctl` subcommands. Talks to the daemon via `client.py`.
- `client.py` — Sync `httpx` wrapper, one method per endpoint.
- `registry.py` — Loads `agents.toml`, renders runnable argv from templates (e.g. `{{message}}`).
- `models.py` — `SessionRecord`, `SessionStatus` enum, `EventRecord`, etc.
- `storage.py` — Sessions/events SQLite store. Owns the **session status state machine** (`ALLOWED_TRANSITIONS`): `queued → running → {stopping, succeeded, failed, stopped}`. Illegal transitions raise.
- `supervisor.py` — `ProcessSupervisor` launches subprocesses with their own process group, tees stdout/stderr to `JsonlLogStore`, transitions session status, and supports `stop_policy = "process_group"` for clean termination. `start_rejected` creates audit-only shadow sessions for denied policy decisions.
- `logs.py` — Append-only JSONL log writer/reader, keyed by session id and stream name.
- `memory.py` + `memory_store.py` — Deterministic session→summary→review→approved memory pipeline. No LLMs, no embeddings.
- `control_plane.py` — Skills/MCP/Policy registries and the **policy evaluator**. Secret redaction lives here (`_redact_*`, `_SECRET_*` patterns). Policy decisions: `allow | deny | approval_required`.
- `safe_edit.py` + `patch_engine.py` + `surface_ops.py` + `harness_config.py` — P10 safe native config editing (dry-run, backup, rollback).
- `catalog.py` + `config_scope.py` — workflow surface catalog and multi-scope config read/merge.
- `profiles.py` + `registry.py` — harness instance profiles and `agents.toml` load/render.
- `workspaces.py` + `run_templates.py` — workspace registry and saved launch templates (P29–P32).
- `tool_discovery.py` + `config_inventory.py` — read-only tool presence and non-secret config summary (P34).
- `attach.py` — discover/bind/attach external sessions (P36).
- `agentic_inventory.py` — read-only OpenClaw/Hermes/n8n capability inventory (P37).
- `live_sessions.py` — read-only scanners over real claude/codex session stores + open-terminal action (P39) + transcript tail preview (P41).
- `capability_inventory.py` — read-only real skills/MCP/plugins/memory names per tool (P40). Names only; secrets never leave the module.
- `import_export.py` — portable setup bundle export/import (P26).
- `remote_store.py` + `remote_access.py` + `remote_gateway.py` + `remote_affordances.py` — remote operator console (P12–P15, P25).
- `evidence.py` + `audit.py` + `fleet.py` + `approvals.py` — session evidence, governance audit, fleet health, approval workflow.

### Two-stage policy gate (P3.5/P3.6)

The launch path goes through the same policy check in two places:

1. `POST /sessions` (run creation) — evaluates policy before spawning. Denied → HTTP 403 with `decision/reason/session_id` and a shadow session record. `approval_required` → HTTP 409.
2. `POST /sessions/{id}/retry` (P3.6 bypass closure) — re-evaluates policy before respawning. The same response shape; this exists because earlier retry bypassed the gate.

Both responses include `session_id` so the CLI/UI can link to the audit trail (`agentctl sessions events <id>`). When changing run/retry paths, both must call the same evaluator — do not duplicate the policy logic.

### Memory pipeline (P1)

Strictly deterministic. `agentctl memory summarize <session>` builds a summary from session metadata + log line counts. `review create` queues it. `approve` promotes it to a durable `memories` row. No autonomous memory writes — promotion is always explicit.

### Static UI (`apps/web/`)

No build step. `index.html` + `styles.css` + `api.js` (endpoint registry) + `app.js` (shell) + `ui/*.js` feature modules. The UI is a thin view over the daemon API; the daemon remains the only process owner. Default API URL is `http://127.0.0.1:8767`, editable in the UI. Remote desktop mode proxies writes through Tauri `connection_api_fetch` and gates admin actions via `remote_affordances`.

Notable `ui/` modules: `catalog-editor`, `config-editor`, `profile-editor`, `registry-editor`, `control-plane-editor`, `approval-workbench`, `remote-console`, `workspace-manager`, `provider-switchboard`, `run-template-launcher`, `daily-dashboard`, `dashboard-v2`, `tool-discovery`, `vibe-coding-launcher`, `agentic-inventory`, `discover-bind`, `product-polish`.

Dual-track operator surfaces (P34–P39): **工具** tab (`tool-discovery.js`), **Vibe Coding** tab (`vibe-coding-launcher.js`), **Agentic** tab (`agentic-inventory.js` + `discover-bind.js`), **總覽** tab (`daily-dashboard.js` + `dashboard-v2.js` two-column layout, with the P39 Live Sessions radar card fed by `GET /sessions/live`).

### Desktop app (`apps/desktop/`)

Tauri shell (P11+): tray, embedded static UI, local `agentd` lifecycle. Packaged `.app` in P11.5. iOS companion in P12.5. See README “Desktop app” for `pnpm desktop:dev` / `desktop:build`.

### CodeGraph

This repo is indexed (`.codegraph/`). Prefer `codegraph_*` MCP tools for structural questions (symbols, callers, routes, impact). Use grep/read only for literal strings, copy, or files flagged stale in the codegraph banner. Full tool-selection rules: `.cursor/rules/codegraph.mdc`.

## Test layout

`tests/` mirrors the module names (`test_api.py`, `test_supervisor.py`, `test_storage.py`, `test_control_plane.py`, `test_memory.py`, `test_policy_aware_run.py`, …). End-to-end coverage in `test_end_to_end.py`. The supervisor tests really fork processes — keep test commands fast and self-terminating (the `shell` smoke uses `/usr/bin/printf`).

When fixing a bug: write the failing test first against the relevant module's test file. When adding API surface: add request/response tests in `test_api.py` and CLI coverage in `test_cli.py`.

## Conventions and gotchas

- **State machine is enforced in `storage.py`.** Do not bypass `update_session_status`; add new transitions to `ALLOWED_TRANSITIONS` if genuinely needed.
- **Secrets are redacted in `control_plane.py`.** Skills/MCP must reference secrets by env-var **name** (`MCP_TOKEN`), never values. URLs and command previews are redacted before storage/display — keep that invariant when adding new fields.
- **No new daemons, supervisors, or process owners.** The single `agentd` process owns subprocesses, logs, DB, and state dir.
- **No LLM calls, no embeddings, no vector DB, no cloud sync.** P1-P9 are intentionally deterministic; see "Limitations" in README.md before proposing additions.
- **`stop` only applies to `running` sessions.** The `shell` smoke exits immediately and cannot be stopped — use the `sleep` registry pattern in README.md for stop demos.
- **Specs are authoritative for scope.** `specs/001-058*.md` define each phase's contract; cross-check before changing behavior, and update the matching spec in the same PR.
- **README phase table is the canonical positioning for P0–P33.** When adding a phase or capability, update both the README phase table and the relevant spec — tests in `test_web.py` assert against this wording. P34–P42 (dual-track product) specs: `054`–`062`.

## Reference: phase scope (P0-P9)

| Phase | Owns | Does not own |
|-------|------|--------------|
| P0 | daemon, CLI, harness registry, run lifecycle, logs, artifacts | harness internals, planning, tool execution |
| P1 | deterministic session summaries, review queue, approved memory | LLM summaries, embeddings, RAG |
| P2 | static control UI over daemon APIs | browser subprocess, IDE, chat UI |
| P3 | skills/MCP catalog, policy registry, policy evaluator | installing capabilities, starting MCP servers, live tool enforcement |
| P3.5 | launch policy gate on `POST /sessions` | per-tool runtime enforcement |
| P3.6 | retry policy gate, CLI/UI error display with decision+session_id | approval workflow, in-harness enforcement |
| P3.7 | harness instance profile schema | harness internals, planning, tool execution |
| P4 | fleet control plane goals, SLO, non-goals, governance principles | health probe implementation, drift detection, audit workflow |
| P5 | fleet health probes, drift events, capacity 429, fleet API/CLI/UI | audit workflow, governance closed loop, deprecation workflow |
| P6 | governance audit events, deprecation lifecycle, bounded log reads, policy coverage | multi-user RBAC, cloud sync, approval workflow UX |
| P7 | approval requests, approve/reject API/CLI/UI, audit links | RBAC, notifications, live in-harness tool approval |
| P8 | SLO benchmark command, diagnostics resource snapshot, JSON reports | hosted telemetry, continuous monitoring, automatic tuning |
| P9 | deprecation reason/replacement/sunset metadata, un-deprecate, auto-disable | package management, delete/purge workflow, scheduler |

P10–P33 (remote access, safe editing, editors, approval workbench, workspace/templates, daily dashboard) are **complete** — see README phase table for per-phase owns/does-not-own. Do not duplicate that table here.

### Dual-track product (P34–P42, on `feat/p34-p38-dual-track-product`)

| Phase | Owns | Does not own |
|-------|------|--------------|
| P34 | `tool_discovery` + `config_inventory`, `GET /tools/discovery`, `GET /tools/inventory`, `tool_kind` on registry agents | bidirectional config sync, secret reads, launching tools |
| P35 | Vibe Coding UI launch/stop/retry/logs/evidence for Codex/Claude Code | chat UI, agentic runtime launch |
| P36 | `attach.py`, `POST /sessions/discover`, `POST /sessions/bind`, `POST /sessions/{id}/attach` | filesystem session sniffing, modifying external runtimes |
| P37 | `agentic_inventory.py`, `GET /agentic/inventory`, Agentic tab inventory UI | starting/stopping OpenClaw/Hermes/n8n |
| P38 | `dashboard-v2.js` two-column 總覽 (Vibe Coding left, Agentic Runtime right); frontend aggregation of existing APIs | new backend `/dashboard/v2` aggregator (spec prefers client-side compose) |
| P39 | `live_sessions.py` read-only scanners over `~/.claude/projects` + `~/.codex/sessions`, `GET /sessions/live`, `POST /sessions/live/open-terminal` (macOS), dashboard Live Sessions card, `agentctl sessions live` | writing to external stores, gemini/qwen/opencode scanners, file watching, cross-machine |
| P40 | `capability_inventory.py`, `GET /tools/capabilities`, `agentctl tools capabilities`, 工具 tab capability cards | writing tool configs, secret values (names only), memory content reads |
| P41 | `read_transcript_tail` in `live_sessions.py`, `GET /sessions/live/transcript` (root-bounded path validation), radar inline transcript panel | sending messages, full-transcript search/pagination |
| P42 | `mcp_alignment.py` cross-tool matrix + copy/remove through `SafeEditEngine` (dry-run default, backup/rollback, values never in responses), `GET /tools/mcp/matrix`, `POST /tools/mcp/{copy,remove}`, `agentctl tools mcp-*`, 工具 tab matrix UI | creating/editing server definitions, skills/plugins writes, bulk sync, project scopes |
