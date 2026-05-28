# P5: Fleet Inventory + Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement multi-runtime profile registry, health probes, version/config drift detection, and capacity enforcement for the agentic-os fleet control plane.

**Architecture:** A new `fleet.py` module owns the fleet_health SQLite table and drift logic. A new `health_prober.py` runs a background asyncio task that probes each registered instance's health_command with windowed concurrency (≤10) and per-probe timeout (10s). The prober records health state transitions and drift events via fleet store. Capacity enforcement intercepts `POST /sessions` with 429 when parallelism limits are reached. All fleet state is queryable via new API endpoints, client methods, CLI commands, and a UI panel.

**Tech Stack:** Python 3.12, FastAPI, SQLite, asyncio (for probe loop), subprocess (for health commands), existing Pydantic models.

**Governance satisfaction:** G1 (all transitions produce events), G2 (probe timeout + isolation), G3 (drift as first-class event), G4 (429 on capacity limits, utilization queryable).

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `src/agentic_os/fleet.py` | FleetStore: SQLite fleet_health + fleet_events tables, HealthState enum, health/drift record CRUD, capacity queries |
| `src/agentic_os/health_prober.py` | HealthProber: background asyncio task, windowed probe execution, per-probe timeout, state transition recording |
| `tests/test_fleet.py` | Unit tests for FleetStore |
| `tests/test_health_prober.py` | Unit tests for HealthProber |

### Modified files

| File | Changes |
|------|---------|
| `src/agentic_os/models.py` | Extend AgentDefinition with version_command, config_fingerprint_command, attach_command, config_path, log_paths, default_provider |
| `src/agentic_os/registry.py` | No changes needed — new fields have defaults, Pydantic parses them automatically |
| `src/agentic_os/api.py` | Add fleet endpoints (GET /fleet/health, /fleet/{id}/health, /fleet/events, /fleet/capacity), capacity gate on POST /sessions, start prober on app startup |
| `src/agentic_os/client.py` | Add fleet_health, fleet_instance_health, fleet_events, fleet_capacity methods |
| `src/agentic_os/cli.py` | Add `fleet` typer group with health, events, capacity subcommands |
| `examples/agents.toml` | Add version_command and config_fingerprint_command to shell agent |
| `apps/web/index.html` | Add Fleet tab |
| `apps/web/app.js` | Add fleet health panel rendering |
| `tests/test_api.py` | Add fleet API endpoint tests |
| `tests/test_cli.py` | Add fleet CLI tests |

---

### Task 1: Extend AgentDefinition with fleet profile fields

**Files:**
- Modify: `src/agentic_os/models.py:22-31`
- Test: `tests/test_registry.py`

- [ ] **Step 1: Write failing test for new profile fields**

```python
# tests/test_registry.py — add at end of file

def test_agent_definition_fleet_profile_fields(tmp_path):
    """AgentDefinition accepts fleet profile fields from TOML."""
    toml_path = tmp_path / "agents.toml"
    toml_path.write_text(
        """\
[[agents]]
id = "test"
label = "Test"
command = ["/bin/echo", "hi"]
health_command = ["/bin/echo", "OK"]
version_command = ["/bin/echo", "1.0.0"]
config_fingerprint_command = ["/bin/echo", "abc123"]
attach_command = ["/bin/echo", "attached"]
config_path = "~/.test/config.toml"
log_paths = ["~/.test/logs"]
default_provider = "openai"
""",
        encoding="utf-8",
    )
    from agentic_os.registry import Registry

    reg = Registry(toml_path)
    agent = reg.get("test")
    assert agent.version_command == ["/bin/echo", "1.0.0"]
    assert agent.config_fingerprint_command == ["/bin/echo", "abc123"]
    assert agent.attach_command == ["/bin/echo", "attached"]
    assert agent.config_path == "~/.test/config.toml"
    assert agent.log_paths == ["~/.test/logs"]
    assert agent.default_provider == "openai"


def test_agent_definition_fleet_fields_optional(tmp_path):
    """Fleet profile fields default to None/empty when not in TOML."""
    toml_path = tmp_path / "agents.toml"
    toml_path.write_text(
        """\
[[agents]]
id = "minimal"
label = "Minimal"
command = ["/bin/echo", "hi"]
""",
        encoding="utf-8",
    )
    from agentic_os.registry import Registry

    reg = Registry(toml_path)
    agent = reg.get("minimal")
    assert agent.version_command is None
    assert agent.config_fingerprint_command is None
    assert agent.attach_command is None
    assert agent.config_path is None
    assert agent.log_paths == []
    assert agent.default_provider is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_registry.py::test_agent_definition_fleet_profile_fields tests/test_registry.py::test_agent_definition_fleet_fields_optional -v`
Expected: FAIL — `AgentDefinition` does not have these fields

- [ ] **Step 3: Add fleet profile fields to AgentDefinition**

In `src/agentic_os/models.py`, add new fields to `AgentDefinition`:

```python
class AgentDefinition(BaseModel):
    id: str
    label: str
    command: list[str]
    cwd_mode: CwdMode = "optional"
    env: dict[str, str] = Field(default_factory=dict)
    stop_policy: StopPolicy = "process_group"
    health_command: list[str] | None = None
    version_command: list[str] | None = None
    config_fingerprint_command: list[str] | None = None
    attach_command: list[str] | None = None
    config_path: str | None = None
    log_paths: list[str] = Field(default_factory=list)
    default_provider: str | None = None
    enabled: bool = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_registry.py -v`
Expected: ALL PASS

- [ ] **Step 5: Update examples/agents.toml with version_command for shell**

```toml
[[agents]]
id = "shell"
label = "Shell Smoke"
command = ["/usr/bin/printf", "%s\\n", "{{message}}"]
cwd_mode = "optional"
stop_policy = "process_group"
health_command = ["/usr/bin/printf", "OK"]
version_command = ["/usr/bin/printf", "1.0.0"]
config_fingerprint_command = ["/usr/bin/printf", "static"]
```

The openclaw and hermes entries remain unchanged (no version_command yet — that is real-harness config, not our concern).

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -q`
Expected: ALL PASS (199+2 new = 201)

- [ ] **Step 7: Commit**

```bash
git add src/agentic_os/models.py tests/test_registry.py examples/agents.toml
git commit -m "feat(p5): extend AgentDefinition with fleet profile fields"
```

---

### Task 2: FleetStore — health state and fleet events SQLite

**Files:**
- Create: `src/agentic_os/fleet.py`
- Create: `tests/test_fleet.py`

- [ ] **Step 1: Write failing test for FleetStore.record_health**

```python
# tests/test_fleet.py

from pathlib import Path

from agentic_os.fleet import FleetStore, HealthState


def _make_store(tmp_path: Path) -> FleetStore:
    store = FleetStore(tmp_path / "fleet.db")
    store.init()
    return store


def test_record_health_and_get(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK")
    record = store.get_health("shell")
    assert record.agent_id == "shell"
    assert record.state == HealthState.UP
    assert record.message == "OK"
    assert record.version is None
    assert record.config_fingerprint is None


def test_record_health_with_version_and_fingerprint(tmp_path):
    store = _make_store(tmp_path)
    store.record_health(
        "shell",
        HealthState.UP,
        "OK",
        version="1.0.0",
        config_fingerprint="abc123",
    )
    record = store.get_health("shell")
    assert record.version == "1.0.0"
    assert record.config_fingerprint == "abc123"


def test_record_health_creates_transition_event(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK")
    store.record_health("shell", HealthState.DOWN, "timeout")
    events = store.list_events()
    transition_events = [e for e in events if e.event_type == "health_state_changed"]
    assert len(transition_events) == 1
    assert transition_events[0].agent_id == "shell"
    assert transition_events[0].metadata["from_state"] == "unknown"
    # First record is implicitly unknown->up, but that's the initial set.
    # The DOWN record triggers unknown->up was the first, then up->down.
    # Actually: first call sets state to UP (transition from unknown->up = event),
    # second call sets DOWN (transition from up->down = event).
    # So there should be 2 transition events.
    transition_events = [e for e in events if e.event_type == "health_state_changed"]
    assert len(transition_events) == 2


def test_list_health_all_instances(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK")
    store.record_health("openclaw", HealthState.DOWN, "not found")
    records = store.list_health()
    assert len(records) == 2
    ids = {r.agent_id for r in records}
    assert ids == {"shell", "openclaw"}


def test_get_health_unknown_returns_none(tmp_path):
    store = _make_store(tmp_path)
    assert store.get_health("nonexistent") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fleet.py -v`
Expected: FAIL — `fleet` module does not exist

- [ ] **Step 3: Implement FleetStore**

```python
# src/agentic_os/fleet.py

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class HealthState(StrEnum):
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


HEALTH_STATE_SQL = ", ".join(f"'{s.value}'" for s in HealthState)

FLEET_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS fleet_health (
  agent_id TEXT PRIMARY KEY,
  state TEXT NOT NULL CHECK (state IN ({HEALTH_STATE_SQL})),
  message TEXT NOT NULL DEFAULT '',
  version TEXT,
  config_fingerprint TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fleet_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{{}}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True)
class HealthRecord:
    agent_id: str
    state: HealthState
    message: str
    version: str | None
    config_fingerprint: str | None
    updated_at: str


@dataclass(frozen=True)
class FleetEvent:
    id: int
    agent_id: str
    event_type: str
    message: str
    metadata: dict[str, object]
    created_at: str


class FleetStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(FLEET_SCHEMA)

    def record_health(
        self,
        agent_id: str,
        state: HealthState,
        message: str,
        *,
        version: str | None = None,
        config_fingerprint: str | None = None,
    ) -> HealthRecord:
        previous = self.get_health(agent_id)
        previous_state = previous.state if previous else HealthState.UNKNOWN

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fleet_health (agent_id, state, message, version, config_fingerprint, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(agent_id) DO UPDATE SET
                  state = excluded.state,
                  message = excluded.message,
                  version = excluded.version,
                  config_fingerprint = excluded.config_fingerprint,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (agent_id, state.value, message, version, config_fingerprint),
            )

        if previous_state != state:
            self._record_event(
                agent_id,
                "health_state_changed",
                f"{previous_state.value} -> {state.value}: {message}",
                {"from_state": previous_state.value, "to_state": state.value},
            )

        return self.get_health(agent_id)  # type: ignore[return-value]

    def get_health(self, agent_id: str) -> HealthRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM fleet_health WHERE agent_id = ?", (agent_id,)
            ).fetchone()
        if row is None:
            return None
        return _health_from_row(row)

    def list_health(self) -> list[HealthRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fleet_health ORDER BY agent_id"
            ).fetchall()
        return [_health_from_row(row) for row in rows]

    def list_events(
        self,
        agent_id: str | None = None,
        event_type: str | None = None,
        limit: int = 200,
    ) -> list[FleetEvent]:
        clauses: list[str] = []
        params: list[object] = []
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM fleet_events {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def _record_event(
        self,
        agent_id: str,
        event_type: str,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fleet_events (agent_id, event_type, message, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                (agent_id, event_type, message, json.dumps(metadata or {})),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def _health_from_row(row: sqlite3.Row) -> HealthRecord:
    return HealthRecord(
        agent_id=row["agent_id"],
        state=HealthState(row["state"]),
        message=row["message"],
        version=row["version"],
        config_fingerprint=row["config_fingerprint"],
        updated_at=row["updated_at"],
    )


def _event_from_row(row: sqlite3.Row) -> FleetEvent:
    return FleetEvent(
        id=row["id"],
        agent_id=row["agent_id"],
        event_type=row["event_type"],
        message=row["message"],
        metadata=json.loads(row["metadata_json"]),
        created_at=row["created_at"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fleet.py -v`
Expected: ALL PASS

- [ ] **Step 5: Write drift event tests**

```python
# tests/test_fleet.py — append

def test_record_health_drift_event_on_version_change(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK", version="1.0.0", config_fingerprint="aaa")
    store.record_health("shell", HealthState.UP, "OK", version="1.1.0", config_fingerprint="aaa")
    events = store.list_events(event_type="config_drift_detected")
    assert len(events) == 1
    assert events[0].metadata["field"] == "version"
    assert events[0].metadata["previous"] == "1.0.0"
    assert events[0].metadata["current"] == "1.1.0"


def test_record_health_drift_event_on_fingerprint_change(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK", version="1.0.0", config_fingerprint="aaa")
    store.record_health("shell", HealthState.UP, "OK", version="1.0.0", config_fingerprint="bbb")
    events = store.list_events(event_type="config_drift_detected")
    assert len(events) == 1
    assert events[0].metadata["field"] == "config_fingerprint"


def test_no_drift_event_when_unchanged(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK", version="1.0.0", config_fingerprint="aaa")
    store.record_health("shell", HealthState.UP, "OK", version="1.0.0", config_fingerprint="aaa")
    events = store.list_events(event_type="config_drift_detected")
    assert len(events) == 0


def test_no_drift_event_on_first_record(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK", version="1.0.0", config_fingerprint="aaa")
    events = store.list_events(event_type="config_drift_detected")
    assert len(events) == 0
```

- [ ] **Step 6: Run drift tests to verify they fail**

Run: `uv run pytest tests/test_fleet.py::test_record_health_drift_event_on_version_change -v`
Expected: FAIL — drift detection not implemented yet

- [ ] **Step 7: Add drift detection to record_health**

In `src/agentic_os/fleet.py`, add drift detection logic to `record_health` method, after the UPSERT and health_state_changed event, before the return:

```python
    def record_health(
        self,
        agent_id: str,
        state: HealthState,
        message: str,
        *,
        version: str | None = None,
        config_fingerprint: str | None = None,
    ) -> HealthRecord:
        previous = self.get_health(agent_id)
        previous_state = previous.state if previous else HealthState.UNKNOWN

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fleet_health (agent_id, state, message, version, config_fingerprint, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(agent_id) DO UPDATE SET
                  state = excluded.state,
                  message = excluded.message,
                  version = excluded.version,
                  config_fingerprint = excluded.config_fingerprint,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (agent_id, state.value, message, version, config_fingerprint),
            )

        if previous_state != state:
            self._record_event(
                agent_id,
                "health_state_changed",
                f"{previous_state.value} -> {state.value}: {message}",
                {"from_state": previous_state.value, "to_state": state.value},
            )

        if previous is not None:
            if version is not None and previous.version is not None and version != previous.version:
                self._record_event(
                    agent_id,
                    "config_drift_detected",
                    f"version changed: {previous.version} -> {version}",
                    {"field": "version", "previous": previous.version, "current": version},
                )
            if (
                config_fingerprint is not None
                and previous.config_fingerprint is not None
                and config_fingerprint != previous.config_fingerprint
            ):
                self._record_event(
                    agent_id,
                    "config_drift_detected",
                    f"config_fingerprint changed: {previous.config_fingerprint} -> {config_fingerprint}",
                    {"field": "config_fingerprint", "previous": previous.config_fingerprint, "current": config_fingerprint},
                )

        return self.get_health(agent_id)  # type: ignore[return-value]
```

- [ ] **Step 8: Run all fleet tests**

Run: `uv run pytest tests/test_fleet.py -v`
Expected: ALL PASS

- [ ] **Step 9: Run full test suite**

Run: `uv run pytest -q`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add src/agentic_os/fleet.py tests/test_fleet.py
git commit -m "feat(p5): add FleetStore with health state tracking and drift detection"
```

---

### Task 3: HealthProber — background probe loop with failure isolation

**Files:**
- Create: `src/agentic_os/health_prober.py`
- Create: `tests/test_health_prober.py`

- [ ] **Step 1: Write failing test for probe_one**

```python
# tests/test_health_prober.py

import asyncio
from pathlib import Path

import pytest

from agentic_os.fleet import FleetStore, HealthState
from agentic_os.health_prober import HealthProber
from agentic_os.models import AgentDefinition


def _make_fleet_store(tmp_path: Path) -> FleetStore:
    store = FleetStore(tmp_path / "fleet.db")
    store.init()
    return store


def _agent(
    agent_id: str = "shell",
    health_command: list[str] | None = None,
    version_command: list[str] | None = None,
    config_fingerprint_command: list[str] | None = None,
) -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        label=agent_id,
        command=["/bin/echo", "hi"],
        health_command=health_command,
        version_command=version_command,
        config_fingerprint_command=config_fingerprint_command,
    )


@pytest.mark.asyncio
async def test_probe_one_healthy(tmp_path):
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=10)
    agent = _agent(health_command=["/bin/echo", "OK"])
    await prober.probe_one(agent)
    record = fleet.get_health("shell")
    assert record is not None
    assert record.state == HealthState.UP


@pytest.mark.asyncio
async def test_probe_one_unhealthy_exit_code(tmp_path):
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=10)
    agent = _agent(health_command=["/bin/sh", "-c", "exit 1"])
    await prober.probe_one(agent)
    record = fleet.get_health("shell")
    assert record is not None
    assert record.state == HealthState.DOWN


@pytest.mark.asyncio
async def test_probe_one_timeout(tmp_path):
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=0.1)
    agent = _agent(health_command=["/bin/sleep", "10"])
    await prober.probe_one(agent)
    record = fleet.get_health("shell")
    assert record is not None
    assert record.state == HealthState.DOWN
    assert "timeout" in record.message.lower()


@pytest.mark.asyncio
async def test_probe_one_no_health_command_skips(tmp_path):
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=10)
    agent = _agent(health_command=None)
    await prober.probe_one(agent)
    assert fleet.get_health("shell") is None


@pytest.mark.asyncio
async def test_probe_one_collects_version(tmp_path):
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=10)
    agent = _agent(
        health_command=["/bin/echo", "OK"],
        version_command=["/bin/echo", "2.1.0"],
        config_fingerprint_command=["/bin/echo", "fp_abc"],
    )
    await prober.probe_one(agent)
    record = fleet.get_health("shell")
    assert record is not None
    assert record.version == "2.1.0"
    assert record.config_fingerprint == "fp_abc"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_health_prober.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Install pytest-asyncio dev dependency**

Run: `uv add --dev pytest-asyncio`

- [ ] **Step 4: Implement HealthProber**

```python
# src/agentic_os/health_prober.py

from __future__ import annotations

import asyncio

from agentic_os.fleet import FleetStore, HealthState
from agentic_os.models import AgentDefinition


class HealthProber:
    def __init__(
        self,
        fleet_store: FleetStore,
        timeout_seconds: float = 10.0,
        max_concurrent: int = 10,
    ) -> None:
        self.fleet_store = fleet_store
        self.timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def probe_one(self, agent: AgentDefinition) -> None:
        if agent.health_command is None:
            return
        async with self._semaphore:
            state, message = await self._run_health_command(agent)
            version = await self._run_info_command(agent.version_command)
            fingerprint = await self._run_info_command(agent.config_fingerprint_command)
            self.fleet_store.record_health(
                agent.id,
                state,
                message,
                version=version,
                config_fingerprint=fingerprint,
            )

    async def probe_all(self, agents: list[AgentDefinition]) -> None:
        tasks = [self.probe_one(agent) for agent in agents]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_health_command(
        self, agent: AgentDefinition
    ) -> tuple[HealthState, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *agent.health_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_seconds
            )
            if proc.returncode == 0:
                return HealthState.UP, stdout.decode().strip()
            return HealthState.DOWN, f"exit {proc.returncode}: {stderr.decode().strip()}"
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return HealthState.DOWN, f"timeout after {self.timeout_seconds}s"
        except OSError as exc:
            return HealthState.DOWN, f"launch failed: {exc}"

    async def _run_info_command(self, command: list[str] | None) -> str | None:
        if command is None:
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_seconds
            )
            if proc.returncode == 0:
                return stdout.decode().strip()
            return None
        except (asyncio.TimeoutError, OSError):
            return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_health_prober.py -v`
Expected: ALL PASS

- [ ] **Step 6: Write test for probe_all windowed concurrency**

```python
# tests/test_health_prober.py — append

@pytest.mark.asyncio
async def test_probe_all_multiple_agents(tmp_path):
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=10)
    agents = [
        _agent("a1", health_command=["/bin/echo", "OK"]),
        _agent("a2", health_command=["/bin/sh", "-c", "exit 1"]),
        _agent("a3", health_command=None),
    ]
    await prober.probe_all(agents)
    assert fleet.get_health("a1").state == HealthState.UP
    assert fleet.get_health("a2").state == HealthState.DOWN
    assert fleet.get_health("a3") is None


@pytest.mark.asyncio
async def test_probe_all_isolation_one_failure_does_not_block_others(tmp_path):
    """A failing probe must not prevent other probes from completing (G2)."""
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=0.2)
    agents = [
        _agent("fast", health_command=["/bin/echo", "OK"]),
        _agent("slow", health_command=["/bin/sleep", "10"]),
        _agent("also_fast", health_command=["/bin/echo", "OK"]),
    ]
    await prober.probe_all(agents)
    assert fleet.get_health("fast").state == HealthState.UP
    assert fleet.get_health("slow").state == HealthState.DOWN
    assert fleet.get_health("also_fast").state == HealthState.UP
```

- [ ] **Step 7: Run all prober tests**

Run: `uv run pytest tests/test_health_prober.py -v`
Expected: ALL PASS

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest -q`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add src/agentic_os/health_prober.py tests/test_health_prober.py pyproject.toml uv.lock
git commit -m "feat(p5): add HealthProber with windowed concurrency and timeout isolation"
```

---

### Task 4: Capacity tracking and 429 enforcement

**Files:**
- Modify: `src/agentic_os/fleet.py`
- Modify: `src/agentic_os/api.py`
- Test: `tests/test_fleet.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing test for capacity query**

```python
# tests/test_fleet.py — append

def test_capacity_query(tmp_path):
    store = _make_store(tmp_path)
    capacity = store.get_capacity(running_sessions=5, registered_instances=10)
    assert capacity["running_sessions"] == 5
    assert capacity["max_running_sessions"] == 50
    assert capacity["registered_instances"] == 10
    assert capacity["max_registered_instances"] == 100
    assert capacity["at_session_limit"] is False
    assert capacity["at_instance_limit"] is False


def test_capacity_at_limit(tmp_path):
    store = _make_store(tmp_path)
    capacity = store.get_capacity(running_sessions=50, registered_instances=100)
    assert capacity["at_session_limit"] is True
    assert capacity["at_instance_limit"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fleet.py::test_capacity_query -v`
Expected: FAIL — method does not exist

- [ ] **Step 3: Add get_capacity to FleetStore**

```python
# src/agentic_os/fleet.py — add to FleetStore class

    MAX_RUNNING_SESSIONS = 50
    MAX_REGISTERED_INSTANCES = 100

    def get_capacity(
        self,
        running_sessions: int,
        registered_instances: int,
    ) -> dict[str, object]:
        return {
            "running_sessions": running_sessions,
            "max_running_sessions": self.MAX_RUNNING_SESSIONS,
            "registered_instances": registered_instances,
            "max_registered_instances": self.MAX_REGISTERED_INSTANCES,
            "at_session_limit": running_sessions >= self.MAX_RUNNING_SESSIONS,
            "at_instance_limit": registered_instances >= self.MAX_REGISTERED_INSTANCES,
        }
```

- [ ] **Step 4: Run capacity tests**

Run: `uv run pytest tests/test_fleet.py::test_capacity_query tests/test_fleet.py::test_capacity_at_limit -v`
Expected: ALL PASS

- [ ] **Step 5: Write failing test for 429 on POST /sessions at capacity**

```python
# tests/test_api.py — add at end

def test_run_session_429_at_capacity(tmp_app, tmp_path):
    """POST /sessions returns 429 when concurrent session limit is reached (G4)."""
    client = TestClient(tmp_app)
    # Create 50 sessions in running state to hit the limit.
    # We use the store directly to simulate this.
    from agentic_os.models import SessionCreate, SessionStatus
    store = tmp_app.state.store
    for i in range(50):
        session = store.create_session(
            SessionCreate(
                agent_id="shell",
                cwd="/tmp",
                argv=["/bin/sleep", "999"],
                artifact_dir=str(tmp_path / f"art_{i}"),
                stdout_log=str(tmp_path / f"out_{i}"),
                stderr_log=str(tmp_path / f"err_{i}"),
            )
        )
        store.mark_running(session.id, pid=99900 + i, pgid=99900 + i)

    response = client.post(
        "/sessions",
        json={"agent_id": "shell", "message": "test"},
    )
    assert response.status_code == 429
    assert "capacity" in response.json()["detail"].lower()
```

- [ ] **Step 6: Run 429 test to verify it fails**

Run: `uv run pytest tests/test_api.py::test_run_session_429_at_capacity -v`
Expected: FAIL — no capacity check exists yet

- [ ] **Step 7: Add capacity gate to POST /sessions in api.py**

In `src/agentic_os/api.py`, in the `run_session` function, add a capacity check before the `registry.build_run()` call:

```python
    @app.post("/sessions")
    def run_session(request: SessionRunRequest) -> dict[str, object]:
        _check_capacity()

        try:
            rendered = registry.build_run(request.agent_id, request.cwd, request.message)
        # ... rest unchanged
```

And add the helper inside `create_app`:

```python
    def _check_capacity() -> None:
        running = [
            s for s in store.list_sessions()
            if s.status in {SessionStatus.RUNNING, SessionStatus.QUEUED, SessionStatus.STOPPING}
        ]
        if len(running) >= fleet_store.MAX_RUNNING_SESSIONS:
            raise HTTPException(
                status_code=429,
                detail=f"Capacity limit reached: {len(running)}/{fleet_store.MAX_RUNNING_SESSIONS} concurrent sessions",
            )
```

Also wire `fleet_store` into `create_app`:

```python
    fleet_store = FleetStore(state_dir / "agentic-os.db")
    fleet_store.init()
```

And expose it on `app.state` for test access:

```python
    app.state.store = store
    app.state.fleet_store = fleet_store
```

- [ ] **Step 8: Run the 429 test**

Run: `uv run pytest tests/test_api.py::test_run_session_429_at_capacity -v`
Expected: PASS

- [ ] **Step 9: Add same capacity gate to retry endpoint**

In `retry_session`, add `_check_capacity()` as the first line.

- [ ] **Step 10: Run full test suite**

Run: `uv run pytest -q`
Expected: ALL PASS

- [ ] **Step 11: Commit**

```bash
git add src/agentic_os/fleet.py src/agentic_os/api.py tests/test_fleet.py tests/test_api.py
git commit -m "feat(p5): add capacity tracking with 429 enforcement on session limits"
```

---

### Task 5: Fleet API endpoints

**Files:**
- Modify: `src/agentic_os/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing tests for fleet endpoints**

```python
# tests/test_api.py — append

def test_fleet_health_empty(tmp_app):
    client = TestClient(tmp_app)
    response = client.get("/fleet/health")
    assert response.status_code == 200
    assert response.json()["instances"] == []


def test_fleet_health_after_probe(tmp_app):
    client = TestClient(tmp_app)
    fleet_store = tmp_app.state.fleet_store
    from agentic_os.fleet import HealthState
    fleet_store.record_health("shell", HealthState.UP, "OK", version="1.0.0")
    response = client.get("/fleet/health")
    assert response.status_code == 200
    instances = response.json()["instances"]
    assert len(instances) == 1
    assert instances[0]["agent_id"] == "shell"
    assert instances[0]["state"] == "up"


def test_fleet_instance_health(tmp_app):
    client = TestClient(tmp_app)
    fleet_store = tmp_app.state.fleet_store
    from agentic_os.fleet import HealthState
    fleet_store.record_health("shell", HealthState.UP, "OK")
    response = client.get("/fleet/shell/health")
    assert response.status_code == 200
    assert response.json()["agent_id"] == "shell"


def test_fleet_instance_health_404(tmp_app):
    client = TestClient(tmp_app)
    response = client.get("/fleet/nonexistent/health")
    assert response.status_code == 404


def test_fleet_events(tmp_app):
    client = TestClient(tmp_app)
    fleet_store = tmp_app.state.fleet_store
    from agentic_os.fleet import HealthState
    fleet_store.record_health("shell", HealthState.UP, "OK")
    fleet_store.record_health("shell", HealthState.DOWN, "fail")
    response = client.get("/fleet/events")
    assert response.status_code == 200
    assert len(response.json()["events"]) >= 1


def test_fleet_capacity(tmp_app):
    client = TestClient(tmp_app)
    response = client.get("/fleet/capacity")
    assert response.status_code == 200
    data = response.json()
    assert "running_sessions" in data
    assert "max_running_sessions" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py::test_fleet_health_empty -v`
Expected: FAIL — route does not exist

- [ ] **Step 3: Add fleet endpoints to api.py**

In `src/agentic_os/api.py`, inside `create_app`, add after the policy routes:

```python
    @app.get("/fleet/health")
    def fleet_health() -> dict[str, object]:
        records = fleet_store.list_health()
        return {"instances": [_fleet_health_dict(r) for r in records]}

    @app.get("/fleet/{agent_id}/health")
    def fleet_instance_health(agent_id: str) -> dict[str, object]:
        record = fleet_store.get_health(agent_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"No health data for {agent_id}")
        return _fleet_health_dict(record)

    @app.get("/fleet/events")
    def fleet_events(
        agent_id: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
    ) -> dict[str, object]:
        events = fleet_store.list_events(agent_id=agent_id, event_type=event_type)
        return {"events": [_fleet_event_dict(e) for e in events]}

    @app.get("/fleet/capacity")
    def fleet_capacity() -> dict[str, object]:
        running = [
            s for s in store.list_sessions()
            if s.status in {SessionStatus.RUNNING, SessionStatus.QUEUED, SessionStatus.STOPPING}
        ]
        return fleet_store.get_capacity(
            running_sessions=len(running),
            registered_instances=len(registry.list_agents()),
        )
```

Add helper functions outside `create_app`:

```python
from agentic_os.fleet import FleetStore, HealthRecord, FleetEvent

def _fleet_health_dict(record: HealthRecord) -> dict[str, object]:
    return {
        "agent_id": record.agent_id,
        "state": record.state.value,
        "message": record.message,
        "version": record.version,
        "config_fingerprint": record.config_fingerprint,
        "updated_at": record.updated_at,
    }


def _fleet_event_dict(event: FleetEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "agent_id": event.agent_id,
        "event_type": event.event_type,
        "message": event.message,
        "metadata": event.metadata,
        "created_at": event.created_at,
    }
```

- [ ] **Step 4: Run fleet API tests**

Run: `uv run pytest tests/test_api.py -k fleet -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat(p5): add fleet health, events, and capacity API endpoints"
```

---

### Task 6: Fleet prober startup integration

**Files:**
- Modify: `src/agentic_os/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write test for prober trigger endpoint**

```python
# tests/test_api.py — append

def test_fleet_probe_trigger(tmp_app):
    """POST /fleet/probe triggers a health probe cycle."""
    client = TestClient(tmp_app)
    response = client.post("/fleet/probe")
    assert response.status_code == 200
    assert response.json()["probed"] >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py::test_fleet_probe_trigger -v`
Expected: FAIL — route does not exist

- [ ] **Step 3: Add POST /fleet/probe endpoint and startup event**

In `src/agentic_os/api.py`, add the probe trigger and a startup lifespan for periodic probing:

```python
from agentic_os.health_prober import HealthProber

# Inside create_app, after fleet_store.init():
    prober = HealthProber(fleet_store)

    @app.post("/fleet/probe")
    def fleet_probe() -> dict[str, object]:
        import asyncio
        agents = registry.list_agents()
        probeable = [a for a in agents if a.health_command is not None]
        loop = asyncio.get_event_loop()
        loop.run_until_complete(prober.probe_all(probeable))
        return {"probed": len(probeable)}
```

Note: since FastAPI runs in an async context, we need to handle this carefully. The endpoint should be async:

```python
    @app.post("/fleet/probe")
    async def fleet_probe() -> dict[str, object]:
        agents = registry.list_agents()
        probeable = [a for a in agents if a.health_command is not None]
        await prober.probe_all(probeable)
        return {"probed": len(probeable)}
```

- [ ] **Step 4: Run the probe test**

Run: `uv run pytest tests/test_api.py::test_fleet_probe_trigger -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat(p5): add POST /fleet/probe endpoint for on-demand health probing"
```

---

### Task 7: Fleet client methods and CLI commands

**Files:**
- Modify: `src/agentic_os/client.py`
- Modify: `src/agentic_os/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add fleet methods to AgenticClient**

```python
# src/agentic_os/client.py — add to AgenticClient class

    def fleet_health(self) -> dict[str, Any]:
        return self._get("/fleet/health")

    def fleet_instance_health(self, agent_id: str) -> dict[str, Any]:
        return self._get(f"/fleet/{_validate_path_id(agent_id)}/health")

    def fleet_events(
        self,
        agent_id: str | None = None,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, object] = {}
        if agent_id is not None:
            params["agent_id"] = agent_id
        if event_type is not None:
            params["event_type"] = event_type
        return self._get("/fleet/events", params=params)

    def fleet_capacity(self) -> dict[str, Any]:
        return self._get("/fleet/capacity")

    def fleet_probe(self) -> dict[str, Any]:
        return self._post("/fleet/probe", {})
```

- [ ] **Step 2: Add fleet CLI commands**

```python
# src/agentic_os/cli.py — add after existing typer groups

fleet = typer.Typer(help="Inspect fleet health, events, and capacity.")
app.add_typer(fleet, name="fleet")


@fleet.command("health")
def fleet_health(
    agent_id: str | None = typer.Argument(None, help="Show health for a specific agent."),
    api: str | None = _api_option(),
) -> None:
    client = make_client(api)
    if agent_id:
        data = _run_api_call(lambda: client.fleet_instance_health(agent_id))
        _echo_json(data)
        return
    data = _run_api_call(client.fleet_health)
    for instance in data.get("instances", []):
        typer.echo(
            f"{instance['agent_id']}\t{instance['state']}\t"
            f"{instance.get('version', '-')}\t{instance['message']}"
        )


@fleet.command("events")
def fleet_events(
    agent_id: str | None = typer.Option(None, "--agent", help="Filter by agent."),
    event_type: str | None = typer.Option(None, "--type", help="Filter by event type."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(
        lambda: make_client(api).fleet_events(agent_id=agent_id, event_type=event_type)
    )
    for event in data.get("events", []):
        typer.echo(
            f"{event.get('id', '-')}\t{event['agent_id']}\t"
            f"{event['event_type']}\t{event['message']}\t{event['created_at']}"
        )


@fleet.command("capacity")
def fleet_capacity_cmd(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).fleet_capacity())
    typer.echo(
        f"sessions: {data['running_sessions']}/{data['max_running_sessions']}"
    )
    typer.echo(
        f"instances: {data['registered_instances']}/{data['max_registered_instances']}"
    )


@fleet.command("probe")
def fleet_probe_cmd(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).fleet_probe())
    typer.echo(f"Probed {data['probed']} instances")
```

- [ ] **Step 3: Write CLI tests**

```python
# tests/test_cli.py — append (follow existing test patterns using subprocess)

def test_fleet_health_cli(cli_env):
    result = _run_cli(cli_env, ["fleet", "health"])
    assert result.returncode == 0


def test_fleet_events_cli(cli_env):
    result = _run_cli(cli_env, ["fleet", "events"])
    assert result.returncode == 0


def test_fleet_capacity_cli(cli_env):
    result = _run_cli(cli_env, ["fleet", "capacity"])
    assert result.returncode == 0
    assert "sessions:" in result.stdout
    assert "instances:" in result.stdout


def test_fleet_probe_cli(cli_env):
    result = _run_cli(cli_env, ["fleet", "probe"])
    assert result.returncode == 0
    assert "Probed" in result.stdout
```

Note: adapt these to match the existing `cli_env` and `_run_cli` fixture patterns in `tests/test_cli.py`.

- [ ] **Step 4: Run CLI tests**

Run: `uv run pytest tests/test_cli.py -k fleet -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/client.py src/agentic_os/cli.py tests/test_cli.py
git commit -m "feat(p5): add fleet CLI commands and client methods"
```

---

### Task 8: UI fleet health panel

**Files:**
- Modify: `apps/web/index.html`
- Modify: `apps/web/app.js`
- Test: `tests/test_web.py`

- [ ] **Step 1: Add Fleet tab to index.html**

In `apps/web/index.html`, add a Fleet tab button next to the existing tabs in the nav:

```html
<button class="tab-btn" data-tab="fleet">Fleet</button>
```

And a Fleet tab panel:

```html
<div class="tab-panel" id="fleet-panel" style="display:none">
  <h2>Fleet Health</h2>
  <button id="fleet-probe-btn">Probe Now</button>
  <div id="fleet-health-list"></div>
  <h3>Capacity</h3>
  <div id="fleet-capacity"></div>
  <h3>Fleet Events</h3>
  <div id="fleet-events-list"></div>
</div>
```

- [ ] **Step 2: Add fleet rendering to app.js**

Add to `app.js`:

```javascript
const FLEET_HEALTH_URL = `${API_BASE}/fleet/health`;
const FLEET_EVENTS_URL = `${API_BASE}/fleet/events`;
const FLEET_CAPACITY_URL = `${API_BASE}/fleet/capacity`;
const FLEET_PROBE_URL = `${API_BASE}/fleet/probe`;

async function loadFleetHealth() {
  const el = document.getElementById("fleet-health-list");
  try {
    const res = await fetch(FLEET_HEALTH_URL);
    const data = await res.json();
    if (!data.instances || data.instances.length === 0) {
      el.innerHTML = "<p>No fleet health data. Click Probe Now.</p>";
      return;
    }
    el.innerHTML = "<table><thead><tr><th>Instance</th><th>State</th><th>Version</th><th>Message</th><th>Updated</th></tr></thead><tbody>"
      + data.instances.map(i =>
        `<tr><td>${esc(i.agent_id)}</td><td>${esc(i.state)}</td><td>${esc(i.version || "-")}</td><td>${esc(i.message)}</td><td>${esc(i.updated_at)}</td></tr>`
      ).join("")
      + "</tbody></table>";
  } catch (e) {
    el.innerHTML = `<p class="error">${esc(String(e))}</p>`;
  }
}

async function loadFleetCapacity() {
  const el = document.getElementById("fleet-capacity");
  try {
    const res = await fetch(FLEET_CAPACITY_URL);
    const data = await res.json();
    el.innerHTML = `<p>Sessions: ${data.running_sessions}/${data.max_running_sessions} | Instances: ${data.registered_instances}/${data.max_registered_instances}</p>`;
  } catch (e) {
    el.innerHTML = `<p class="error">${esc(String(e))}</p>`;
  }
}

async function loadFleetEvents() {
  const el = document.getElementById("fleet-events-list");
  try {
    const res = await fetch(FLEET_EVENTS_URL);
    const data = await res.json();
    if (!data.events || data.events.length === 0) {
      el.innerHTML = "<p>No fleet events.</p>";
      return;
    }
    el.innerHTML = "<table><thead><tr><th>ID</th><th>Instance</th><th>Type</th><th>Message</th><th>Time</th></tr></thead><tbody>"
      + data.events.map(e =>
        `<tr><td>${e.id}</td><td>${esc(e.agent_id)}</td><td>${esc(e.event_type)}</td><td>${esc(e.message)}</td><td>${esc(e.created_at)}</td></tr>`
      ).join("")
      + "</tbody></table>";
  } catch (e) {
    el.innerHTML = `<p class="error">${esc(String(e))}</p>`;
  }
}

function setupFleetTab() {
  const probeBtn = document.getElementById("fleet-probe-btn");
  if (probeBtn) {
    probeBtn.addEventListener("click", async () => {
      probeBtn.disabled = true;
      probeBtn.textContent = "Probing...";
      try {
        await fetch(FLEET_PROBE_URL, { method: "POST" });
        await loadFleetHealth();
        await loadFleetCapacity();
        await loadFleetEvents();
      } finally {
        probeBtn.disabled = false;
        probeBtn.textContent = "Probe Now";
      }
    });
  }
}
```

Wire the Fleet tab into the tab switch handler and call `setupFleetTab()` on init.

- [ ] **Step 3: Write web test for Fleet tab presence**

```python
# tests/test_web.py — append

def test_fleet_tab_exists(index_html):
    assert 'data-tab="fleet"' in index_html


def test_fleet_panel_exists(index_html):
    assert 'id="fleet-panel"' in index_html
    assert 'id="fleet-health-list"' in index_html
    assert 'id="fleet-capacity"' in index_html


def test_fleet_api_constants_in_js(app_js):
    assert "/fleet/health" in app_js
    assert "/fleet/events" in app_js
    assert "/fleet/capacity" in app_js
    assert "/fleet/probe" in app_js
```

Note: adapt to match the existing `index_html` and `app_js` fixture patterns in `tests/test_web.py`.

- [ ] **Step 4: Run web tests**

Run: `uv run pytest tests/test_web.py -k fleet -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add apps/web/index.html apps/web/app.js tests/test_web.py
git commit -m "feat(p5): add fleet health panel to web UI"
```

---

### Task 9: Final integration, lint, and documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `specs/008-harness-fleet-control-plane-goals.md`

- [ ] **Step 1: Run ruff lint and format**

Run: `uv run ruff check . && uv run ruff format .`
Expected: clean

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -q`
Expected: ALL PASS (target ~220+ tests)

- [ ] **Step 3: Update README with P5 usage section**

Add a "Run P5 Fleet Health" section to README.md after the P3.5/P3.6 section:

```markdown
## Run P5 Fleet Health

Start the daemon:

```bash
rtk uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Probe fleet health:

```bash
rtk uv run agentctl fleet probe
rtk uv run agentctl fleet health
rtk uv run agentctl fleet health shell
rtk uv run agentctl fleet events
rtk uv run agentctl fleet capacity
```

Use the UI Fleet tab to see health state, capacity, and events.

P5 does not start harnesses, install capabilities, execute tools, or manage
MCP server processes. It probes health commands defined in `agents.toml`,
records state transitions and drift events, and enforces capacity limits.
```

- [ ] **Step 4: Update CLAUDE.md phase table**

Add P5 row to the phase scope table:

```
| P5 | fleet inventory, health probes, drift detection, capacity enforcement | harness internals, capability installation, MCP server management |
```

- [ ] **Step 5: Mark spec 008 P5 as implemented**

Update `specs/008-harness-fleet-control-plane-goals.md` Phase Roadmap table to mark P5 as implemented.

- [ ] **Step 6: Run final test suite**

Run: `uv run pytest -q && uv run ruff check .`
Expected: ALL PASS, clean lint

- [ ] **Step 7: Commit**

```bash
git add README.md CLAUDE.md specs/008-harness-fleet-control-plane-goals.md
git commit -m "docs(p5): update README, CLAUDE.md, and spec 008 for P5 fleet health"
```
