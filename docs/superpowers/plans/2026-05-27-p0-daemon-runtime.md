# P0 Harness Manager Substrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the P0 `agentd` daemon and `agentctl` CLI so local harness instances can be registered and Harness Sessions can be started, logged, listed, stopped, and retried.

**Architecture:** Use a small Python package with focused modules: Harness Instance Registry loading, SQLite metadata, JSONL log storage, process supervision, FastAPI routes, and Typer CLI. The daemon owns local Harness Run launch/supervision; the CLI only talks to the daemon HTTP API. Runtime state lives under `.agentic-os/`.

**Tech Stack:** Python 3.12 via `mise`/`uv`, FastAPI, Uvicorn, Typer, Pydantic, stdlib `sqlite3`, stdlib `subprocess`, pytest.

---

## Scope Check

The spec is focused enough for one implementation plan. P0 includes daemon, CLI, Harness Instance Registry, Harness Sessions, logs, artifacts, process control, retry, and reconciliation. P0 excludes UI, memory pipeline, Shared Capability Catalog / Harness Launch Policy editing, semantic indexing, auth, and multi-user mode.

## File Map

- Create `pyproject.toml`: package metadata, dependencies, CLI entrypoints, pytest config.
- Create `src/agentic_os/__init__.py`: package version.
- Create `src/agentic_os/models.py`: Pydantic/domain models and session states.
- Create `src/agentic_os/registry.py`: TOML registry loader and command template renderer.
- Create `src/agentic_os/storage.py`: SQLite schema and metadata repository.
- Create `src/agentic_os/logs.py`: append-only JSONL log writer/reader.
- Create `src/agentic_os/supervisor.py`: local process group runner, stop, retry, and reconciliation.
- Create `src/agentic_os/api.py`: FastAPI application and typed routes.
- Create `src/agentic_os/daemon.py`: `agentd` command entrypoint.
- Create `src/agentic_os/client.py`: HTTP client used by CLI.
- Create `src/agentic_os/cli.py`: `agentctl` Typer CLI.
- Create `examples/agents.toml`: OpenClaw, Hermes, and harmless local shell examples.
- Modify `README.md`: P0 run and smoke instructions.
- Test `tests/test_registry.py`: registry load and command rendering.
- Test `tests/test_storage.py`: SQLite schema, session lifecycle, events.
- Test `tests/test_logs.py`: JSONL append/read/filter/cursor behavior.
- Test `tests/test_supervisor.py`: process success, failure, stop, retry, reconciliation.
- Test `tests/test_api.py`: daemon routes with a temporary state directory.
- Test `tests/test_cli.py`: CLI command formatting through a fake client.

## Task 1: Python Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/agentic_os/__init__.py`
- Create: `tests/test_package.py`
- Modify: `README.md`

- [ ] **Step 1: Write the failing package smoke test**

Create `tests/test_package.py`:

```python
from agentic_os import __version__


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_package.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentic_os'`.

- [ ] **Step 3: Create package metadata and package module**

Create `pyproject.toml`:

```toml
[project]
name = "agentic-os"
version = "0.1.0"
description = "Local Harness Manager substrate for local harnesses"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115.0",
  "httpx>=0.27.0",
  "pydantic>=2.8.0",
  "typer>=0.12.0",
  "uvicorn>=0.30.0",
]

[project.scripts]
agentd = "agentic_os.daemon:app"
agentctl = "agentic_os.cli:app"

[dependency-groups]
dev = [
  "pytest>=8.2.0",
  "ruff>=0.6.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

Create `src/agentic_os/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/test_package.py -q
```

Expected: PASS, `1 passed`.

- [ ] **Step 5: Add README development commands**

Append to `README.md`:

````markdown
## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
```
````

- [ ] **Step 6: Commit scaffold**

Run:

```bash
git add pyproject.toml src/agentic_os/__init__.py tests/test_package.py README.md
git commit -m "chore: scaffold python package"
```

Expected: commit succeeds.

## Task 2: Domain Models And SQLite Store

**Files:**
- Create: `src/agentic_os/models.py`
- Create: `src/agentic_os/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_storage.py`:

```python
from pathlib import Path

from agentic_os.models import SessionCreate, SessionStatus
from agentic_os.storage import Store


def test_store_creates_and_updates_session(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()

    session = store.create_session(
        SessionCreate(
            agent_id="shell",
            cwd=str(tmp_path),
            argv=["/bin/echo", "OK"],
            artifact_dir=str(tmp_path / "sessions" / "s_1"),
            stdout_log=str(tmp_path / "sessions" / "s_1" / "stdout.jsonl"),
            stderr_log=str(tmp_path / "sessions" / "s_1" / "stderr.jsonl"),
        )
    )

    assert session.id.startswith("s_")
    assert session.status == SessionStatus.QUEUED

    updated = store.mark_running(session.id, pid=123, pgid=123)
    assert updated.status == SessionStatus.RUNNING
    assert updated.pid == 123
    assert updated.pgid == 123

    finished = store.mark_finished(session.id, exit_code=0)
    assert finished.status == SessionStatus.SUCCEEDED
    assert finished.exit_code == 0


def test_store_records_events(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()
    session = store.create_session(
        SessionCreate(
            agent_id="shell",
            cwd=str(tmp_path),
            argv=["/bin/echo", "OK"],
            artifact_dir=str(tmp_path / "sessions" / "s_1"),
            stdout_log=str(tmp_path / "sessions" / "s_1" / "stdout.jsonl"),
            stderr_log=str(tmp_path / "sessions" / "s_1" / "stderr.jsonl"),
        )
    )

    store.record_event(session.id, "launch_failed", "missing executable", {"argv": ["missing"]})

    events = store.list_events(session.id)
    assert len(events) == 1
    assert events[0].event_type == "launch_failed"
    assert events[0].metadata == {"argv": ["missing"]}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_storage.py -q
```

Expected: FAIL with missing `agentic_os.models` or `agentic_os.storage`.

- [ ] **Step 3: Implement models**

Create `src/agentic_os/models.py`:

```python
from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    STOPPING = "stopping"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"


CwdMode = Literal["required", "optional", "ignored"]
StopPolicy = Literal["process_group"]


class AgentDefinition(BaseModel):
    id: str
    label: str
    command: list[str]
    cwd_mode: CwdMode = "optional"
    env: dict[str, str] = Field(default_factory=dict)
    stop_policy: StopPolicy = "process_group"
    health_command: list[str] | None = None
    enabled: bool = True


class SessionCreate(BaseModel):
    agent_id: str
    cwd: str
    argv: list[str]
    artifact_dir: str
    stdout_log: str
    stderr_log: str
    summary_one_liner: str = ""


class SessionRecord(SessionCreate):
    id: str
    status: SessionStatus
    pid: int | None = None
    pgid: int | None = None
    exit_code: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    updated_at: str


class EventRecord(BaseModel):
    id: int
    session_id: str
    event_type: str
    message: str
    metadata: dict[str, Any]
    created_at: str


class RunRequest(BaseModel):
    cwd: str
    message: str
```

- [ ] **Step 4: Implement SQLite store**

Create `src/agentic_os/storage.py`:

```python
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from agentic_os.models import EventRecord, SessionCreate, SessionRecord, SessionStatus


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  command_json TEXT NOT NULL,
  cwd_mode TEXT NOT NULL,
  env_json TEXT NOT NULL DEFAULT '{}',
  stop_policy TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  cwd TEXT NOT NULL,
  argv_json TEXT NOT NULL,
  status TEXT NOT NULL,
  pid INTEGER,
  pgid INTEGER,
  exit_code INTEGER,
  artifact_dir TEXT NOT NULL,
  stdout_log TEXT NOT NULL,
  stderr_log TEXT NOT NULL,
  summary_one_liner TEXT NOT NULL DEFAULT '',
  started_at TEXT,
  ended_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_session(self, request: SessionCreate) -> SessionRecord:
        session_id = f"s_{uuid.uuid4().hex}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                  id, agent_id, cwd, argv_json, status, artifact_dir,
                  stdout_log, stderr_log, summary_one_liner, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    session_id,
                    request.agent_id,
                    request.cwd,
                    json.dumps(request.argv),
                    SessionStatus.QUEUED.value,
                    request.artifact_dir,
                    request.stdout_log,
                    request.stderr_log,
                    request.summary_one_liner,
                ),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> SessionRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return _session_from_row(row)

    def list_sessions(self) -> list[SessionRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC, id DESC").fetchall()
        return [_session_from_row(row) for row in rows]

    def mark_running(self, session_id: str, pid: int, pgid: int) -> SessionRecord:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, pid = ?, pgid = ?, started_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (SessionStatus.RUNNING.value, pid, pgid, session_id),
            )
        return self.get_session(session_id)

    def mark_stopping(self, session_id: str) -> SessionRecord:
        return self._set_status(session_id, SessionStatus.STOPPING)

    def mark_stopped(self, session_id: str) -> SessionRecord:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, ended_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (SessionStatus.STOPPED.value, session_id),
            )
        return self.get_session(session_id)

    def mark_failed(self, session_id: str, exit_code: int | None = None) -> SessionRecord:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, exit_code = ?, ended_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (SessionStatus.FAILED.value, exit_code, session_id),
            )
        return self.get_session(session_id)

    def mark_finished(self, session_id: str, exit_code: int) -> SessionRecord:
        status = SessionStatus.SUCCEEDED if exit_code == 0 else SessionStatus.FAILED
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, exit_code = ?, ended_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status.value, exit_code, session_id),
            )
        return self.get_session(session_id)

    def record_event(
        self,
        session_id: str,
        event_type: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO events (session_id, event_type, message, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, event_type, message, json.dumps(metadata or {})),
            )

    def list_events(self, session_id: str) -> list[EventRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [
            EventRecord(
                id=row["id"],
                session_id=row["session_id"],
                event_type=row["event_type"],
                message=row["message"],
                metadata=json.loads(row["metadata_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _set_status(self, session_id: str, status: SessionStatus) -> SessionRecord:
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status.value, session_id),
            )
        return self.get_session(session_id)


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        agent_id=row["agent_id"],
        cwd=row["cwd"],
        argv=json.loads(row["argv_json"]),
        status=SessionStatus(row["status"]),
        pid=row["pid"],
        pgid=row["pgid"],
        exit_code=row["exit_code"],
        artifact_dir=row["artifact_dir"],
        stdout_log=row["stdout_log"],
        stderr_log=row["stderr_log"],
        summary_one_liner=row["summary_one_liner"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        updated_at=row["updated_at"],
    )
```

- [ ] **Step 5: Run storage tests**

Run:

```bash
uv run pytest tests/test_storage.py -q
```

Expected: PASS, `2 passed`.

- [ ] **Step 6: Commit storage layer**

Run:

```bash
git add src/agentic_os/models.py src/agentic_os/storage.py tests/test_storage.py
git commit -m "feat: add session metadata store"
```

Expected: commit succeeds.

## Task 3: Harness Instance Registry And Command Rendering

The implementation keeps the existing `agents` file/API names, but the
positioning is Harness Instance Registry rather than ownership of the underlying
harness internals.

**Files:**
- Create: `src/agentic_os/registry.py`
- Create: `examples/agents.toml`
- Create: `tests/test_registry.py`

- [ ] **Step 1: Write failing registry tests**

Create `tests/test_registry.py`:

```python
from pathlib import Path

import pytest

from agentic_os.registry import Registry, render_command


def test_registry_loads_agents(tmp_path: Path) -> None:
    config = tmp_path / "agents.toml"
    config.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/bin/echo", "{{message}}"]
cwd_mode = "required"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )

    registry = Registry(config)
    agents = registry.list_agents()

    assert [agent.id for agent in agents] == ["shell"]
    assert registry.get("shell").label == "Shell"


def test_render_command_replaces_message() -> None:
    assert render_command(["/bin/echo", "{{message}}"], message="OK") == ["/bin/echo", "OK"]


def test_registry_rejects_missing_required_cwd(tmp_path: Path) -> None:
    config = tmp_path / "agents.toml"
    config.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/bin/echo", "{{message}}"]
cwd_mode = "required"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )

    registry = Registry(config)

    with pytest.raises(ValueError, match="cwd is required"):
        registry.build_run("shell", cwd=None, message="OK")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_registry.py -q
```

Expected: FAIL with missing `agentic_os.registry`.

- [ ] **Step 3: Implement registry**

Create `src/agentic_os/registry.py`:

```python
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from agentic_os.models import AgentDefinition


@dataclass(frozen=True)
class RenderedRun:
    agent: AgentDefinition
    cwd: str
    argv: list[str]


class Registry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._agents = self._load()

    def list_agents(self) -> list[AgentDefinition]:
        return sorted(self._agents.values(), key=lambda agent: agent.id)

    def get(self, agent_id: str) -> AgentDefinition:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent: {agent_id}") from exc

    def build_run(self, agent_id: str, cwd: str | None, message: str) -> RenderedRun:
        agent = self.get(agent_id)
        if agent.cwd_mode == "required" and not cwd:
            raise ValueError("cwd is required")
        run_cwd = str(Path(cwd).expanduser().resolve()) if cwd else str(Path.cwd())
        if agent.cwd_mode != "ignored" and not Path(run_cwd).exists():
            raise ValueError(f"cwd does not exist: {run_cwd}")
        return RenderedRun(agent=agent, cwd=run_cwd, argv=render_command(agent.command, message))

    def _load(self) -> dict[str, AgentDefinition]:
        if not self.path.exists():
            return {}
        data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        agents = {}
        for raw_agent in data.get("agents", []):
            agent = AgentDefinition.model_validate(raw_agent)
            agents[agent.id] = agent
        return agents


def render_command(command: list[str], message: str) -> list[str]:
    return [part.replace("{{message}}", message) for part in command]
```

- [ ] **Step 4: Add example registry**

Create `examples/agents.toml`:

```toml
[[agents]]
id = "shell"
label = "Shell Smoke"
command = ["/usr/bin/printf", "%s\n", "{{message}}"]
cwd_mode = "optional"
stop_policy = "process_group"
health_command = ["/usr/bin/printf", "OK"]

[[agents]]
id = "openclaw"
label = "OpenClaw"
command = ["openclaw", "agent", "--message", "{{message}}", "--json"]
cwd_mode = "required"
stop_policy = "process_group"
health_command = ["openclaw", "status", "--json"]

[[agents]]
id = "hermes"
label = "Hermes"
command = ["hermes", "chat", "--query", "{{message}}", "--quiet", "--source", "agentic-os"]
cwd_mode = "optional"
stop_policy = "process_group"
health_command = ["hermes", "status"]
```

- [ ] **Step 5: Run registry tests**

Run:

```bash
uv run pytest tests/test_registry.py -q
```

Expected: PASS, `3 passed`.

- [ ] **Step 6: Commit registry**

Run:

```bash
git add src/agentic_os/registry.py examples/agents.toml tests/test_registry.py
git commit -m "feat: add harness instance registry"
```

Expected: commit succeeds.

## Task 4: JSONL Logs And Artifact Paths

**Files:**
- Create: `src/agentic_os/logs.py`
- Create: `tests/test_logs.py`

- [ ] **Step 1: Write failing log tests**

Create `tests/test_logs.py`:

```python
from pathlib import Path

from agentic_os.logs import JsonlLogStore


def test_log_store_appends_and_reads_lines(tmp_path: Path) -> None:
    store = JsonlLogStore()
    path = tmp_path / "stdout.jsonl"

    store.append(path, session_id="s_1", stream="stdout", line="hello")
    store.append(path, session_id="s_1", stream="stdout", line="world")

    entries = store.read(path)
    assert [entry.line for entry in entries] == ["hello", "world"]
    assert entries[0].stream == "stdout"


def test_log_store_filters_after_cursor(tmp_path: Path) -> None:
    store = JsonlLogStore()
    path = tmp_path / "stdout.jsonl"

    store.append(path, session_id="s_1", stream="stdout", line="one")
    store.append(path, session_id="s_1", stream="stdout", line="two")

    entries = store.read(path, after=1)
    assert [entry.line for entry in entries] == ["two"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_logs.py -q
```

Expected: FAIL with missing `agentic_os.logs`.

- [ ] **Step 3: Implement JSONL log store**

Create `src/agentic_os/logs.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


StreamName = Literal["stdout", "stderr"]


class LogEntry(BaseModel):
    ts: str
    stream: StreamName
    session_id: str
    line: str
    index: int


class JsonlLogStore:
    def append(self, path: Path, session_id: str, stream: StreamName, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stream": stream,
            "session_id": session_id,
            "line": line,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def read(self, path: Path, after: int = 0) -> list[LogEntry]:
        if not path.exists():
            return []
        entries = []
        with path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index < after:
                    continue
                raw = json.loads(line)
                entries.append(
                    LogEntry(
                        ts=raw["ts"],
                        stream=raw["stream"],
                        session_id=raw["session_id"],
                        line=raw["line"],
                        index=index + 1,
                    )
                )
        return entries

    def read_merged(
        self,
        stdout_path: Path,
        stderr_path: Path,
        stream: StreamName | None = None,
        after: int = 0,
    ) -> list[LogEntry]:
        if stream == "stdout":
            return self.read(stdout_path, after=after)
        if stream == "stderr":
            return self.read(stderr_path, after=after)
        entries = [*self.read(stdout_path), *self.read(stderr_path)]
        entries.sort(key=lambda entry: entry.ts)
        return entries[after:]
```

- [ ] **Step 4: Run log tests**

Run:

```bash
uv run pytest tests/test_logs.py -q
```

Expected: PASS, `2 passed`.

- [ ] **Step 5: Commit log store**

Run:

```bash
git add src/agentic_os/logs.py tests/test_logs.py
git commit -m "feat: add append-only jsonl logs"
```

Expected: commit succeeds.

## Task 5: Process Supervisor

**Files:**
- Create: `src/agentic_os/supervisor.py`
- Create: `tests/test_supervisor.py`

- [ ] **Step 1: Write failing supervisor tests**

Create `tests/test_supervisor.py`:

```python
import time
from pathlib import Path

from agentic_os.logs import JsonlLogStore
from agentic_os.models import SessionCreate, SessionStatus
from agentic_os.storage import Store
from agentic_os.supervisor import ProcessSupervisor


def make_supervisor(tmp_path: Path) -> ProcessSupervisor:
    store = Store(tmp_path / "agentic-os.db")
    store.init()
    return ProcessSupervisor(store=store, logs=JsonlLogStore(), state_dir=tmp_path)


def wait_until_done(supervisor: ProcessSupervisor, session_id: str) -> None:
    for _ in range(50):
        session = supervisor.store.get_session(session_id)
        if session.status in {SessionStatus.SUCCEEDED, SessionStatus.FAILED, SessionStatus.STOPPED}:
            return
        time.sleep(0.05)
    raise AssertionError("session did not finish")


def test_supervisor_runs_successful_command(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=["/bin/sh", "-lc", "printf OK"],
    )
    wait_until_done(supervisor, session.id)

    finished = supervisor.store.get_session(session.id)
    assert finished.status == SessionStatus.SUCCEEDED
    assert finished.exit_code == 0
    assert Path(finished.artifact_dir).exists()
    assert supervisor.logs.read(Path(finished.stdout_log))[0].line == "OK"


def test_supervisor_marks_failed_command(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=["/bin/sh", "-lc", "printf nope >&2; exit 7"],
    )
    wait_until_done(supervisor, session.id)

    finished = supervisor.store.get_session(session.id)
    assert finished.status == SessionStatus.FAILED
    assert finished.exit_code == 7
    assert supervisor.logs.read(Path(finished.stderr_log))[0].line == "nope"


def test_supervisor_stops_process_group(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=["/bin/sh", "-lc", "sleep 10"],
    )
    running = supervisor.store.get_session(session.id)
    assert running.status == SessionStatus.RUNNING

    stopped = supervisor.stop(session.id, timeout_seconds=0.1)

    assert stopped.status == SessionStatus.STOPPED
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_supervisor.py -q
```

Expected: FAIL with missing `agentic_os.supervisor`.

- [ ] **Step 3: Implement supervisor**

Create `src/agentic_os/supervisor.py`:

```python
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from agentic_os.logs import JsonlLogStore
from agentic_os.models import SessionCreate, SessionRecord, SessionStatus
from agentic_os.storage import Store


class ProcessSupervisor:
    def __init__(self, store: Store, logs: JsonlLogStore, state_dir: Path) -> None:
        self.store = store
        self.logs = logs
        self.state_dir = state_dir
        self._processes: dict[str, subprocess.Popen[str]] = {}

    def start(self, agent_id: str, cwd: str, argv: list[str]) -> SessionRecord:
        session_id_hint = "pending"
        session_dir = self.state_dir / "sessions" / session_id_hint
        session = self.store.create_session(
            SessionCreate(
                agent_id=agent_id,
                cwd=cwd,
                argv=argv,
                artifact_dir=str(session_dir / "artifacts"),
                stdout_log=str(session_dir / "stdout.jsonl"),
                stderr_log=str(session_dir / "stderr.jsonl"),
            )
        )
        session_dir = self.state_dir / "sessions" / session.id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        self._move_session_paths(session.id, session_dir)
        session = self.store.get_session(session.id)

        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            self.store.record_event(session.id, "launch_failed", str(exc), {"argv": argv})
            self.logs.append(Path(session.stderr_log), session.id, "stderr", str(exc))
            return self.store.mark_failed(session.id)

        pgid = os.getpgid(process.pid)
        self._processes[session.id] = process
        session = self.store.mark_running(session.id, pid=process.pid, pgid=pgid)

        threading.Thread(
            target=self._pipe_reader,
            args=(session.id, process.stdout, Path(session.stdout_log), "stdout"),
            daemon=True,
        ).start()
        threading.Thread(
            target=self._pipe_reader,
            args=(session.id, process.stderr, Path(session.stderr_log), "stderr"),
            daemon=True,
        ).start()
        threading.Thread(target=self._waiter, args=(session.id, process), daemon=True).start()
        return session

    def stop(self, session_id: str, timeout_seconds: float = 5.0) -> SessionRecord:
        session = self.store.mark_stopping(session_id)
        process = self._processes.get(session_id)
        if process is None or process.poll() is not None:
            return self.store.mark_stopped(session_id)

        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if process.poll() is not None:
                return self.store.mark_stopped(session_id)
            time.sleep(0.05)

        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        self.store.record_event(session_id, "stop_escalated", "sent SIGKILL", {"pid": process.pid})
        return self.store.mark_stopped(session_id)

    def retry(self, session_id: str) -> SessionRecord:
        previous = self.store.get_session(session_id)
        return self.start(previous.agent_id, previous.cwd, previous.argv)

    def reconcile(self) -> None:
        for session in self.store.list_sessions():
            if session.status != SessionStatus.RUNNING or session.pid is None:
                continue
            if not _pid_exists(session.pid):
                self.store.record_event(
                    session.id,
                    "daemon_reconciled_missing_process",
                    "recorded pid is gone",
                    {"pid": session.pid},
                )
                self.store.mark_failed(session.id)

    def _pipe_reader(self, session_id: str, pipe: object, path: Path, stream: str) -> None:
        if pipe is None:
            return
        for raw_line in pipe:
            self.logs.append(path, session_id, stream, raw_line.rstrip("\n"))

    def _waiter(self, session_id: str, process: subprocess.Popen[str]) -> None:
        exit_code = process.wait()
        current = self.store.get_session(session_id)
        if current.status in {SessionStatus.STOPPING, SessionStatus.STOPPED}:
            self.store.mark_stopped(session_id)
        else:
            self.store.mark_finished(session_id, exit_code)
        self._processes.pop(session_id, None)

    def _move_session_paths(self, session_id: str, session_dir: Path) -> None:
        with self.store.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET artifact_dir = ?, stdout_log = ?, stderr_log = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    str(session_dir / "artifacts"),
                    str(session_dir / "stdout.jsonl"),
                    str(session_dir / "stderr.jsonl"),
                    session_id,
                ),
            )


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
```

- [ ] **Step 4: Run supervisor tests**

Run:

```bash
uv run pytest tests/test_supervisor.py -q
```

Expected: PASS, `3 passed`.

- [ ] **Step 5: Commit supervisor**

Run:

```bash
git add src/agentic_os/supervisor.py tests/test_supervisor.py
git commit -m "feat: supervise local harness processes"
```

Expected: commit succeeds.

## Task 6: FastAPI Daemon Routes

**Files:**
- Create: `src/agentic_os/api.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_api.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from agentic_os.api import create_app


def write_registry(path: Path) -> None:
    path.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/usr/bin/printf", "%s", "{{message}}"]
cwd_mode = "optional"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )


def test_api_lists_agents(tmp_path: Path) -> None:
    registry = tmp_path / "agents.toml"
    write_registry(registry)
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    response = client.get("/agents")

    assert response.status_code == 200
    assert response.json()["agents"][0]["id"] == "shell"


def test_api_runs_session_and_reads_logs(tmp_path: Path) -> None:
    registry = tmp_path / "agents.toml"
    write_registry(registry)
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    run = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"})
    assert run.status_code == 200
    session_id = run.json()["id"]

    logs = client.get(f"/sessions/{session_id}/logs")
    assert logs.status_code == 200
    assert logs.json()["entries"][0]["line"] == "OK"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_api.py -q
```

Expected: FAIL with missing `agentic_os.api`.

- [ ] **Step 3: Implement FastAPI app**

Create `src/agentic_os/api.py`:

```python
from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from agentic_os.logs import JsonlLogStore, StreamName
from agentic_os.registry import Registry
from agentic_os.storage import Store
from agentic_os.supervisor import ProcessSupervisor


class SessionRunRequest(BaseModel):
    agent_id: str
    cwd: str | None = None
    message: str


def create_app(state_dir: Path, registry_path: Path) -> FastAPI:
    state_dir.mkdir(parents=True, exist_ok=True)
    registry = Registry(registry_path)
    store = Store(state_dir / "agentic-os.db")
    store.init()
    logs = JsonlLogStore()
    supervisor = ProcessSupervisor(store=store, logs=logs, state_dir=state_dir)
    supervisor.reconcile()

    app = FastAPI(title="agentic-os")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/agents")
    def list_agents() -> dict[str, object]:
        return {"agents": [agent.model_dump() for agent in registry.list_agents()]}

    @app.get("/agents/{agent_id}")
    def show_agent(agent_id: str) -> dict[str, object]:
        try:
            return registry.get(agent_id).model_dump()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions")
    def run_session(request: SessionRunRequest) -> dict[str, object]:
        try:
            rendered = registry.build_run(request.agent_id, request.cwd, request.message)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session = supervisor.start(rendered.agent.id, rendered.cwd, rendered.argv)
        _wait_for_short_command(supervisor, session.id)
        return supervisor.store.get_session(session.id).model_dump()

    @app.get("/sessions")
    def list_sessions() -> dict[str, object]:
        return {"sessions": [session.model_dump() for session in store.list_sessions()]}

    @app.get("/sessions/{session_id}")
    def show_session(session_id: str) -> dict[str, object]:
        try:
            return store.get_session(session_id).model_dump()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/logs")
    def session_logs(
        session_id: str,
        stream: StreamName | None = None,
        after: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        try:
            session = store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        entries = logs.read_merged(
            Path(session.stdout_log),
            Path(session.stderr_log),
            stream=stream,
            after=after,
        )
        return {"entries": [entry.model_dump() for entry in entries]}

    @app.post("/sessions/{session_id}/stop")
    def stop_session(session_id: str) -> dict[str, object]:
        try:
            return supervisor.stop(session_id).model_dump()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/retry")
    def retry_session(session_id: str) -> dict[str, object]:
        try:
            return supervisor.retry(session_id).model_dump()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


def _wait_for_short_command(supervisor: ProcessSupervisor, session_id: str) -> None:
    for _ in range(20):
        session = supervisor.store.get_session(session_id)
        if session.status.value in {"succeeded", "failed", "stopped"}:
            return
        time.sleep(0.025)
```

- [ ] **Step 4: Run API tests**

Run:

```bash
uv run pytest tests/test_api.py -q
```

Expected: PASS, `2 passed`.

- [ ] **Step 5: Commit API**

Run:

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat: expose daemon api"
```

Expected: commit succeeds.

## Task 7: Daemon Entrypoint

**Files:**
- Create: `src/agentic_os/daemon.py`
- Create: `tests/test_daemon.py`

- [ ] **Step 1: Write failing daemon test**

Create `tests/test_daemon.py`:

```python
from typer.testing import CliRunner

from agentic_os.daemon import app


def test_agentd_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "serve" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_daemon.py -q
```

Expected: FAIL with missing `agentic_os.daemon`.

- [ ] **Step 3: Implement daemon CLI**

Create `src/agentic_os/daemon.py`:

```python
from __future__ import annotations

from pathlib import Path

import typer
import uvicorn

from agentic_os.api import create_app


app = typer.Typer(help="Run the agentic-os daemon.")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8767, help="Bind port."),
    state_dir: Path = typer.Option(Path(".agentic-os"), help="Runtime state directory."),
    registry: Path = typer.Option(Path("examples/agents.toml"), help="Harness Instance Registry TOML."),
) -> None:
    api = create_app(state_dir=state_dir, registry_path=registry)
    uvicorn.run(api, host=host, port=port)
```

- [ ] **Step 4: Run daemon test**

Run:

```bash
uv run pytest tests/test_daemon.py -q
```

Expected: PASS, `1 passed`.

- [ ] **Step 5: Commit daemon entrypoint**

Run:

```bash
git add src/agentic_os/daemon.py tests/test_daemon.py
git commit -m "feat: add agentd serve command"
```

Expected: commit succeeds.

## Task 8: HTTP Client And Typer CLI

**Files:**
- Create: `src/agentic_os/client.py`
- Create: `src/agentic_os/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from agentic_os import cli


class FakeClient:
    def list_agents(self):
        return {"agents": [{"id": "shell", "label": "Shell", "enabled": True}]}

    def run_session(self, agent_id: str, cwd: str | None, message: str):
        return {"id": "s_1", "agent_id": agent_id, "cwd": cwd, "status": "succeeded"}

    def list_sessions(self):
        return {"sessions": [{"id": "s_1", "agent_id": "shell", "status": "succeeded"}]}

    def get_logs(self, session_id: str, stream=None, after: int = 0):
        return {"entries": [{"stream": "stdout", "line": "OK", "index": 1}]}

    def stop_session(self, session_id: str):
        return {"id": session_id, "status": "stopped"}


def test_agents_list(monkeypatch) -> None:
    monkeypatch.setattr(cli, "make_client", lambda api: FakeClient())
    result = CliRunner().invoke(cli.app, ["agents", "list"])

    assert result.exit_code == 0
    assert "shell" in result.output


def test_run_prints_session_id(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "make_client", lambda api: FakeClient())
    result = CliRunner().invoke(
        cli.app,
        ["run", "shell", "--cwd", str(tmp_path), "--message", "OK"],
    )

    assert result.exit_code == 0
    assert "s_1" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_cli.py -q
```

Expected: FAIL with missing `agentic_os.cli`.

- [ ] **Step 3: Implement HTTP client**

Create `src/agentic_os/client.py`:

```python
from __future__ import annotations

import httpx


class AgenticClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def list_agents(self) -> dict:
        return self._get("/agents")

    def show_agent(self, agent_id: str) -> dict:
        return self._get(f"/agents/{agent_id}")

    def run_session(self, agent_id: str, cwd: str | None, message: str) -> dict:
        return self._post("/sessions", {"agent_id": agent_id, "cwd": cwd, "message": message})

    def list_sessions(self) -> dict:
        return self._get("/sessions")

    def show_session(self, session_id: str) -> dict:
        return self._get(f"/sessions/{session_id}")

    def get_logs(self, session_id: str, stream: str | None = None, after: int = 0) -> dict:
        params = {"after": after}
        if stream:
            params["stream"] = stream
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            response = client.get(f"/sessions/{session_id}/logs", params=params)
            response.raise_for_status()
            return response.json()

    def stop_session(self, session_id: str) -> dict:
        return self._post(f"/sessions/{session_id}/stop", {})

    def retry_session(self, session_id: str) -> dict:
        return self._post(f"/sessions/{session_id}/retry", {})

    def _get(self, path: str) -> dict:
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            response = client.get(path)
            response.raise_for_status()
            return response.json()

    def _post(self, path: str, payload: dict) -> dict:
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            response = client.post(path, json=payload)
            response.raise_for_status()
            return response.json()
```

- [ ] **Step 4: Implement Typer CLI**

Create `src/agentic_os/cli.py`:

```python
from __future__ import annotations

import os
import time
from pathlib import Path

import typer

from agentic_os.client import AgenticClient


app = typer.Typer(help="Control local agentic-os sessions.")
agents_app = typer.Typer(help="Inspect configured agents.")
sessions_app = typer.Typer(help="Inspect sessions.")
app.add_typer(agents_app, name="agents")
app.add_typer(sessions_app, name="sessions")


def make_client(api: str | None) -> AgenticClient:
    return AgenticClient(api or os.environ.get("AGENTIC_OS_API", "http://127.0.0.1:8767"))


@agents_app.command("list")
def agents_list(api: str | None = typer.Option(None, help="Daemon API URL.")) -> None:
    data = make_client(api).list_agents()
    for agent in data["agents"]:
        enabled = "enabled" if agent.get("enabled", True) else "disabled"
        typer.echo(f"{agent['id']}\t{agent['label']}\t{enabled}")


@agents_app.command("show")
def agents_show(agent_id: str, api: str | None = typer.Option(None, help="Daemon API URL.")) -> None:
    typer.echo(make_client(api).show_agent(agent_id))


@app.command()
def run(
    agent_id: str,
    cwd: Path | None = typer.Option(None, help="Working directory."),
    message: str = typer.Option(..., help="Message passed to the agent command template."),
    api: str | None = typer.Option(None, help="Daemon API URL."),
) -> None:
    data = make_client(api).run_session(
        agent_id=agent_id,
        cwd=str(cwd.expanduser().resolve()) if cwd else None,
        message=message,
    )
    typer.echo(f"{data['id']}\t{data['agent_id']}\t{data['status']}")


@sessions_app.command("list")
def sessions_list(api: str | None = typer.Option(None, help="Daemon API URL.")) -> None:
    data = make_client(api).list_sessions()
    for session in data["sessions"]:
        typer.echo(f"{session['id']}\t{session['agent_id']}\t{session['status']}")


@sessions_app.command("show")
def sessions_show(
    session_id: str,
    api: str | None = typer.Option(None, help="Daemon API URL."),
) -> None:
    typer.echo(make_client(api).show_session(session_id))


@app.command()
def logs(
    session_id: str,
    stream: str | None = typer.Option(None, help="stdout or stderr."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Poll for new log lines."),
    api: str | None = typer.Option(None, help="Daemon API URL."),
) -> None:
    client = make_client(api)
    after = 0
    while True:
        data = client.get_logs(session_id, stream=stream, after=after)
        entries = data["entries"]
        for entry in entries:
            typer.echo(f"{entry['stream']}\t{entry['line']}")
            after = max(after, entry["index"])
        if not follow:
            return
        time.sleep(1)


@app.command()
def stop(session_id: str, api: str | None = typer.Option(None, help="Daemon API URL.")) -> None:
    data = make_client(api).stop_session(session_id)
    typer.echo(f"{data['id']}\t{data['status']}")


@app.command()
def retry(session_id: str, api: str | None = typer.Option(None, help="Daemon API URL.")) -> None:
    data = make_client(api).retry_session(session_id)
    typer.echo(f"{data['id']}\t{data['agent_id']}\t{data['status']}")
```

- [ ] **Step 5: Run CLI tests**

Run:

```bash
uv run pytest tests/test_cli.py -q
```

Expected: PASS, `2 passed`.

- [ ] **Step 6: Commit CLI**

Run:

```bash
git add src/agentic_os/client.py src/agentic_os/cli.py tests/test_cli.py
git commit -m "feat: add agentctl cli"
```

Expected: commit succeeds.

## Task 9: End-To-End Smoke And Documentation

**Files:**
- Modify: `README.md`
- Create: `tests/test_end_to_end.py`

- [ ] **Step 1: Write failing end-to-end test**

Create `tests/test_end_to_end.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from agentic_os.api import create_app


def test_e2e_shell_run_session_logs_and_retry(tmp_path: Path) -> None:
    registry = tmp_path / "agents.toml"
    registry.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/usr/bin/printf", "%s", "{{message}}"]
cwd_mode = "optional"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    first = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"})
    first_id = first.json()["id"]
    assert first.json()["status"] == "succeeded"

    logs = client.get(f"/sessions/{first_id}/logs")
    assert logs.json()["entries"][0]["line"] == "OK"

    retry = client.post(f"/sessions/{first_id}/retry")
    assert retry.status_code == 200
    assert retry.json()["id"] != first_id
```

- [ ] **Step 2: Run full tests**

Run:

```bash
uv run pytest -q
```

Expected: PASS. If the end-to-end test fails because fast commands finish after the first API response, increase `_wait_for_short_command` polling in `src/agentic_os/api.py` from 20 iterations to 80 iterations.

- [ ] **Step 3: Update README with P0 usage**

Replace the development section in `README.md` with:

````markdown
## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
```

## Run P0 Locally

Start the daemon:

```bash
uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

In another terminal:

```bash
uv run agentctl agents list
uv run agentctl run shell --cwd "$PWD" --message "OK"
uv run agentctl sessions list
uv run agentctl logs <session_id>
uv run agentctl retry <session_id>
uv run agentctl stop <session_id>
```

Real agent smoke examples:

```bash
uv run agentctl run openclaw --cwd "$PWD" --message "只輸出 OK"
uv run agentctl run hermes --cwd "$PWD" --message "只輸出 OK"
```
````

- [ ] **Step 4: Run quality gates**

Run:

```bash
uv run pytest -q
uv run ruff check .
```

Expected: pytest PASS and ruff `All checks passed!`.

- [ ] **Step 5: Manual smoke**

Run:

```bash
uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

In another terminal:

```bash
uv run agentctl agents list
uv run agentctl run shell --cwd "$PWD" --message "OK"
uv run agentctl sessions list
uv run agentctl logs <session_id>
```

Expected:

```text
shell	Shell Smoke	enabled
s_<id>	shell	succeeded
stdout	OK
```

- [ ] **Step 6: Commit end-to-end docs**

Run:

```bash
git add README.md tests/test_end_to_end.py
git commit -m "docs: document p0 runtime smoke"
```

Expected: commit succeeds.

## Task 10: Real Agent Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Verify OpenClaw or Hermes executable is present**

Run:

```bash
command -v openclaw || command -v hermes
```

Expected: prints at least one executable path.

- [ ] **Step 2: Start daemon against example registry**

Run:

```bash
uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Expected: Uvicorn listens on `http://127.0.0.1:8767`.

- [ ] **Step 3: Run one real agent command**

If OpenClaw exists:

```bash
uv run agentctl run openclaw --cwd "$PWD" --message "只輸出 OK"
```

If Hermes exists:

```bash
uv run agentctl run hermes --cwd "$PWD" --message "只輸出 OK"
```

Expected: command prints `s_<id>` and a terminal status. `succeeded` is ideal; `failed` is acceptable only if logs show an upstream agent/runtime error rather than an `agentic-os` launch bug.

- [ ] **Step 4: Inspect logs**

Run:

```bash
uv run agentctl logs <session_id>
```

Expected: logs show raw stdout/stderr from the real agent command.

- [ ] **Step 5: Record verification in README**

Append a short note under `## Run P0 Locally`:

```markdown
## P0 Verification Notes

The required local smoke is `shell`. Real agent smoke should be run with OpenClaw or Hermes when those CLIs are available on the machine. If a real agent fails because its own gateway/auth/model is unavailable, keep the session and logs as proof that `agentic-os` captured the failure correctly.
```

- [ ] **Step 6: Commit verification note**

Run:

```bash
git add README.md
git commit -m "docs: add real agent verification notes"
```

Expected: commit succeeds.

## Self-Review

Spec coverage:

- Harness Instance Registry: Task 3.
- Start local Harness Run: Tasks 5, 6, 8, 9.
- Session metadata: Task 2.
- Append-only stdout/stderr logs: Task 4.
- Stop process group: Task 5.
- Artifact folder: Task 5.
- CLI before UI: Tasks 7 and 8.
- Retry: Tasks 6, 8, 9.
- Daemon restart reconciliation: Task 5.
- Failure handling: Tasks 2, 5, 6.
- Verification: Tasks 9 and 10.

Completeness scan:

- The plan contains no empty-work markers or deferred-fill sections.
- Every task names files, commands, expected results, and commit messages.

Type consistency:

- Session statuses match `SessionStatus`.
- CLI routes match API routes.
- Registry command rendering feeds supervisor argv unchanged.
- Logs use `stdout` and `stderr` stream names throughout.
