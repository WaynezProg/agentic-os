# P9 Deprecation Lifecycle Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete P6 deprecation by adding structured metadata, un-deprecate endpoints, and deterministic sunset auto-disable.

**Architecture:** Extend `ControlPlaneStore` schema and records, keep enforcement opportunistic inside existing store/API calls, and record all lifecycle changes in the existing audit trail. No scheduler, package manager, or delete workflow is added.

**Tech Stack:** Python 3.12, FastAPI, Typer, SQLite migrations, pytest, ruff, static HTML/CSS/JavaScript.

---

## File Structure

- Modify: `src/agentic_os/control_plane.py` -- metadata columns, deprecate payloads, un-deprecate, sunset enforcement.
- Modify: `src/agentic_os/api.py` -- request models, deprecate bodies, un-deprecate endpoints, audit metadata.
- Modify: `src/agentic_os/client.py` -- un-deprecate methods and deprecate payload support.
- Modify: `src/agentic_os/cli.py` -- deprecate flags and un-deprecate commands.
- Modify: `apps/web/app.js`, `apps/web/index.html` -- show deprecation metadata.
- Modify: `tests/test_control_plane.py` -- store lifecycle tests.
- Modify: `tests/test_api.py` -- API lifecycle and audit tests.
- Modify: `tests/test_cli.py` -- CLI lifecycle tests.
- Modify: `tests/test_web.py` -- UI contract tests.
- Modify: `README.md`, `CLAUDE.md` -- P9 usage and scope.

### Task 1: Control-plane metadata and un-deprecate

**Files:**
- Modify: `src/agentic_os/control_plane.py`
- Test: `tests/test_control_plane.py`

- [ ] **Step 1: Write failing store tests**

Add tests that deprecate a skill with reason/replacement/sunset, assert fields
round-trip, then un-deprecate and assert metadata clears.

- [ ] **Step 2: Run store tests**

Run: `rtk uv run pytest tests/test_control_plane.py -q`

Expected: FAIL because records do not expose metadata and un-deprecate methods
do not exist.

- [ ] **Step 3: Add dataclass fields**

Add to `SkillRecord`, `McpServerRecord`, and `PolicyRecord`:

```python
deprecated_at: str | None
deprecation_reason: str
replacement_id: str | None
sunset_at: str | None
```

- [ ] **Step 4: Add migrations**

In `ControlPlaneStore.init()`, call `_add_column_if_missing` for each new
column on `skills`, `mcp_servers`, and `agent_policies`.

- [ ] **Step 5: Add lifecycle methods**

Add `undeprecate_skill`, `undeprecate_mcp_server`, `undeprecate_policy`.
Update existing deprecate methods to accept reason, replacement_id, and
sunset_at.

- [ ] **Step 6: Run store tests**

Run: `rtk uv run pytest tests/test_control_plane.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agentic_os/control_plane.py tests/test_control_plane.py
git commit -m "feat(p9): add deprecation metadata and undeprecate"
```

### Task 2: Sunset auto-disable

**Files:**
- Modify: `src/agentic_os/control_plane.py`
- Test: `tests/test_control_plane.py`

- [ ] **Step 1: Write failing sunset tests**

Add tests asserting an enabled deprecated skill with past `sunset_at` becomes
disabled when listed or evaluated.

- [ ] **Step 2: Run sunset tests**

Run: `rtk uv run pytest tests/test_control_plane.py -q`

Expected: FAIL because sunset is not enforced.

- [ ] **Step 3: Implement opportunistic enforcement**

Add a private `apply_sunset(now: datetime | None = None)` method that disables
expired deprecated rows and returns changed ids grouped by domain. Call it at
the beginning of list/show/evaluate/mutate methods.

- [ ] **Step 4: Run control-plane tests**

Run: `rtk uv run pytest tests/test_control_plane.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/control_plane.py tests/test_control_plane.py
git commit -m "feat(p9): enforce deprecation sunset"
```

### Task 3: API and audit lifecycle

**Files:**
- Modify: `src/agentic_os/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests for:

- `POST /skills/{id}/deprecate` with JSON body;
- `POST /skills/{id}/undeprecate`;
- equivalent MCP and policy endpoints;
- audit metadata includes reason, replacement, sunset, before/after;
- auto-disable after sunset records `*_auto_disabled_after_sunset`.

- [ ] **Step 2: Run API tests**

Run: `rtk uv run pytest tests/test_api.py -q`

Expected: FAIL because request bodies and un-deprecate routes do not exist.

- [ ] **Step 3: Add request model**

Add:

```python
class DeprecationRequest(BaseModel):
    reason: str = ""
    replacement_id: str | None = None
    sunset_at: str | None = None
```

- [ ] **Step 4: Update deprecate endpoints and add un-deprecate endpoints**

Wire all three domains through control-plane lifecycle methods and audit
records.

- [ ] **Step 5: Run API tests**

Run: `rtk uv run pytest tests/test_api.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat(p9): expose deprecation lifecycle API"
```

### Task 4: CLI and client

**Files:**
- Modify: `src/agentic_os/client.py`
- Modify: `src/agentic_os/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Add tests for:

```bash
agentctl skills deprecate reviewer --reason "use v2" --replacement reviewer-v2 --sunset 2026-06-30T00:00:00Z
agentctl skills undeprecate reviewer
agentctl mcp undeprecate filesystem
agentctl policy undeprecate shell
```

- [ ] **Step 2: Run CLI tests**

Run: `rtk uv run pytest tests/test_cli.py -q`

Expected: FAIL.

- [ ] **Step 3: Add client and CLI support**

Extend deprecate client methods to accept payloads and add un-deprecate client
methods. Add Typer flags to deprecate commands and new `undeprecate` commands.

- [ ] **Step 4: Run CLI tests**

Run: `rtk uv run pytest tests/test_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/client.py src/agentic_os/cli.py tests/test_cli.py
git commit -m "feat(p9): expose deprecation lifecycle CLI"
```

### Task 5: UI and docs

**Files:**
- Modify: `apps/web/index.html`
- Modify: `apps/web/app.js`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing UI tests**

Assert `app.js` renders `deprecation_reason`, `replacement_id`, and `sunset_at`
for skills, MCP servers, and policies.

- [ ] **Step 2: Run UI tests**

Run: `rtk uv run pytest tests/test_web.py -q`

Expected: FAIL.

- [ ] **Step 3: Update UI tables**

Show deprecation metadata in the existing table-oriented UI. Do not add modal or
wizard flows.

- [ ] **Step 4: Update docs**

Document:

```bash
agentctl skills deprecate reviewer --reason "use reviewer-v2" --replacement reviewer-v2 --sunset 2026-06-30T00:00:00Z
agentctl skills undeprecate reviewer
```

- [ ] **Step 5: Run final gate**

Run:

```bash
rtk uv run pytest -q
rtk uv run ruff check .
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/web/index.html apps/web/app.js tests/test_web.py README.md CLAUDE.md
git commit -m "docs(p9): document deprecation lifecycle"
```
