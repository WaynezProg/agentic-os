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
uv run pytest -q                        # run full test suite (target ~200 tests)
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
agentctl / web UI  --HTTP-->  agentd (FastAPI)
                                 │
                                 ├── Registry   (examples/agents.toml → harness instances)
                                 ├── Store      (SQLite: sessions, events)
                                 ├── JsonlLogStore (.agentic-os/sessions/<id>/{stdout,stderr}.jsonl)
                                 ├── ProcessSupervisor (subprocess.Popen + pgid stop)
                                 ├── MemoryStore       (SQLite: summaries, review, memories)
                                 └── ControlPlaneStore (SQLite: skills, mcp, policy)
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

### Two-stage policy gate (P3.5/P3.6)

The launch path goes through the same policy check in two places:

1. `POST /sessions` (run creation) — evaluates policy before spawning. Denied → HTTP 403 with `decision/reason/session_id` and a shadow session record. `approval_required` → HTTP 409.
2. `POST /sessions/{id}/retry` (P3.6 bypass closure) — re-evaluates policy before respawning. The same response shape; this exists because earlier retry bypassed the gate.

Both responses include `session_id` so the CLI/UI can link to the audit trail (`agentctl sessions events <id>`). When changing run/retry paths, both must call the same evaluator — do not duplicate the policy logic.

### Memory pipeline (P1)

Strictly deterministic. `agentctl memory summarize <session>` builds a summary from session metadata + log line counts. `review create` queues it. `approve` promotes it to a durable `memories` row. No autonomous memory writes — promotion is always explicit.

### Static UI (`apps/web/`)

No build step. `index.html` + `styles.css` + plain `app.js`. The UI is a thin view over the daemon API; the daemon remains the only process owner. Default API URL is `http://127.0.0.1:8767`, editable in the UI.

## Test layout

`tests/` mirrors the module names (`test_api.py`, `test_supervisor.py`, `test_storage.py`, `test_control_plane.py`, `test_memory.py`, `test_policy_aware_run.py`, …). End-to-end coverage in `test_end_to_end.py`. The supervisor tests really fork processes — keep test commands fast and self-terminating (the `shell` smoke uses `/usr/bin/printf`).

When fixing a bug: write the failing test first against the relevant module's test file. When adding API surface: add request/response tests in `test_api.py` and CLI coverage in `test_cli.py`.

## Conventions and gotchas

- **State machine is enforced in `storage.py`.** Do not bypass `update_session_status`; add new transitions to `ALLOWED_TRANSITIONS` if genuinely needed.
- **Secrets are redacted in `control_plane.py`.** Skills/MCP must reference secrets by env-var **name** (`MCP_TOKEN`), never values. URLs and command previews are redacted before storage/display — keep that invariant when adding new fields.
- **No new daemons, supervisors, or process owners.** The single `agentd` process owns subprocesses, logs, DB, and state dir.
- **No LLM calls, no embeddings, no vector DB, no cloud sync.** P1–P5 are intentionally deterministic; see "Limitations" in README.md before proposing additions.
- **`stop` only applies to `running` sessions.** The `shell` smoke exits immediately and cannot be stopped — use the `sleep` registry pattern in README.md for stop demos.
- **Specs are authoritative for scope.** `specs/001-008*.md` define each phase's contract; cross-check before changing behavior, and update the matching spec in the same PR.
- **README phase table is the canonical positioning.** When adding a phase or capability, update both the README phase table and the relevant spec — tests in `test_web.py` assert against this wording.

## Reference: phase scope (P0–P5)

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
