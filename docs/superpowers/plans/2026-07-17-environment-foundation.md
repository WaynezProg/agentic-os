# Environment Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one built-in adapter table, normalized Environment API, shared health probe, shared native-session observation, and one launch-decision path without breaking existing endpoints.

**Architecture:** Existing tool-specific readers remain specialized. New services normalize and compose their results; old routes become compatibility projections. A static adapter table is the only support matrix.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, pytest, existing registry/readers/supervisor.

## Global Constraints

- `agentd` remains the only owner of managed subprocesses.
- No dynamic plugin loading or second registry file.
- A CLI observation never proves Desktop, IDE, auth, runtime, or config state.
- Existing API and CLI contracts remain compatible.
- All file reads remain bounded and secret values remain redacted.
- Python formatting and lint use Ruff with line length 100.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/agentic_os/environment_models.py` | Normalized environment, surface, evidence, and status models |
| `src/agentic_os/environment_adapters.py` | Static built-in support table and adapter lookup |
| `src/agentic_os/probe_service.py` | Single health/version/fingerprint command executor |
| `src/agentic_os/native_session_service.py` | Bounded normalized native-session scan and filtering |
| `src/agentic_os/environment_service.py` | Compose registry and observer results into Environment |
| `src/agentic_os/launch_decision.py` | Shared capacity/policy/approval decision semantics |
| `src/agentic_os/api.py` | Composition wiring, new endpoints, compatibility route rewiring |
| `src/agentic_os/health_prober.py` | Persist shared ProbeResult for fleet views |
| `src/agentic_os/live_sessions.py` | Keep tool parsers; expose them through the new service |
| `src/agentic_os/attach.py` | Consume normalized session records for discovery/bind |
| `tests/test_environment_adapters.py` | Adapter coverage and support-matrix tests |
| `tests/test_probe_service.py` | Shared probe behavior |
| `tests/test_native_session_service.py` | Radar/bind normalization and bounds |
| `tests/test_environment_service.py` | Status composition and surface separation |
| `tests/test_launch_decision.py` | Shared decision semantics |
| `tests/test_api.py` | New Environment API and compatibility responses |

### Task 1: Normalized models and static adapter table

**Interfaces:**

- Produces: `EnvironmentAdapter`, `get_adapter()`, `iter_adapters()`.
- Produces: `Environment`, `SurfaceObservation`, `ObservationEvidence`.
- Consumed by: Tasks 2–5.

- [x] **Step 1: Write failing adapter tests**

Create `tests/test_environment_adapters.py`:

```python
from agentic_os.environment_adapters import get_adapter, iter_adapters


def test_built_in_adapters_cover_semantic_harnesses() -> None:
    assert tuple(adapter.id for adapter in iter_adapters()) == (
        "claude",
        "codex",
        "cursor",
        "hermes",
        "openclaw",
        "opencode",
        "qwen",
    )


def test_adapter_declares_independent_surfaces() -> None:
    adapter = get_adapter("codex")
    assert adapter.cli is True
    assert adapter.config is True
    assert adapter.native_sessions is True
    assert adapter.desktop is True
    assert adapter.ide is False


def test_unknown_adapter_is_explicit() -> None:
    assert get_adapter("shell", required=False) is None
```

- [x] **Step 2: Run tests and confirm the missing module**

Run:

```bash
rtk uv run pytest tests/test_environment_adapters.py -q
```

Expected: collection fails with `ModuleNotFoundError: agentic_os.environment_adapters`.

- [x] **Step 3: Add normalized models**

Create `src/agentic_os/environment_models.py` with these public contracts:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

SurfaceKind = Literal["cli", "config", "capability", "runtime", "desktop", "ide"]
SurfaceStatus = Literal[
    "healthy",
    "degraded",
    "missing",
    "configured_only",
    "auth_required",
    "stale",
    "unsupported",
    "unknown",
]


def observed_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ObservationEvidence(BaseModel):
    source: str
    detail: str


class SurfaceObservation(BaseModel):
    kind: SurfaceKind
    status: SurfaceStatus
    source: str
    version: str | None = None
    path: str | None = None
    detail: str | None = None
    action_required: str | None = None
    evidence: list[ObservationEvidence] = Field(default_factory=list)
    observed_at: str = Field(default_factory=observed_now)


class Environment(BaseModel):
    id: str
    label: str
    tool_kind: str
    overall_status: SurfaceStatus
    surfaces: list[SurfaceObservation] = Field(default_factory=list)
    capability_names: dict[str, list[str]] = Field(default_factory=dict)
    active_sessions: int = 0
    pending_change_count: int = 0
    observed_at: str = Field(default_factory=observed_now)
```

- [x] **Step 4: Add the static adapter table**

Create `src/agentic_os/environment_adapters.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvironmentAdapter:
    id: str
    label: str
    tool_kind: str
    cli: bool = True
    config: bool = True
    capabilities: bool = True
    runtime: bool = False
    desktop: bool = False
    ide: bool = False
    native_sessions: bool = False


_ADAPTERS = (
    EnvironmentAdapter("claude", "Claude Code", "vibe_coding", desktop=True, native_sessions=True),
    EnvironmentAdapter("codex", "Codex", "vibe_coding", desktop=True, native_sessions=True),
    EnvironmentAdapter("cursor", "Cursor", "vibe_coding", desktop=True, ide=True),
    EnvironmentAdapter("hermes", "Hermes", "agentic_runtime", runtime=True),
    EnvironmentAdapter("openclaw", "OpenClaw", "agentic_runtime", runtime=True),
    EnvironmentAdapter("opencode", "OpenCode", "vibe_coding", desktop=True),
    EnvironmentAdapter("qwen", "Qwen", "vibe_coding"),
)
_BY_ID = {adapter.id: adapter for adapter in _ADAPTERS}


def iter_adapters() -> tuple[EnvironmentAdapter, ...]:
    return _ADAPTERS


def get_adapter(
    environment_id: str,
    *,
    required: bool = True,
) -> EnvironmentAdapter | None:
    adapter = _BY_ID.get(environment_id)
    if adapter is None and required:
        raise KeyError(f"unknown environment adapter: {environment_id}")
    return adapter
```

- [x] **Step 5: Run focused tests**

Run:

```bash
rtk uv run pytest tests/test_environment_adapters.py -q
rtk uv run ruff check src/agentic_os/environment_models.py src/agentic_os/environment_adapters.py
```

Expected: all tests pass and Ruff reports no errors.

- [x] **Step 6: Commit**

```bash
git add src/agentic_os/environment_models.py src/agentic_os/environment_adapters.py tests/test_environment_adapters.py
git commit -m "feat: add built-in environment adapter model"
```

### Task 2: Shared health probe service

**Interfaces:**

- Consumes: `AgentDefinition`.
- Produces: `ProbeResult`, `ProbeService.probe()`, `ProbeService.info()`.
- Used by: `HealthProber` and `/harnesses/{id}/health`.

- [x] **Step 1: Write failing tests**

Create `tests/test_probe_service.py`:

```python
from agentic_os.models import AgentDefinition
from agentic_os.probe_service import ProbeService


def agent(command: list[str] | None) -> AgentDefinition:
    return AgentDefinition(
        id="demo",
        label="Demo",
        command=["/bin/echo", "run"],
        health_command=command,
    )


def test_probe_normalizes_success() -> None:
    result = ProbeService(timeout_seconds=1).probe(agent(["/bin/echo", "OK"]))
    assert result.state == "up"
    assert result.exit_code == 0
    assert result.stdout == "OK"
    assert result.duration_ms >= 0


def test_probe_normalizes_nonzero() -> None:
    result = ProbeService(timeout_seconds=1).probe(agent(["/bin/sh", "-c", "exit 7"]))
    assert result.state == "down"
    assert result.exit_code == 7


def test_probe_without_command_is_unknown() -> None:
    result = ProbeService(timeout_seconds=1).probe(agent(None))
    assert result.state == "unknown"
    assert result.error == "health command not configured"
```

- [x] **Step 2: Verify failure**

Run:

```bash
rtk uv run pytest tests/test_probe_service.py -q
```

Expected: missing module failure.

- [x] **Step 3: Implement `ProbeService`**

Create `src/agentic_os/probe_service.py` with:

```python
from __future__ import annotations

import subprocess
import time
from typing import Literal

from pydantic import BaseModel

from agentic_os.models import AgentDefinition

ProbeState = Literal["up", "down", "unknown"]
_OUTPUT_LIMIT = 2048


class ProbeResult(BaseModel):
    state: ProbeState
    message: str
    duration_ms: int
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    version: str | None = None
    config_fingerprint: str | None = None


class ProbeService:
    def __init__(self, timeout_seconds: float = 10) -> None:
        self.timeout_seconds = timeout_seconds

    def probe(self, agent: AgentDefinition) -> ProbeResult:
        if not agent.health_command:
            return ProbeResult(
                state="unknown",
                message="health command not configured",
                duration_ms=0,
                error="health command not configured",
            )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                agent.health_command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ProbeResult(
                state="down",
                message=f"timeout after {self.timeout_seconds}s",
                duration_ms=int((time.monotonic() - started) * 1000),
                error="timeout",
            )
        except OSError as exc:
            return ProbeResult(
                state="down",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                error=str(exc),
            )
        stdout = completed.stdout.strip()[:_OUTPUT_LIMIT]
        stderr = completed.stderr.strip()[:_OUTPUT_LIMIT]
        return ProbeResult(
            state="up" if completed.returncode == 0 else "down",
            message=stdout or stderr or f"exit {completed.returncode}",
            duration_ms=int((time.monotonic() - started) * 1000),
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            version=self.info(agent.version_command),
            config_fingerprint=self.info(agent.config_fingerprint_command),
        )

    def info(self, command: list[str] | None) -> str | None:
        if not command:
            return None
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        return (completed.stdout or completed.stderr).strip()[:_OUTPUT_LIMIT] or None
```

- [x] **Step 4: Rewire fleet and immediate health**

Modify `src/agentic_os/health_prober.py` so `probe_one()` executes
`ProbeService.probe()` with `asyncio.to_thread`, then calls
`FleetStore.record_health()` with the shared state/message/version/fingerprint.

Modify `src/agentic_os/api.py` so `_run_health_check()` serializes the same
`ProbeResult` instead of invoking `subprocess.run` itself.

- [x] **Step 5: Run focused regression**

```bash
rtk uv run pytest tests/test_probe_service.py tests/test_health_prober.py tests/test_api.py -k "health or probe" -q
rtk uv run ruff check src/agentic_os/probe_service.py src/agentic_os/health_prober.py src/agentic_os/api.py
```

Expected: all focused tests pass.

- [x] **Step 6: Commit**

```bash
git add src/agentic_os/probe_service.py src/agentic_os/health_prober.py src/agentic_os/api.py tests/test_probe_service.py tests/test_health_prober.py tests/test_api.py
git commit -m "refactor: unify harness health probing"
```

### Task 3: Unified native-session service

**Interfaces:**

- Produces: `NativeSessionService.scan()`, `NativeSessionScan`.
- Reuses: existing Claude/Codex parser functions.
- Consumed by: live radar, transcript path validation, external discovery/bind.

- [x] **Step 1: Write normalization tests**

Create `tests/test_native_session_service.py` with fixture writers imported from
`tests/test_live_sessions.py` or copied as local helpers, then assert:

```python
def test_workspace_filter_and_radar_return_same_identity(tmp_path: Path) -> None:
    roots = make_native_roots(tmp_path)
    service = NativeSessionService(roots=roots)
    all_scan = service.scan(within_hours=72, limit=20, now=NOW)
    project_scan = service.scan(
        workspace="/Users/w/proj",
        within_hours=72,
        limit=20,
        now=NOW,
    )
    assert [item.identity for item in all_scan.sessions] == [
        item.identity for item in project_scan.sessions
    ]


def test_scan_has_global_file_limit(tmp_path: Path) -> None:
    roots = make_many_native_sessions(tmp_path, count=80)
    scan = NativeSessionService(roots=roots, max_files=25).scan(
        within_hours=72,
        limit=100,
        now=NOW,
    )
    assert scan.files_examined <= 25
```

- [x] **Step 2: Verify failure**

```bash
rtk uv run pytest tests/test_native_session_service.py -q
```

Expected: missing module failure.

- [x] **Step 3: Implement service**

Create `src/agentic_os/native_session_service.py` with:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from agentic_os.live_sessions import LiveSession, scan_live_sessions


class NativeSessionRecord(BaseModel):
    identity: str
    environment_id: str
    session_id: str
    workspace: str
    title: str
    started_at: str | None
    last_activity_at: str
    active: bool
    source: str | None
    log_path: str
    resume_command: str


class NativeSessionScan(BaseModel):
    sessions: list[NativeSessionRecord] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    files_examined: int = 0


class NativeSessionService:
    def __init__(
        self,
        roots: dict[str, Path] | None = None,
        *,
        max_files: int = 500,
        scanner=scan_live_sessions,
    ) -> None:
        self.roots = roots
        self.max_files = max_files
        self.scanner = scanner

    def scan(
        self,
        *,
        environment_id: str | None = None,
        workspace: str | None = None,
        within_hours: int = 72,
        limit: int = 50,
        now: datetime | None = None,
    ) -> NativeSessionScan:
        sessions, errors = self.scanner(
            self.roots,
            within_hours=within_hours,
            limit=min(limit, self.max_files),
            now=now,
        )
        filtered = [
            self._normalize(session)
            for session in sessions
            if (environment_id is None or session.tool == environment_id)
            and (workspace is None or session.workspace == workspace)
        ]
        return NativeSessionScan(
            sessions=filtered[:limit],
            errors=errors,
            files_examined=min(len(sessions), self.max_files),
        )

    @staticmethod
    def _normalize(session: LiveSession) -> NativeSessionRecord:
        return NativeSessionRecord(
            identity=f"{session.tool}:{session.session_id}",
            environment_id=session.tool,
            session_id=session.session_id,
            workspace=session.workspace,
            title=session.title,
            started_at=session.started_at,
            last_activity_at=session.last_activity_at,
            active=session.active,
            source=session.source,
            log_path=session.log_path,
            resume_command=session.resume_command,
        )
```

During implementation, move the actual global file-count enforcement into the
shared traversal in `live_sessions.py`; the service-level cap alone must not be
used as proof of bounded filesystem traversal.

- [x] **Step 4: Rewire routes**

Use one `NativeSessionService` instance in `create_app()`.

- `/sessions/live` serializes `service.scan()`.
- `/sessions/discover` filters the same normalized records by workspace and
  registered environment, then maps them to the legacy discovery response.
- `/sessions/live/transcript` validates the selected record's `log_path`.

Keep `attach.py` command construction and execution unchanged.

- [x] **Step 5: Run regression**

```bash
rtk uv run pytest tests/test_native_session_service.py tests/test_live_sessions.py tests/test_attach_vibe_coding.py tests/test_api.py -k "live or discover or bind or transcript" -q
rtk uv run ruff check src/agentic_os/native_session_service.py src/agentic_os/live_sessions.py src/agentic_os/attach.py src/agentic_os/api.py
```

- [x] **Step 6: Commit**

```bash
git add src/agentic_os/native_session_service.py src/agentic_os/live_sessions.py src/agentic_os/attach.py src/agentic_os/api.py tests/test_native_session_service.py tests/test_live_sessions.py tests/test_attach_vibe_coding.py tests/test_api.py
git commit -m "refactor: unify native session observation"
```

### Task 4: Environment service and APIs

**Interfaces:**

- Consumes: adapter table, registry, discovery, config/capability/runtime readers,
  native-session service, fleet health.
- Produces: `EnvironmentService.observe()` and Environment endpoints.

- [x] **Step 1: Write service and API tests**

Create `tests/test_environment_service.py`:

```python
def test_config_residue_does_not_mark_cli_installed(environment_service) -> None:
    environment = environment_service.observe("qwen")[0]
    cli = next(surface for surface in environment.surfaces if surface.kind == "cli")
    config = next(surface for surface in environment.surfaces if surface.kind == "config")
    assert cli.status == "missing"
    assert config.status == "configured_only"
    assert environment.overall_status == "degraded"


def test_surface_evidence_is_independent(environment_service) -> None:
    environment = environment_service.observe("codex")[0]
    assert {surface.kind for surface in environment.surfaces} >= {
        "cli",
        "config",
        "capability",
    }
    assert all(surface.source for surface in environment.surfaces)
```

Add API assertions to `tests/test_api.py`:

```python
def test_environments_list_and_detail(client) -> None:
    response = client.get("/environments")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == len(body["environments"])
    environment_id = body["environments"][0]["id"]
    detail = client.get(f"/environments/{environment_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == environment_id
```

- [x] **Step 2: Implement `EnvironmentService`**

Create `src/agentic_os/environment_service.py`. Its constructor receives
`Registry`, capability home, `NativeSessionService`, and `FleetStore`. Implement:

```python
class EnvironmentService:
    def observe(self, environment_id: str | None = None) -> list[Environment]:
        adapters = (
            (get_adapter(environment_id),)
            if environment_id is not None
            else iter_adapters()
        )
        return [self._observe_one(adapter) for adapter in adapters if adapter is not None]
```

`_observe_one()` must:

- locate the registry agent;
- call `detect_tool()` once;
- call `read_config_summary()` only when configured;
- call `read_tool_capabilities()` only when supported;
- call `build_agentic_inventory()` only for runtime adapters;
- count active normalized native sessions;
- read persisted fleet health;
- create independent surface observations;
- compute overall status with this precedence:
  `auth_required`, `degraded`, `stale`, `missing`, `configured_only`, `healthy`,
  `unknown`, `unsupported`.

- [x] **Step 3: Wire composition and routes**

In `create_app()` instantiate one Environment service and add:

```python
@app.get("/environments")
def list_environments() -> dict[str, object]:
    environments = environment_service.observe()
    return {
        "environments": [item.model_dump(mode="json") for item in environments],
        "count": len(environments),
    }


@app.get("/environments/{environment_id}")
def show_environment(environment_id: str) -> dict[str, object]:
    try:
        return environment_service.observe(environment_id)[0].model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

Add refresh POST routes that invalidate discovery cache before observing.

- [x] **Step 4: Convert compatibility endpoints**

Change `/tools/discovery`, `/tools/inventory`, `/tools/capabilities`, and
`/agentic/inventory` to project from Environment service data while preserving
their existing JSON field names and redaction tests.

- [x] **Step 5: Run focused and full domain tests**

```bash
rtk uv run pytest tests/test_environment_service.py tests/test_tool_discovery.py tests/test_config_inventory.py tests/test_capability_inventory.py tests/test_agentic_inventory.py tests/test_api.py -q
rtk uv run ruff check src/agentic_os/environment_service.py src/agentic_os/api.py
```

- [x] **Step 6: Commit**

```bash
git add src/agentic_os/environment_service.py src/agentic_os/api.py tests/test_environment_service.py tests/test_api.py
git commit -m "feat: add normalized environment APIs"
```

### Task 5: Shared launch-decision service

**Interfaces:**

- Produces: `LaunchContext`, `LaunchDecision`, `LaunchDecisionService.evaluate()`.
- Consumed by: new launch, retry, approval execution, explicit policy evaluate.

- [x] **Step 1: Write semantic tests**

Create `tests/test_launch_decision.py`:

```python
def test_missing_policy_is_open_with_warning(service, context) -> None:
    decision = service.evaluate(context)
    assert decision.decision == "allow"
    assert decision.reason == "policy_missing_open_default"
    assert decision.warnings == ["no launch policy configured"]


def test_capacity_denial_precedes_policy(service, full_context) -> None:
    decision = service.evaluate(full_context)
    assert decision.decision == "deny"
    assert decision.reason == "capacity_limit_reached"


def test_approval_requirement_is_preserved(service, approval_context) -> None:
    decision = service.evaluate(approval_context)
    assert decision.decision == "approval_required"
```

- [x] **Step 2: Implement service**

Create `src/agentic_os/launch_decision.py` with Pydantic models:

```python
class LaunchContext(BaseModel):
    agent_id: str
    cwd: str
    requested_skills: list[str] = Field(default_factory=list)
    requested_mcp_servers: list[str] = Field(default_factory=list)
    requested_tools: list[str] = Field(default_factory=list)
    model: str | None = None
    running_sessions: int
    max_running_sessions: int


class LaunchDecision(BaseModel):
    decision: Literal["allow", "deny", "approval_required"]
    reason: str
    warnings: list[str] = Field(default_factory=list)
    policy_result: dict[str, object] | None = None
```

`evaluate()` first checks capacity, then the policy store. A missing policy
returns allow with warning. Existing policy deny and approval results retain
their metadata.

- [x] **Step 3: Rewire all decision call sites**

Use one helper in `api.py` to construct `LaunchContext` for:

- `POST /sessions`;
- retry;
- approval execution;
- `POST /policy/evaluate`.

All four paths record the same redacted decision metadata in audit.

- [x] **Step 4: Verify**

```bash
rtk uv run pytest tests/test_launch_decision.py tests/test_policy_aware_run.py tests/test_approvals.py tests/test_remote_approval_loop.py tests/test_api.py -q
rtk uv run ruff check src/agentic_os/launch_decision.py src/agentic_os/api.py
```

- [x] **Step 5: Commit**

```bash
git add src/agentic_os/launch_decision.py src/agentic_os/api.py tests/test_launch_decision.py tests/test_policy_aware_run.py tests/test_approvals.py tests/test_remote_approval_loop.py tests/test_api.py
git commit -m "refactor: unify launch decisions"
```

### Task 6: Compatibility and complete verification

- [ ] **Step 1: Add compatibility contract tests**

Assert old endpoint keys and status codes remain unchanged, and adapter IDs
match `SEMANTIC_HARNESS_IDS`.

- [ ] **Step 2: Run complete Python gates**

```bash
rtk uv run pytest -q
rtk uv run ruff check .
```

Expected: full suite passes and Ruff reports no errors.

- [ ] **Step 3: Update architecture docs**

Append implementation evidence to `decision_log.md` and add a README phase row
for Environment foundation. Keep the design document unchanged except for a
short implemented-status note.

- [ ] **Step 4: Commit**

```bash
git add README.md decision_log.md docs/superpowers/specs/2026-07-17-local-agent-environment-manager-design.md
git commit -m "docs: record environment foundation"
```

## Self-Review

- Spec coverage: Task 1 owns the support matrix and normalized evidence model;
  Tasks 2 and 3 remove duplicate probe/session paths; Task 4 exposes the
  Environment API; Task 5 unifies launch decisions; Task 6 protects
  compatibility and records evidence.
- Placeholder scan: no deferred implementation markers remain. Test-only
  fixtures named in snippets are defined in the test file being created and
  construct real temporary stores/config files.
- Type consistency: adapter IDs, `SurfaceKind`, `SurfaceStatus`,
  `NativeSessionRecord.identity`, and `LaunchDecision.decision` use the same
  names in producers, API projections, and tests.
