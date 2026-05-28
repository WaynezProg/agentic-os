# P3 Shared Capability Catalog And Harness Launch Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the durable local Shared Capability Catalog and Harness Launch Policy registry with deterministic policy evaluation while preserving `agentic-os` as a Harness Manager substrate.

**Architecture:** P3 adds a SQLite-backed management store and a pure evaluator that reads stored catalog/policy state but never executes external tools. The daemon exposes CRUD/read/evaluate routes, `agentctl` wraps those routes, and the static UI displays catalog and evaluation state by calling daemon API only.

**Tech Stack:** Python 3.12, FastAPI, Typer, SQLite, pytest, ruff, static HTML/CSS/JavaScript. No new runtime dependency and no Python version change.

---

## Context

P0 provides Harness Instance Registry, Harness Sessions, logs, and retries. P1 provides deterministic run evidence promotion. P2 provides a no-build thin UI and placeholder `GET /skills` plus `GET /mcp`. P3 replaces those placeholders with durable Shared Capability Catalog and Harness Launch Policy functions, but it must not install capabilities, start MCP servers, enforce live harness loops, or become a second orchestrator.

## File Structure

- `specs/004-skills-mcp-policy.md`: P3 contract.
- `src/agentic_os/control_plane.py`: registry records, SQLite schema/store, redaction, deterministic policy evaluator.
- `src/agentic_os/api.py`: Shared Capability Catalog and Harness Launch Policy API routes.
- `src/agentic_os/client.py`: HTTP client methods for P3 routes.
- `src/agentic_os/cli.py`: `skills`, `mcp`, and `policy` CLI groups.
- `apps/web/index.html`: expanded Skills / MCP interface tab with Shared Capability Catalog summary and evaluator controls.
- `apps/web/app.js`: API calls and rendering for registry/policy/evaluation.
- `apps/web/styles.css`: layout support for evaluation controls without changing the thin UI boundary.
- `tests/test_control_plane.py`: store, redaction, and evaluator unit tests.
- `tests/test_api.py`: P3 daemon route tests.
- `tests/test_cli.py`: P3 CLI tests.
- `tests/test_web.py`: static UI contract tests.
- `README.md`: P3 daemon, CLI, UI usage and limits.

## Subagent Protocol

Each implementation slice requires:

- fresh pre-review subagent before implementation;
- local TDD red-green cycle for the slice;
- fresh post-slice code review subagent;
- fix blocking findings before moving to the next slice.

Do not dispatch multiple implementation slices in parallel because API, client,
CLI, and UI contracts build on the same schema names.

## Task 1: Control-Plane Store And Evaluator

**Files:**
- Create: `src/agentic_os/control_plane.py`
- Create: `tests/test_control_plane.py`

- [ ] **Step 1: Pre-review**

Dispatch a fresh subagent to review this slice against `specs/004-skills-mcp-policy.md`, focused on schema shape, redaction, deterministic evaluation, and non-orchestrator boundaries.

- [ ] **Step 2: RED tests**

Write failing tests for:

- skill-like catalog upsert/list/show/disable durability;
- MCP catalog upsert/list/show/disable durability;
- command preview and URL redaction before storage;
- env key storage without env values;
- missing policy denies;
- disabled policy denies;
- enabled registry + matching policy allows;
- unknown or disabled requested catalog capability denies;
- model allowlist mismatch denies;
- cwd outside scope denies;
- readonly write tool denies;
- approval-required tool returns `approval_required`;
- same input produces the same decision and reason.

Run:

```bash
rtk uv run pytest tests/test_control_plane.py -q
```

Expected: FAIL with missing `agentic_os.control_plane`.

- [ ] **Step 3: GREEN implementation**

Implement `ControlPlaneStore` and pure `evaluate_policy` logic in
`src/agentic_os/control_plane.py`. Use SQLite tables:

```text
skills
mcp_servers
agent_policies
```

Use dataclasses for stored records and Pydantic models only at API boundary.
Never store env values. Store MCP command preview only after redaction.

- [ ] **Step 4: Verify slice**

Run:

```bash
rtk uv run pytest tests/test_control_plane.py -q
rtk uv run pytest -q
rtk uv run ruff check .
```

- [ ] **Step 5: Post-review**

Dispatch a fresh code-review subagent for `src/agentic_os/control_plane.py` and
`tests/test_control_plane.py`. Blocking findings must be fixed and rechecked.

## Task 2: Daemon API And Client Contract

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `src/agentic_os/client.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Pre-review**

Dispatch a fresh subagent to review endpoint names, request/response shape, and
client path-id validation before writing code.

- [ ] **Step 2: RED API/client tests**

Add failing tests for:

- `GET /skills`, `GET /skills/{id}`, `POST /skills/{id}`, `POST /skills/{id}/disable`;
- `GET /mcp`, `GET /mcp/{id}`, `POST /mcp/{id}`, `POST /mcp/{id}/disable`;
- `GET /policy`, `GET /policy/{agent_id}`, `POST /policy/{agent_id}`, `POST /policy/evaluate`;
- unknown read routes return `404`;
- unsafe ids are rejected by `AgenticClient`;
- client methods build expected HTTP requests.

Run:

```bash
rtk uv run pytest tests/test_api.py tests/test_cli.py -q
```

Expected: FAIL with missing routes/client methods.

- [ ] **Step 3: GREEN API/client implementation**

Initialize `ControlPlaneStore(state_dir / "agentic-os.db")` in `create_app`,
call `init()`, and wire P3 routes. Extend `AgenticClient` with matching methods
and safe path-id validation for catalog and policy ids.

- [ ] **Step 4: Verify slice**

Run:

```bash
rtk uv run pytest tests/test_control_plane.py tests/test_api.py tests/test_cli.py -q
rtk uv run pytest -q
rtk uv run ruff check .
```

- [ ] **Step 5: Post-review**

Dispatch a fresh code-review subagent for the API/client changes and fix
blocking findings.

## Task 3: CLI Commands

**Files:**
- Modify: `src/agentic_os/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Pre-review**

Dispatch a fresh subagent to review command names and concise tabular output.

- [ ] **Step 2: RED CLI tests**

Add failing tests for:

- `agentctl skills list`
- `agentctl skills show <id>`
- `agentctl skills upsert <id> --label ...`
- `agentctl skills disable <id>`
- `agentctl mcp list`
- `agentctl mcp show <id>`
- `agentctl mcp upsert <id> --label ...`
- `agentctl mcp disable <id>`
- `agentctl policy show [agent_id]`
- `agentctl policy set <agent_id> ...`
- `agentctl policy evaluate <agent_id> ...`

Run:

```bash
rtk uv run pytest tests/test_cli.py -q
```

Expected: FAIL with missing command groups.

- [ ] **Step 3: GREEN CLI implementation**

Add `skills`, `mcp`, and `policy` Typer groups. Keep list output tab-separated
and concise. Print show/evaluate results as JSON.

- [ ] **Step 4: Verify slice**

Run:

```bash
rtk uv run pytest tests/test_cli.py -q
rtk uv run pytest -q
rtk uv run ruff check .
```

- [ ] **Step 5: Post-review**

Dispatch a fresh code-review subagent for CLI behavior and fix blocking
findings.

## Task 4: Thin UI And README

**Files:**
- Modify: `apps/web/index.html`
- Modify: `apps/web/app.js`
- Modify: `apps/web/styles.css`
- Modify: `tests/test_web.py`
- Modify: `README.md`

- [ ] **Step 1: Pre-review**

Dispatch a fresh subagent to review thin-UI constraints: browser must call
daemon API only, not spawn processes, not parse large logs, and not become an
IDE.

- [ ] **Step 2: RED UI/docs tests**

Add failing tests that require:

- Shared Capability Catalog skill-like table shows id, label, enabled, source, tags;
- Shared Capability Catalog MCP table shows id, label, enabled, transport, command preview;
- policy summary area exists;
- evaluation form/result area exists;
- JavaScript references P3 endpoints;
- forbidden process-spawn tokens remain absent;
- README documents daemon, CLI, UI paths and P3 non-goals.

Run:

```bash
rtk uv run pytest tests/test_web.py -q
```

Expected: FAIL with missing P3 UI elements.

- [ ] **Step 3: GREEN UI/docs implementation**

Update the Skills / MCP tab to render Shared Capability Catalog tables, Harness
Launch Policy summary, and a small deterministic evaluation form. The form calls
`POST /policy/evaluate` and renders the returned decision and reason. Update
README with P3 usage and explicit limits.

- [ ] **Step 4: Verify slice**

Run:

```bash
rtk uv run pytest tests/test_web.py -q
rtk uv run pytest -q
rtk uv run ruff check .
```

- [ ] **Step 5: Post-review**

Dispatch a fresh code-review subagent for UI/docs changes and fix blocking
findings.

## Task 5: Final Integration Review

**Files:**
- All changed P3 files.

- [ ] **Step 1: Request final code review**

Use `superpowers:requesting-code-review` and dispatch a fresh final reviewer
for the complete P3 implementation. The reviewer must check Done When items,
scope boundaries, and stop conditions.

- [ ] **Step 2: Fix blocking findings**

If the final reviewer reports blocking findings, fix them with TDD where code
behavior changes and rerun targeted tests.

- [ ] **Step 3: Verification before completion**

Use `superpowers:verification-before-completion`, then run:

```bash
rtk uv run pytest -q
rtk uv run ruff check .
rtk proxy git status --short
```

- [ ] **Step 4: Completion audit**

Map each Done When item to concrete evidence from files, tests, and command
output. Do not mark the goal complete unless every item is proven.
