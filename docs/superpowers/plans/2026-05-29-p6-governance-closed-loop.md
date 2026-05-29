# P6 Governance Closed Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the P6 governance closed loop: audit events, deprecation lifecycle, bounded log reads, policy coverage, and UI/CLI visibility without changing `agentic-os` into an agent runtime.

**Architecture:** P6 adds a SQLite-backed `AuditStore` for governance events, extends the existing control-plane tables with `deprecated`, and records audit events from the FastAPI layer after successful mutations and run policy checks. Existing P0 session events and P5 fleet events remain canonical for state transitions; P6 adds governance-specific audit records and query surfaces.

**Tech Stack:** Python 3.12, FastAPI, Typer, SQLite, pytest, ruff, static HTML/CSS/JavaScript. No new dependencies, no extra daemon, no async rewrite.

---

## Context

The reviewed spec is `docs/superpowers/specs/2026-05-29-p6-governance-closed-loop-design.md`.

Important constraints:

- Keep backward-compatible launch semantics: a run without a configured policy may still start, but P6 must record `policy_missing_at_run_start` and `run_started_without_policy`.
- Do not modify `ProcessSupervisor` for audit coupling. The API layer has the policy result and session id, so it records governance audit events around `supervisor.start()` and `_reject_session()`.
- `GET /audit/events` returns `audit_events` only. `/sessions/{id}/events` and `/fleet/events` remain separate canonical state-event APIs.
- `JsonlLogStore.read()` and `read_merged()` return `ReadResult`; update all callers, especially `_build_and_store_summary()`.

## File Structure

- Create `src/agentic_os/audit.py`: `AuditStore`, `AuditEvent`, schema, filtering, policy coverage.
- Modify `src/agentic_os/control_plane.py`: `deprecated` migration, deprecate methods, warning propagation.
- Modify `src/agentic_os/api.py`: `AuditStore` init, audit hooks, deprecate endpoints, audit endpoints, log truncation audit, run policy audit.
- Modify `src/agentic_os/logs.py`: `ReadResult`, `max_lines`, truncation flag.
- Modify `src/agentic_os/client.py`: deprecate, audit event, audit coverage methods.
- Modify `src/agentic_os/cli.py`: `audit` subgroup, deprecate commands, deprecated status labels, log truncation warning.
- Modify `apps/web/index.html` and `apps/web/app.js`: audit events section and deprecated badges.
- Create `tests/test_audit.py`: audit store and coverage tests.
- Modify `tests/test_control_plane.py`, `tests/test_api.py`, `tests/test_logs.py`, `tests/test_cli.py`, `tests/test_web.py`.
- Modify `README.md`, `CLAUDE.md`, and `specs/008-harness-fleet-control-plane-goals.md` for P6 usage and scope.

## Task 1: Audit Store

**Files:**
- Create: `src/agentic_os/audit.py`
- Create: `tests/test_audit.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_audit.py` with tests named:

```python
def test_audit_store_records_and_lists_events(tmp_path): ...
def test_audit_store_filters_by_domain_entity_and_type(tmp_path): ...
def test_audit_store_limit_orders_desc(tmp_path): ...
def test_policy_coverage_reports_missing_policy_and_uncovered_runs(tmp_path): ...
def test_policy_coverage_reports_last_evaluated_at(tmp_path): ...
```

The coverage tests should seed `audit_events` with `policy_evaluated` metadata containing `session_id`, pass `agent_ids=["shell"]` and `session_ids_by_agent={"shell": ["s_1", "s_2"]}`, and assert `runs_without_policy_evaluation == ["s_2"]`.

Run:

```bash
rtk uv run pytest tests/test_audit.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentic_os.audit'`.

- [ ] **Step 2: Implement `AuditStore`**

Create `src/agentic_os/audit.py` with:

```python
@dataclass(frozen=True)
class AuditEvent:
    id: int
    domain: str
    entity_id: str
    event_type: str
    message: str
    metadata: dict[str, object]
    created_at: str
```

Implement `init()`, `record() -> AuditEvent`, `list_events(...)`, and `policy_coverage(agent_ids, session_ids_by_agent)`. Use SQLite `json.dumps(metadata or {})` and `json.loads(row["metadata_json"])`. `policy_coverage` should derive `last_evaluated_at` from the newest `policy_evaluated` event for each agent and compare session ids from metadata.

- [ ] **Step 3: Verify and commit**

Run:

```bash
rtk uv run pytest tests/test_audit.py -q
rtk uv run ruff check .
```

Commit:

```bash
git add src/agentic_os/audit.py tests/test_audit.py
git commit -m "feat(p6): add governance audit store"
```

## Task 2: Deprecation Lifecycle In Control Plane

**Files:**
- Modify: `src/agentic_os/control_plane.py`
- Modify: `tests/test_control_plane.py`

- [ ] **Step 1: Write failing tests**

Add tests that verify:

```python
def test_skill_can_be_deprecated_and_upsert_resets_deprecated(tmp_path): ...
def test_mcp_server_can_be_deprecated_and_upsert_resets_deprecated(tmp_path): ...
def test_policy_can_be_deprecated_and_upsert_resets_deprecated(tmp_path): ...
def test_policy_evaluation_warns_for_deprecated_policy_skill_and_mcp(tmp_path): ...
```

The warning test should upsert a policy, skill, and MCP server; deprecate all three; evaluate a request that references the deprecated skill and MCP; assert `decision == "allow"` and warnings contain the policy, skill, and MCP identifiers.

Run:

```bash
rtk uv run pytest tests/test_control_plane.py -q
```

Expected: FAIL because records have no `deprecated`, methods are missing, and `PolicyEvaluationResult` has no `warnings`.

- [ ] **Step 2: Add schema migration and records**

In `ControlPlaneStore.init()`, after `executescript(SCHEMA)`, call a local `_add_column_if_missing(conn, table, column_sql)` helper for:

```sql
skills deprecated INTEGER NOT NULL DEFAULT 0
mcp_servers deprecated INTEGER NOT NULL DEFAULT 0
agent_policies deprecated INTEGER NOT NULL DEFAULT 0
```

Add `deprecated: bool` to `SkillRecord`, `McpServerRecord`, and `PolicyRecord`; update row mappers.

- [ ] **Step 3: Add deprecate methods and warning propagation**

Add:

```python
def deprecate_skill(self, skill_id: str) -> SkillRecord: ...
def deprecate_mcp_server(self, server_id: str) -> McpServerRecord: ...
def deprecate_policy(self, agent_id: str) -> PolicyRecord: ...
```

Update all `upsert_*` SQL statements to set `deprecated = 0` on insert and conflict update. Add `warnings: list[str] = field(default_factory=list)` to `PolicyEvaluationResult`. Thread a `warnings` list through `_decision()`, `_evaluate_skill()`, and `_evaluate_mcp()` so deprecation warns without denying.

- [ ] **Step 4: Verify and commit**

Run:

```bash
rtk uv run pytest tests/test_control_plane.py -q
rtk uv run pytest tests/test_policy_aware_run.py -q
rtk uv run ruff check .
```

Commit:

```bash
git add src/agentic_os/control_plane.py tests/test_control_plane.py
git commit -m "feat(p6): add capability deprecation lifecycle"
```

## Task 3: API Audit Hooks And Deprecate Endpoints

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests for:

```python
def test_skill_upsert_disable_and_deprecate_create_audit_events(tmp_app): ...
def test_mcp_upsert_disable_and_deprecate_create_audit_events(tmp_app): ...
def test_policy_upsert_and_deprecate_create_audit_events(tmp_app): ...
def test_policy_evaluate_endpoint_records_governance_audit(tmp_app): ...
def test_run_without_policy_records_missing_policy_audit(tmp_path): ...
def test_run_with_policy_records_policy_evaluated_and_run_started(tmp_path): ...
def test_denied_run_records_policy_evaluated_audit(tmp_path): ...
```

Use `GET /audit/events?domain=...` in assertions. For no-policy run, assert event types include `policy_missing_at_run_start` and `run_started_without_policy`.

Run:

```bash
rtk uv run pytest tests/test_api.py -q
```

Expected: FAIL with missing audit routes and deprecate endpoints.

- [ ] **Step 2: Initialize `AuditStore` and expose query routes**

In `create_app`, instantiate `AuditStore(state_dir / "agentic-os.db")`, call `init()`, and set `app.state.audit_store`. Add:

```http
GET /audit/events
GET /audit/policy-coverage
```

`/audit/policy-coverage` should build `session_ids_by_agent` from `store.list_sessions()` and call `audit_store.policy_coverage(...)`.

- [ ] **Step 3: Add mutation hooks and deprecate endpoints**

For skill/MCP/policy upsert, disable, and deprecate endpoints: fetch previous record when it exists, perform the mutation, then call `audit_store.record(...)`. Include minimal before/after metadata for changed fields, especially `enabled` and `deprecated`.

- [ ] **Step 4: Add run policy audit hooks**

Keep existing no-policy launch behavior. In `run_session()` and `retry_session()`, after session creation or rejected-session creation, record:

- `policy_evaluated` with `session_id` when `_evaluate_session_policy()` returned a result;
- `policy_missing_at_run_start` when it returned `None`;
- `run_started_with_policy` for allowed runs with policy;
- `run_started_without_policy` for allowed runs without policy.

For denied or approval-required runs, record only `policy_evaluated` because the run did not start.

- [ ] **Step 5: Verify and commit**

Run:

```bash
rtk uv run pytest tests/test_api.py tests/test_policy_aware_run.py -q
rtk uv run pytest -q
rtk uv run ruff check .
```

Commit:

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat(p6): add governance audit API hooks"
```

## Task 4: Bounded Log Reads

**Files:**
- Modify: `src/agentic_os/logs.py`
- Modify: `src/agentic_os/api.py`
- Modify: `src/agentic_os/cli.py`
- Modify: `tests/test_logs.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing log tests**

Add tests:

```python
def test_read_returns_read_result_with_truncated_false(tmp_path): ...
def test_read_truncates_at_max_lines(tmp_path): ...
def test_read_merged_truncates_per_stream(tmp_path): ...
def test_memory_summary_uses_read_result_entries(tmp_path): ...
def test_logs_endpoint_returns_truncated_flag_and_audit_event(tmp_path): ...
def test_agentctl_logs_prints_truncation_warning(monkeypatch): ...
```

Run:

```bash
rtk uv run pytest tests/test_logs.py tests/test_api.py tests/test_cli.py -q
```

Expected: FAIL because log readers return lists and endpoint lacks `truncated`.

- [ ] **Step 2: Implement `ReadResult`**

In `logs.py`, add:

```python
@dataclass(frozen=True)
class ReadResult:
    entries: list[LogEntry]
    truncated: bool
```

Change `read()` and `read_merged()` to return `ReadResult`. Preserve cursor semantics: `after` is still compared to one-based indexes; `max_lines` caps read rows per stream before merge.

- [ ] **Step 3: Update callers**

Update `/sessions/{id}/logs` to return `{"entries": [...], "truncated": result.truncated}` and accept `max_lines: int = Query(default=5000, ge=1, le=50000)`. Update `_build_and_store_summary()` to pass `result.entries` to `build_session_summary()`. Update CLI `logs` to read `truncated` and print `"(truncated at {max_lines} lines)"`.

- [ ] **Step 4: Verify and commit**

Run:

```bash
rtk uv run pytest tests/test_logs.py tests/test_api.py tests/test_cli.py tests/test_memory.py -q
rtk uv run pytest -q
rtk uv run ruff check .
```

Commit:

```bash
git add src/agentic_os/logs.py src/agentic_os/api.py src/agentic_os/cli.py tests/test_logs.py tests/test_api.py tests/test_cli.py
git commit -m "feat(p6): bound log reads and audit truncation"
```

## Task 5: Client And CLI Audit Surface

**Files:**
- Modify: `src/agentic_os/client.py`
- Modify: `src/agentic_os/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing client/CLI tests**

Add tests for:

```python
def test_client_audit_methods_validate_paths_and_query_params(): ...
def test_audit_events_command_prints_rows(monkeypatch): ...
def test_audit_coverage_command_prints_rows(monkeypatch): ...
def test_skill_mcp_policy_deprecate_commands(monkeypatch): ...
def test_deprecated_status_is_printed_in_list_outputs(monkeypatch): ...
```

Run:

```bash
rtk uv run pytest tests/test_cli.py -q
```

Expected: FAIL with missing methods/commands.

- [ ] **Step 2: Implement client methods**

Add `deprecate_skill`, `deprecate_mcp_server`, `deprecate_policy`, `audit_events`, and `audit_policy_coverage` to `AgenticClient`. Reuse `_validate_path_id()` for path components.

- [ ] **Step 3: Implement CLI commands**

Add:

```text
agentctl skills deprecate <id>
agentctl mcp deprecate <id>
agentctl policy deprecate <agent_id>
agentctl audit events --domain ... --entity ... --type ... --limit ...
agentctl audit coverage
```

For list outputs, status should be `deprecated` when `deprecated=true`, otherwise `disabled` or `enabled`.

- [ ] **Step 4: Verify and commit**

Run:

```bash
rtk uv run pytest tests/test_cli.py -q
rtk uv run pytest -q
rtk uv run ruff check .
```

Commit:

```bash
git add src/agentic_os/client.py src/agentic_os/cli.py tests/test_cli.py
git commit -m "feat(p6): expose audit and deprecation CLI"
```

## Task 6: Static UI Audit And Deprecation Display

**Files:**
- Modify: `apps/web/index.html`
- Modify: `apps/web/app.js`
- Modify: `apps/web/styles.css`
- Modify: `tests/test_web.py`

- [ ] **Step 1: Write failing web contract tests**

Add tests:

```python
def test_fleet_tab_has_audit_events_section(): ...
def test_javascript_references_audit_endpoints(): ...
def test_javascript_renders_deprecated_badges(): ...
def test_javascript_has_load_audit_events_function(): ...
```

Run:

```bash
rtk uv run pytest tests/test_web.py -q
```

Expected: FAIL because UI has no audit section.

- [ ] **Step 2: Implement UI**

Add an Audit Events section under the Fleet tab with filter controls for domain/entity/type and a bounded table. Add `loadAuditEvents()`, call it from Fleet tab refresh, and render `deprecated` badges in skill/MCP/policy rows when records include `deprecated=true`.

- [ ] **Step 3: Verify and commit**

Run:

```bash
rtk uv run pytest tests/test_web.py -q
rtk uv run pytest -q
rtk uv run ruff check .
```

Commit:

```bash
git add apps/web/index.html apps/web/app.js apps/web/styles.css tests/test_web.py
git commit -m "feat(p6): add audit visibility to web UI"
```

## Task 7: Documentation, Spec Alignment, And Final Gate

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `specs/008-harness-fleet-control-plane-goals.md`
- Modify: `docs/superpowers/specs/2026-05-29-p6-governance-closed-loop-design.md` only if implementation discovers a contract mismatch.

- [ ] **Step 1: Update docs**

Add a README section `Run P6 Governance Closed Loop` with:

```bash
rtk uv run agentctl audit events
rtk uv run agentctl audit coverage
rtk uv run agentctl skills deprecate reviewer
rtk uv run agentctl mcp deprecate filesystem
rtk uv run agentctl policy deprecate shell
```

Update the phase table to add P6 as governance audit, deprecation lifecycle, bounded log reads, and policy coverage. Update CLAUDE.md phase scope to P0-P6 and keep non-goals unchanged.

- [ ] **Step 2: Final verification**

Run:

```bash
rtk uv run pytest -q
rtk uv run ruff check .
```

Expected: all tests pass and ruff reports `All checks passed!`.

- [ ] **Step 3: Commit final docs**

```bash
git add README.md CLAUDE.md specs/008-harness-fleet-control-plane-goals.md docs/superpowers/specs/2026-05-29-p6-governance-closed-loop-design.md
git commit -m "docs(p6): document governance closed loop"
```

## Plan Self-Review

- Spec coverage: Tasks 1-7 cover AuditStore, CRUD audit hooks, deprecation, log isolation, audit query API, policy bypass verification, CLI, UI, and docs.
- Placeholder scan: no unfinished marker text; each task has concrete files, tests, commands, and commit messages.
- Type consistency: `AuditEvent`, `ReadResult`, `PolicyEvaluationResult.warnings`, `deprecated`, `policy_coverage`, and endpoint names match the reviewed spec.
- Scope check: no new daemon, no new runtime dependency, no cloud/RBAC/approval workflow, no supervisor audit coupling.
