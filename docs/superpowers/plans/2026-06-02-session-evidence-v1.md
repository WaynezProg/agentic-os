# Session Evidence v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every `agentic-os` Harness Run produce a standard evidence bundle with `metadata.json`, `events.jsonl`, and `artifacts/manifest.json`, while keeping formal memory ownership outside `agentic-os`.

**Architecture:** Add a focused `EvidenceStore` that owns evidence files under each existing session directory and is called by the supervisor, API, and CLI. Keep stdout/stderr JSONL and SQLite session/event storage compatible; evidence files are additive and repairable. Update docs and light UI copy so existing memory routes are described as summary/review pointers rather than the canonical memory system.

**Tech Stack:** Python 3.12, FastAPI, Typer, Pydantic, SQLite-backed session metadata, JSON/JSONL files, pytest, Ruff.

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `src/agentic_os/evidence.py` | New evidence models, file paths, metadata writer, event JSONL writer/reader, artifact manifest helper, git working-tree snapshot. |
| `src/agentic_os/supervisor.py` | Call `EvidenceStore` during run accepted, launch started/failed, process started/exited, stop, upstream session discovery, usage reported. |
| `src/agentic_os/api.py` | Add `/sessions/{session_id}/evidence` and `/sessions/{session_id}/evidence/events`; keep memory routes but tag summary/review pointer responses. |
| `src/agentic_os/client.py` | Add client methods for evidence endpoints. |
| `src/agentic_os/cli.py` | Add `agentctl sessions evidence` and `agentctl sessions evidence-events`. |
| `tests/test_evidence.py` | Unit tests for evidence file creation, metadata, events, malformed JSONL tolerance, artifact manifest. |
| `tests/test_supervisor.py` | Supervisor lifecycle evidence regressions. |
| `tests/test_api.py` | Evidence API and memory-boundary response tests. |
| `tests/test_cli.py` | Client and CLI command tests. |
| `README.md` | Reposition memory language: agentic-os owns evidence; session2memory owns durable memory. |
| `specs/002-session-memory-pipeline.md` | Mark as compatibility summary/review pointer surface superseded by Session Evidence v1 for evidence ownership. |
| `specs/003-thin-ui.md` | Relabel UI memory surface as summary/review pointer, not canonical memory. |
| `apps/web/index.html` | Minimal copy-only label change from canonical memory wording to evidence summary/review pointer wording. |
| `tests/test_web.py` | Contract tests for the copy/API surface update. |

## Scope Notes

- Do not change `SessionRecord` schema in this slice.
- Do not remove existing `/memory*` routes or SQLite memory tables.
- Do not parse private harness internals.
- Do not add a UI evidence tab in this slice.
- Do not push or merge until full gates pass and review is complete.

---

### Task 1: Evidence Store Core

**Files:**
- Create: `src/agentic_os/evidence.py`
- Create: `tests/test_evidence.py`

- [ ] **Step 1: Write failing evidence unit tests**

Create `tests/test_evidence.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentic_os.evidence import EvidenceStore
from agentic_os.models import SessionCreate
from agentic_os.storage import Store


def make_session(tmp_path: Path, *, agent_id: str = "codex"):
    store = Store(tmp_path / "agentic-os.db")
    store.init()
    session_dir = tmp_path / "sessions" / "s_manual"
    return store.create_session(
        SessionCreate(
            agent_id=agent_id,
            cwd=str(tmp_path),
            argv=["/bin/sh", "-lc", "printf OK"],
            env={"SECRET_TOKEN": "hidden", "VISIBLE_NAME": "shown"},
            artifact_dir=str(session_dir / "artifacts"),
            stdout_log=str(session_dir / "stdout.jsonl"),
            stderr_log=str(session_dir / "stderr.jsonl"),
            resolved_profile="default",
            resolved_provider="openai",
            resolved_model="gpt-5",
        )
    )


def test_evidence_store_creates_base_bundle(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    evidence = EvidenceStore(state_dir=tmp_path)

    paths = evidence.ensure_bundle(session)

    assert paths.metadata.exists()
    assert paths.events.exists()
    assert paths.artifact_manifest.exists()
    assert Path(session.artifact_dir).exists()
    manifest = json.loads(paths.artifact_manifest.read_text(encoding="utf-8"))
    assert manifest == {
        "schema_version": "artifact_manifest.v1",
        "session_id": session.id,
        "artifacts": [],
    }


def test_evidence_metadata_redacts_env_values_and_records_paths(tmp_path: Path) -> None:
    session = make_session(tmp_path, agent_id="codex")
    evidence = EvidenceStore(state_dir=tmp_path)

    payload = evidence.write_metadata(session)

    assert payload["schema_version"] == "session_evidence.v1"
    assert payload["session_id"] == session.id
    assert payload["harness_id"] == "codex"
    assert payload["adapter_contract_version"] == "v2"
    assert payload["required_env"] == ["SECRET_TOKEN", "VISIBLE_NAME"]
    assert "hidden" not in json.dumps(payload)
    assert payload["resolved_profile"] == "default"
    assert payload["resolved_provider"] == "openai"
    assert payload["resolved_model"] == "gpt-5"
    assert payload["evidence_paths"]["events"].endswith("/events.jsonl")
    assert payload["evidence_paths"]["artifact_manifest"].endswith("/artifacts/manifest.json")


def test_evidence_metadata_uses_v1_for_non_semantic_harness(tmp_path: Path) -> None:
    session = make_session(tmp_path, agent_id="shell")
    evidence = EvidenceStore(state_dir=tmp_path)

    payload = evidence.write_metadata(session)

    assert payload["adapter_contract_version"] == "v1"


def test_evidence_events_append_and_read_with_truncation(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    evidence = EvidenceStore(state_dir=tmp_path)

    evidence.append_event(session, "run_accepted", "run accepted", {"argv": session.argv})
    evidence.append_event(session, "process_started", "process started", {"pid": 123})
    result = evidence.read_events(session, max_lines=1)

    assert result.truncated is True
    assert len(result.events) == 1
    assert result.events[0].event_type == "run_accepted"
    assert result.events[0].severity == "info"
    assert result.events[0].metadata == {"argv": session.argv}
    assert result.events[0].index == 1


def test_evidence_event_reader_skips_malformed_jsonl(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    evidence = EvidenceStore(state_dir=tmp_path)
    paths = evidence.ensure_bundle(session)
    paths.events.write_text(
        "not-json\n"
        + json.dumps(
            {
                "ts": "2026-06-02T00:00:00+00:00",
                "session_id": session.id,
                "harness_id": session.agent_id,
                "event_type": "process_exited",
                "severity": "info",
                "message": "process exited",
                "metadata": {"exit_code": 0},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = evidence.read_events(session)

    assert result.truncated is False
    assert [event.event_type for event in result.events] == ["process_exited"]
    assert result.events[0].index == 2


def test_evidence_records_artifact_manifest_entry(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    evidence = EvidenceStore(state_dir=tmp_path)
    artifact_path = Path(session.artifact_dir) / "report.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text('{"ok": true}', encoding="utf-8")

    entry = evidence.record_artifact(
        session,
        artifact_path,
        kind="json",
        media_type="application/json",
        source_event_type="artifact_recorded",
    )

    manifest = json.loads((Path(session.artifact_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert entry["id"] == "art_001"
    assert entry["path"].endswith("/artifacts/report.json")
    assert entry["sha256"]
    assert manifest["artifacts"] == [entry]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
rtk uv run pytest tests/test_evidence.py -q
```

Expected: failure importing `agentic_os.evidence`.

- [ ] **Step 3: Implement `src/agentic_os/evidence.py`**

Create `src/agentic_os/evidence.py`:

```python
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from agentic_os.adapter_contract import SEMANTIC_HARNESS_IDS
from agentic_os.control_plane import _redact_value
from agentic_os.models import SessionRecord


EvidenceSeverity = Literal["debug", "info", "warning", "error"]


class EvidenceEvent(BaseModel):
    ts: str
    session_id: str
    harness_id: str
    event_type: str
    severity: EvidenceSeverity
    message: str
    metadata: dict[str, Any]
    index: int


@dataclass(frozen=True)
class EvidenceReadResult:
    events: list[EvidenceEvent]
    truncated: bool


@dataclass(frozen=True)
class EvidencePaths:
    session_dir: Path
    metadata: Path
    events: Path
    stdout: Path
    stderr: Path
    artifact_dir: Path
    artifact_manifest: Path


class EvidenceStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir

    def paths_for_session(self, session: SessionRecord) -> EvidencePaths:
        session_dir = Path(session.stdout_log).parent
        artifact_dir = Path(session.artifact_dir)
        return EvidencePaths(
            session_dir=session_dir,
            metadata=session_dir / "metadata.json",
            events=session_dir / "events.jsonl",
            stdout=Path(session.stdout_log),
            stderr=Path(session.stderr_log),
            artifact_dir=artifact_dir,
            artifact_manifest=artifact_dir / "manifest.json",
        )

    def ensure_bundle(self, session: SessionRecord) -> EvidencePaths:
        paths = self.paths_for_session(session)
        paths.session_dir.mkdir(parents=True, exist_ok=True)
        paths.artifact_dir.mkdir(parents=True, exist_ok=True)
        paths.stdout.touch(exist_ok=True)
        paths.stderr.touch(exist_ok=True)
        paths.events.touch(exist_ok=True)
        if not paths.artifact_manifest.exists():
            self._write_json(
                paths.artifact_manifest,
                {
                    "schema_version": "artifact_manifest.v1",
                    "session_id": session.id,
                    "artifacts": [],
                },
            )
        if not paths.metadata.exists():
            self.write_metadata(session)
        return paths

    def write_metadata(self, session: SessionRecord) -> dict[str, Any]:
        paths = self.ensure_bundle_without_metadata(session)
        payload: dict[str, Any] = {
            "schema_version": "session_evidence.v1",
            "session_id": session.id,
            "harness_id": session.agent_id,
            "status": session.status.value,
            "cwd": session.cwd,
            "argv": list(session.argv),
            "required_env": sorted(session.env.keys()),
            "pid": session.pid,
            "pgid": session.pgid,
            "exit_code": session.exit_code,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "updated_at": session.updated_at,
            "upstream_session_id": session.external_session_id,
            "resolved_profile": session.resolved_profile,
            "resolved_provider": session.resolved_provider,
            "resolved_model": session.resolved_model,
            "adapter_contract_version": "v2"
            if session.agent_id in SEMANTIC_HARNESS_IDS
            else "v1",
            "working_tree": _working_tree_snapshot(Path(session.cwd)),
            "evidence_paths": self.path_payload(paths),
        }
        self._write_json(paths.metadata, payload)
        return payload

    def ensure_bundle_without_metadata(self, session: SessionRecord) -> EvidencePaths:
        paths = self.paths_for_session(session)
        paths.session_dir.mkdir(parents=True, exist_ok=True)
        paths.artifact_dir.mkdir(parents=True, exist_ok=True)
        paths.stdout.touch(exist_ok=True)
        paths.stderr.touch(exist_ok=True)
        paths.events.touch(exist_ok=True)
        if not paths.artifact_manifest.exists():
            self._write_json(
                paths.artifact_manifest,
                {
                    "schema_version": "artifact_manifest.v1",
                    "session_id": session.id,
                    "artifacts": [],
                },
            )
        return paths

    def append_event(
        self,
        session: SessionRecord,
        event_type: str,
        message: str,
        metadata: dict[str, Any] | None = None,
        *,
        severity: EvidenceSeverity = "info",
    ) -> dict[str, Any]:
        paths = self.ensure_bundle(session)
        payload = {
            "ts": _utc_now(),
            "session_id": session.id,
            "harness_id": session.agent_id,
            "event_type": event_type,
            "severity": severity,
            "message": message,
            "metadata": _redact_metadata(metadata or {}),
        }
        with paths.events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return payload

    def read_events(
        self,
        session: SessionRecord,
        *,
        after: int = 0,
        max_lines: int = 5000,
    ) -> EvidenceReadResult:
        paths = self.ensure_bundle(session)
        events: list[EvidenceEvent] = []
        truncated = False
        with paths.events.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                if index <= after:
                    continue
                if len(events) >= max_lines:
                    truncated = True
                    break
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict):
                    continue
                event = _event_from_raw(raw, index)
                if event is not None:
                    events.append(event)
        return EvidenceReadResult(events=events, truncated=truncated)

    def evidence_index(self, session: SessionRecord) -> dict[str, Any]:
        paths = self.ensure_bundle(session)
        if not paths.metadata.exists():
            metadata = self.write_metadata(session)
        else:
            metadata = json.loads(paths.metadata.read_text(encoding="utf-8"))
        return {
            "session_id": session.id,
            "harness_id": session.agent_id,
            "metadata": metadata,
            "paths": self.path_payload(paths),
        }

    def path_payload(self, paths: EvidencePaths) -> dict[str, str]:
        return {
            "metadata": self._display_path(paths.metadata),
            "events": self._display_path(paths.events),
            "stdout": self._display_path(paths.stdout),
            "stderr": self._display_path(paths.stderr),
            "artifact_manifest": self._display_path(paths.artifact_manifest),
            "artifact_dir": self._display_path(paths.artifact_dir),
        }

    def record_artifact(
        self,
        session: SessionRecord,
        path: Path,
        *,
        kind: str,
        media_type: str,
        source_event_type: str,
    ) -> dict[str, Any]:
        paths = self.ensure_bundle(session)
        manifest = json.loads(paths.artifact_manifest.read_text(encoding="utf-8"))
        artifacts = list(manifest.get("artifacts", []))
        entry = {
            "id": f"art_{len(artifacts) + 1:03d}",
            "path": self._display_path(path),
            "kind": kind,
            "media_type": media_type,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "source_event_type": source_event_type,
            "created_at": _utc_now(),
        }
        artifacts.append(entry)
        manifest = {
            "schema_version": "artifact_manifest.v1",
            "session_id": session.id,
            "artifacts": artifacts,
        }
        self._write_json(paths.artifact_manifest, manifest)
        self.append_event(
            session,
            "artifact_recorded",
            f"artifact recorded: {path.name}",
            {"artifact_id": entry["id"], "path": entry["path"], "kind": kind},
        )
        return entry

    def _display_path(self, path: Path) -> str:
        resolved = path.resolve()
        for root in (Path.cwd().resolve(), self.state_dir.resolve()):
            try:
                return str(resolved.relative_to(root))
            except ValueError:
                continue
        return str(resolved)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)


def _event_from_raw(raw: dict[str, Any], index: int) -> EvidenceEvent | None:
    required = ("ts", "session_id", "harness_id", "event_type", "severity", "message", "metadata")
    if any(key not in raw for key in required):
        return None
    if raw["severity"] not in {"debug", "info", "warning", "error"}:
        return None
    if not isinstance(raw["metadata"], dict):
        return None
    try:
        return EvidenceEvent(
            ts=str(raw["ts"]),
            session_id=str(raw["session_id"]),
            harness_id=str(raw["harness_id"]),
            event_type=str(raw["event_type"]),
            severity=raw["severity"],
            message=str(raw["message"]),
            metadata=raw["metadata"],
            index=index,
        )
    except ValueError:
        return None


def _redact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, dict):
            redacted[key] = _redact_metadata(value)
        elif isinstance(value, list):
            redacted[key] = [_redact_sequence_value(key, item) for item in value]
        else:
            redacted[key] = _redact_value(value, key)
    return redacted


def _redact_sequence_value(key: str, value: Any) -> Any:
    if isinstance(value, dict):
        return _redact_metadata(value)
    return _redact_value(value, key)


def _working_tree_snapshot(cwd: Path) -> dict[str, Any]:
    if not cwd.exists() or not cwd.is_dir():
        return {"available": False, "reason": "cwd is not a directory"}
    try:
        branch = _git(cwd, "branch", "--show-current")
        head = _git(cwd, "rev-parse", "HEAD")
        status = _git(cwd, "status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return {"available": False, "reason": "git inspection failed"}
    lines = [line for line in status.splitlines() if line.strip()]
    modified = sum(1 for line in lines if not line.startswith("??"))
    untracked = sum(1 for line in lines if line.startswith("??"))
    return {
        "available": True,
        "branch": branch,
        "head": head,
        "dirty": bool(lines),
        "status_summary": {"modified": modified, "untracked": untracked},
    }


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Run unit tests and verify GREEN**

Run:

```bash
rtk uv run pytest tests/test_evidence.py -q
```

Expected: `6 passed`.

- [ ] **Step 5: Run formatting/lint for new module**

Run:

```bash
rtk uv run ruff check src/agentic_os/evidence.py tests/test_evidence.py
rtk uv run ruff format --check src/agentic_os/evidence.py tests/test_evidence.py
```

Expected: both pass.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add src/agentic_os/evidence.py tests/test_evidence.py
git commit -m "feat: add session evidence store"
```

---

### Task 2: Supervisor Lifecycle Evidence

**Files:**
- Modify: `src/agentic_os/supervisor.py`
- Test: `tests/test_supervisor.py`

- [ ] **Step 1: Write failing supervisor evidence tests**

Append these tests to `tests/test_supervisor.py`:

```python
def read_evidence_events(session: SessionRecord) -> list[dict[str, object]]:
    events_path = Path(session.stdout_log).parent / "events.jsonl"
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_evidence_metadata(session: SessionRecord) -> dict[str, object]:
    metadata_path = Path(session.stdout_log).parent / "metadata.json"
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def test_supervisor_writes_evidence_bundle_for_successful_run(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start(
        agent_id="codex",
        cwd=str(tmp_path),
        argv=["/bin/sh", "-lc", "printf OK"],
        env={"SECRET_TOKEN": "hidden"},
        resolved_profile="default",
        resolved_provider="openai",
        resolved_model="gpt-5",
    )
    wait_until_done(supervisor, session.id)

    finished = supervisor.store.get_session(session.id)
    session_dir = Path(finished.stdout_log).parent
    metadata = read_evidence_metadata(finished)
    event_types = [event["event_type"] for event in read_evidence_events(finished)]

    assert (session_dir / "metadata.json").exists()
    assert (session_dir / "events.jsonl").exists()
    assert (Path(finished.artifact_dir) / "manifest.json").exists()
    assert metadata["status"] == "succeeded"
    assert metadata["adapter_contract_version"] == "v2"
    assert metadata["required_env"] == ["SECRET_TOKEN"]
    assert "hidden" not in json.dumps(metadata)
    assert "run_accepted" in event_types
    assert "launch_started" in event_types
    assert "process_started" in event_types
    assert "process_exited" in event_types


def test_supervisor_writes_evidence_for_rejected_run(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start_rejected(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=["/bin/sh", "-lc", "printf rejected"],
        env={"TOKEN": "hidden"},
    )

    finished = supervisor.store.get_session(session.id)
    metadata = read_evidence_metadata(finished)
    event_types = [event["event_type"] for event in read_evidence_events(finished)]

    assert finished.status == SessionStatus.FAILED
    assert metadata["status"] == "failed"
    assert metadata["adapter_contract_version"] == "v1"
    assert "run_accepted" in event_types
    assert "launch_rejected" in event_types


def test_supervisor_writes_evidence_for_launch_failure(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start(agent_id="shell", cwd=str(tmp_path), argv=[])
    finished = supervisor.store.get_session(session.id)
    event_types = [event["event_type"] for event in read_evidence_events(finished)]
    metadata = read_evidence_metadata(finished)

    assert finished.status == SessionStatus.FAILED
    assert "launch_failed" in event_types
    assert metadata["status"] == "failed"


def test_supervisor_writes_evidence_for_stopped_run(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)
    ready_path = tmp_path / "child-ready"
    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=child_ignores_sigterm_argv(ready_path),
    )
    wait_until_file_exists(ready_path)
    running = supervisor.store.get_session(session.id)

    try:
        stopped = supervisor.stop(session.id, timeout_seconds=0.1)
        event_types = [event["event_type"] for event in read_evidence_events(stopped)]
        metadata = read_evidence_metadata(stopped)

        assert stopped.status == SessionStatus.STOPPED
        assert "run_stopping" in event_types
        assert "run_stopped" in event_types
        assert metadata["status"] == "stopped"
    finally:
        cleanup_process_group(running.pgid, running.pid)
```

- [ ] **Step 2: Run supervisor tests and verify RED**

Run:

```bash
rtk uv run pytest tests/test_supervisor.py -q
```

Expected: new evidence tests fail because `metadata.json`, `events.jsonl`, or `manifest.json` are not created by supervisor.

- [ ] **Step 3: Wire `EvidenceStore` into supervisor**

Modify `src/agentic_os/supervisor.py` imports:

```python
from agentic_os.evidence import EvidenceStore
```

Modify `ProcessSupervisor.__init__`:

```python
        self.usage_store = usage_store
        self.evidence = EvidenceStore(state_dir)
        self._processes: dict[str, subprocess.Popen[str]] = {}
```

Add helper methods inside `ProcessSupervisor` before `_cleanup_process_tracking`:

```python
    def _ensure_evidence(self, session: SessionRecord) -> None:
        try:
            self.evidence.ensure_bundle(session)
            self.evidence.write_metadata(session)
        except Exception as exc:  # noqa: BLE001
            self.store.record_event(
                session.id,
                "evidence_write_failed",
                str(exc),
                {"phase": "ensure_bundle"},
            )

    def _append_evidence_event(
        self,
        session: SessionRecord,
        event_type: str,
        message: str,
        metadata: dict[str, object] | None = None,
        *,
        severity: str = "info",
    ) -> None:
        try:
            self.evidence.append_event(
                session,
                event_type,
                message,
                metadata or {},
                severity=severity,  # type: ignore[arg-type]
            )
        except Exception as exc:  # noqa: BLE001
            self.store.record_event(
                session.id,
                "evidence_write_failed",
                str(exc),
                {"phase": event_type},
            )

    def _rewrite_evidence_metadata(self, session_id: str) -> None:
        try:
            self.evidence.write_metadata(self.store.get_session(session_id))
        except Exception as exc:  # noqa: BLE001
            self.store.record_event(
                session_id,
                "evidence_write_failed",
                str(exc),
                {"phase": "metadata"},
            )
```

Modify `start_rejected()` after `Path(session.stderr_log).touch()`:

```python
        self._ensure_evidence(session)
        self._append_evidence_event(
            session,
            "run_accepted",
            "run accepted",
            {"argv": argv, "cwd": cwd},
        )
        self._append_evidence_event(
            session,
            "launch_rejected",
            "launch rejected by policy",
            {"argv": argv, "cwd": cwd},
            severity="warning",
        )
        failed = self.store.mark_failed(session.id)
        self._rewrite_evidence_metadata(failed.id)
        return failed
```

Remove the existing final line in `start_rejected()`:

```python
        return self.store.mark_failed(session.id)
```

The new final lines are:

```python
        failed = self.store.mark_failed(session.id)
        self._rewrite_evidence_metadata(failed.id)
        return failed
```

Modify `start()` after stdout/stderr touches:

```python
        self._ensure_evidence(session)
        self._append_evidence_event(
            session,
            "run_accepted",
            "run accepted",
            {"argv": argv, "cwd": cwd},
        )
        self._append_evidence_event(
            session,
            "launch_started",
            "launch started",
            {"argv": argv, "cwd": cwd},
        )
```

Modify launch failure handling:

```python
        except (OSError, LaunchFailure) as exc:
            self.store.record_event(session.id, "launch_failed", str(exc), {"argv": argv})
            self._append_evidence_event(
                session,
                "launch_failed",
                str(exc),
                {"argv": argv},
                severity="error",
            )
            self.logs.append(Path(session.stderr_log), session.id, "stderr", str(exc))
            failed = self.store.mark_failed(session.id)
            self._rewrite_evidence_metadata(failed.id)
            return failed
```

Modify after `mark_running()`:

```python
        session = self.store.mark_running(session.id, pid=process.pid, pgid=pgid)
        self._append_evidence_event(
            session,
            "process_started",
            "process started",
            {"pid": process.pid, "pgid": pgid},
        )
        self._rewrite_evidence_metadata(session.id)
```

Modify `stop()` after `session = self.store.mark_stopping(session_id)`:

```python
            self._append_evidence_event(
                session,
                "run_stopping",
                "stop requested",
                {"pid": session.pid, "pgid": session.pgid},
                severity="warning",
            )
            self._rewrite_evidence_metadata(session.id)
```

Modify `_mark_stopped_once()`:

```python
    def _mark_stopped_once(self, session_id: str) -> SessionRecord:
        try:
            stopped = self.store.mark_stopped(session_id)
            self._append_evidence_event(
                stopped,
                "run_stopped",
                "run stopped",
                {"pid": stopped.pid, "pgid": stopped.pgid},
                severity="warning",
            )
            self._rewrite_evidence_metadata(stopped.id)
            return stopped
        except ValueError:
            current = self.store.get_session(session_id)
            if current.status == SessionStatus.STOPPED:
                return current
            raise
```

Modify `_waiter()` after terminal state handling and before `_cleanup_process_tracking(session_id)`:

```python
        terminal = self.store.get_session(session_id)
        if terminal.status in TERMINAL_STATUSES:
            self._append_evidence_event(
                terminal,
                "process_exited",
                "process exited",
                {"exit_code": terminal.exit_code, "status": terminal.status.value},
                severity="info" if terminal.status == SessionStatus.SUCCEEDED else "error",
            )
            self._rewrite_evidence_metadata(session_id)
```

Modify `_waiter()` around external session capture:

```python
        before_external_session_id = self.store.get_session(session_id).external_session_id
        capture_external_session_after_run(
            self.store,
            session_id,
            has_attach_command=has_attach_command,
        )
        after_capture = self.store.get_session(session_id)
        if (
            after_capture.external_session_id
            and after_capture.external_session_id != before_external_session_id
        ):
            self._append_evidence_event(
                after_capture,
                "upstream_session_discovered",
                "upstream session discovered",
                {"upstream_session_id": after_capture.external_session_id},
            )
            self._rewrite_evidence_metadata(session_id)
```

Change `_collect_usage_for_session()` signature and tail:

```python
    def _collect_usage_for_session(self, session_id: str) -> UsageRecord | None:
        if self.usage_store is None:
            return None
```

After `self.usage_store.upsert(usage)`:

```python
        self.usage_store.upsert(usage)
        return usage
```

Modify `_waiter()` usage collection:

```python
        try:
            usage = self._collect_usage_for_session(session_id)
            if usage is not None:
                session = self.store.get_session(session_id)
                self._append_evidence_event(
                    session,
                    "usage_reported",
                    "usage reported",
                    {
                        "provider": usage.provider,
                        "model": usage.model,
                        "total_tokens": usage.total_tokens,
                        "cost_usd": usage.cost_usd,
                        "source": usage.source,
                    },
                )
                self._rewrite_evidence_metadata(session_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to collect usage for %s: %s", session_id, exc)
```

- [ ] **Step 4: Run supervisor tests and verify GREEN**

Run:

```bash
rtk uv run pytest tests/test_supervisor.py -q
```

Expected: all supervisor tests pass.

- [ ] **Step 5: Run evidence unit tests again**

Run:

```bash
rtk uv run pytest tests/test_evidence.py -q
```

Expected: all evidence tests still pass.

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add src/agentic_os/supervisor.py tests/test_supervisor.py
git commit -m "feat: record session evidence lifecycle"
```

---

### Task 3: Evidence API and Client

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `src/agentic_os/client.py`
- Test: `tests/test_api.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing API tests**

Append to `tests/test_api.py` near existing session log tests:

```python
def test_session_evidence_endpoint_returns_metadata_and_paths(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "evidence"},
    )
    assert run.status_code == 200
    session_id = run.json()["id"]

    response = client.get(f"/sessions/{session_id}/evidence")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["harness_id"] == "shell"
    assert payload["metadata"]["schema_version"] == "session_evidence.v1"
    assert payload["metadata"]["status"] == "succeeded"
    assert payload["paths"]["events"].endswith("/events.jsonl")
    assert payload["paths"]["artifact_manifest"].endswith("/artifacts/manifest.json")


def test_session_evidence_events_endpoint_returns_normalized_events(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "events"},
    )
    assert run.status_code == 200
    session_id = run.json()["id"]

    response = client.get(f"/sessions/{session_id}/evidence/events")

    assert response.status_code == 200
    payload = response.json()
    event_types = [event["event_type"] for event in payload["events"]]
    assert payload["truncated"] is False
    assert "run_accepted" in event_types
    assert "process_started" in event_types
    assert "process_exited" in event_types
    assert all("index" in event for event in payload["events"])


def test_session_evidence_events_endpoint_supports_after_and_max_lines(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "events cursor"},
    )
    assert run.status_code == 200
    session_id = run.json()["id"]

    response = client.get(
        f"/sessions/{session_id}/evidence/events",
        params={"after": 0, "max_lines": 1},
    )

    assert response.status_code == 200
    assert len(response.json()["events"]) == 1
    assert response.json()["truncated"] is True


def test_session_evidence_endpoints_return_404_for_unknown_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    index_response = client.get("/sessions/missing/evidence")
    events_response = client.get("/sessions/missing/evidence/events")

    assert index_response.status_code == 404
    assert events_response.status_code == 404
```

- [ ] **Step 2: Write failing client tests**

Append to `tests/test_cli.py` near `test_client_get_session_events_builds_expected_request`:

```python
def test_client_get_session_evidence_builds_expected_request(monkeypatch: Any) -> None:
    RecordingHttpxClient.requests = []
    monkeypatch.setattr("agentic_os.client.httpx.Client", RecordingHttpxClient)

    client = AgenticClient("http://api.example/")
    assert client.get_session_evidence("s_1") == {"session_id": "s_1"}

    assert RecordingHttpxClient.requests == [
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/sessions/s_1/evidence",
            "params": None,
        }
    ]


def test_client_get_session_evidence_events_builds_expected_request(monkeypatch: Any) -> None:
    RecordingHttpxClient.requests = []
    monkeypatch.setattr("agentic_os.client.httpx.Client", RecordingHttpxClient)

    client = AgenticClient("http://api.example/")
    assert client.get_session_evidence_events("s_1", after=2, max_lines=3) == {"events": []}

    assert RecordingHttpxClient.requests == [
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/sessions/s_1/evidence/events",
            "params": {"after": 2, "max_lines": 3},
        }
    ]
```

- [ ] **Step 3: Run API/client tests and verify RED**

Run:

```bash
rtk uv run pytest tests/test_api.py -k 'session_evidence' -q
rtk uv run pytest tests/test_cli.py -k 'session_evidence' -q
```

Expected: API routes and client methods are missing.

- [ ] **Step 4: Implement API routes**

Modify `src/agentic_os/api.py` imports:

```python
from agentic_os.evidence import EvidenceStore
```

In `create_app()`, after `logs = JsonlLogStore()`:

```python
    evidence_store = EvidenceStore(state_dir)
```

Add routes after `session_events()` and before `session_timeline()`:

```python
    @app.get("/sessions/{session_id}/evidence")
    def session_evidence(session_id: str) -> dict[str, object]:
        try:
            session = store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return evidence_store.evidence_index(session)

    @app.get("/sessions/{session_id}/evidence/events")
    def session_evidence_events(
        session_id: str,
        after: int = Query(default=0, ge=0),
        max_lines: int = Query(default=5000, ge=1, le=50000),
    ) -> dict[str, object]:
        try:
            session = store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        result = evidence_store.read_events(session, after=after, max_lines=max_lines)
        return {
            "events": [event.model_dump(mode="json") for event in result.events],
            "truncated": result.truncated,
        }
```

- [ ] **Step 5: Implement client methods**

Modify `src/agentic_os/client.py` after `get_session_events()`:

```python
    def get_session_evidence(self, session_id: str) -> dict[str, Any]:
        return self._get(f"/sessions/{_validate_path_id(session_id)}/evidence")

    def get_session_evidence_events(
        self,
        session_id: str,
        after: int = 0,
        max_lines: int = 5000,
    ) -> dict[str, Any]:
        return self._get(
            f"/sessions/{_validate_path_id(session_id)}/evidence/events",
            params={"after": after, "max_lines": max_lines},
        )
```

- [ ] **Step 6: Run API/client tests and verify GREEN**

Run:

```bash
rtk uv run pytest tests/test_api.py -k 'session_evidence' -q
rtk uv run pytest tests/test_cli.py -k 'session_evidence' -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 3**

Run:

```bash
git add src/agentic_os/api.py src/agentic_os/client.py tests/test_api.py tests/test_cli.py
git commit -m "feat: expose session evidence api"
```

---

### Task 4: Evidence CLI Commands

**Files:**
- Modify: `src/agentic_os/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Extend `FakeClient` with evidence methods**

Modify `tests/test_cli.py` `FakeClient` after `get_session_events()`:

```python
    def get_session_evidence(self, session_id: str) -> dict[str, object]:
        self.calls.append(("get_session_evidence", (session_id,), {}))
        return {
            "session_id": session_id,
            "harness_id": "shell",
            "metadata": {"schema_version": "session_evidence.v1", "session_id": session_id},
            "paths": {
                "metadata": ".agentic-os/sessions/s_1/metadata.json",
                "events": ".agentic-os/sessions/s_1/events.jsonl",
            },
        }

    def get_session_evidence_events(
        self,
        session_id: str,
        after: int = 0,
        max_lines: int = 5000,
    ) -> dict[str, object]:
        self.calls.append(
            ("get_session_evidence_events", (session_id,), {"after": after, "max_lines": max_lines})
        )
        return {
            "events": [
                {
                    "ts": "2026-06-02T00:00:00+00:00",
                    "session_id": session_id,
                    "harness_id": "shell",
                    "event_type": "process_started",
                    "severity": "info",
                    "message": "process started",
                    "metadata": {"pid": 123},
                    "index": 1,
                }
            ],
            "truncated": False,
        }
```

- [ ] **Step 2: Write failing CLI tests**

Append near existing session command tests in `tests/test_cli.py`:

```python
def test_sessions_evidence_prints_json(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["sessions", "evidence", "s_1"])

    assert result.exit_code == 0
    assert '"schema_version": "session_evidence.v1"' in result.output
    assert '"events": ".agentic-os/sessions/s_1/events.jsonl"' in result.output
    assert fake.calls == [("get_session_evidence", ("s_1",), {})]


def test_sessions_evidence_events_prints_jsonl_by_default(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        cli.app,
        ["sessions", "evidence-events", "s_1", "--after", "2", "--max-lines", "3"],
    )

    assert result.exit_code == 0
    line = json.loads(result.output)
    assert line["event_type"] == "process_started"
    assert fake.calls == [
        ("get_session_evidence_events", ("s_1",), {"after": 2, "max_lines": 3})
    ]


def test_sessions_evidence_events_json_flag_prints_envelope(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["sessions", "evidence-events", "s_1", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["events"][0]["event_type"] == "process_started"
    assert payload["truncated"] is False
```

- [ ] **Step 3: Run CLI tests and verify RED**

Run:

```bash
rtk uv run pytest tests/test_cli.py -k 'sessions_evidence' -q
```

Expected: commands are missing.

- [ ] **Step 4: Implement CLI commands**

Modify `src/agentic_os/cli.py` after `sessions_events()`:

```python
@sessions.command("evidence")
def sessions_evidence(session_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).get_session_evidence(session_id))
    _echo_json(data)


@sessions.command("evidence-events")
def sessions_evidence_events(
    session_id: str,
    after: int = typer.Option(0, "--after", help="Skip events through this line index."),
    max_lines: int = typer.Option(5000, "--max-lines", help="Maximum events to read."),
    json_output: bool = typer.Option(False, "--json", help="Print API envelope JSON."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(
        lambda: make_client(api).get_session_evidence_events(
            session_id,
            after=after,
            max_lines=max_lines,
        )
    )
    if json_output:
        _echo_json(data)
        return
    for event in data.get("events", []):
        typer.echo(json.dumps(event, ensure_ascii=False, sort_keys=True))
```

- [ ] **Step 5: Run CLI tests and verify GREEN**

Run:

```bash
rtk uv run pytest tests/test_cli.py -k 'sessions_evidence or client_get_session_evidence' -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add src/agentic_os/cli.py tests/test_cli.py
git commit -m "feat: add session evidence cli"
```

---

### Task 5: Memory Boundary and Product Language

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `README.md`
- Modify: `specs/002-session-memory-pipeline.md`
- Modify: `specs/003-thin-ui.md`
- Modify: `apps/web/index.html`
- Test: `tests/test_api.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing API tests for pointer metadata**

Modify `tests/test_api.py::test_api_creates_and_reads_session_memory_summary` by adding these assertions after `stdout_lines` and `stderr_lines`:

```python
    assert created.json()["ownership"] == "summary_pointer"
    assert created.json()["formal_memory_owner"] == "session2memory"
```

Modify `tests/test_api.py::test_api_creates_memory_review_from_current_session_logs` by adding:

```python
    assert created.json()["ownership"] == "review_pointer"
    assert created.json()["formal_memory_owner"] == "session2memory"
```

- [ ] **Step 2: Write failing web/docs tests**

Append to `tests/test_web.py`:

```python
def test_memory_copy_identifies_summary_review_pointers() -> None:
    html = (ROOT / "apps" / "web" / "index.html").read_text(encoding="utf-8")

    assert "證據摘要" in html
    assert "review pointer" in html


def test_readme_positions_session2memory_as_formal_memory_owner() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "session2memory owns formal memory compilation" in readme
    assert "agentic-os owns harness-run evidence" in readme
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
rtk uv run pytest tests/test_api.py -k 'memory_summary or memory_review_from_current_session_logs' -q
rtk uv run pytest tests/test_web.py -k 'memory_copy_identifies or readme_positions' -q
```

Expected: missing ownership fields and copy.

- [ ] **Step 4: Add pointer ownership fields to memory route responses**

Modify `src/agentic_os/api.py` by adding this helper near `_asdict` helpers:

```python
def _with_memory_boundary(payload: dict[str, Any], ownership: str) -> dict[str, Any]:
    return {
        **payload,
        "ownership": ownership,
        "formal_memory_owner": "session2memory",
    }
```

Modify memory routes:

```python
    @app.post("/sessions/{session_id}/memory/summary")
    def create_session_memory_summary(session_id: str) -> dict[str, Any]:
        return _with_memory_boundary(_asdict(_build_and_store_summary(session_id)), "summary_pointer")

    @app.get("/sessions/{session_id}/memory/summary")
    def show_session_memory_summary(session_id: str) -> dict[str, Any]:
        _get_session_or_404(session_id)
        try:
            return _with_memory_boundary(_asdict(memory_store.get_summary(session_id)), "summary_pointer")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/memory/review")
    def create_session_memory_review(session_id: str) -> dict[str, Any]:
        summary = _get_or_create_summary(session_id)
        return _with_memory_boundary(_asdict(memory_store.create_review_item(summary)), "review_pointer")
```

Do not add these fields to `/memory`, `/memory/search`, approve, or reject in this slice; those remain compatibility endpoints and can be repositioned in docs.

- [ ] **Step 5: Update README language**

Edit `README.md` so the positioning section contains this exact paragraph near the phase table:

```markdown
Session Evidence v1 clarifies ownership: agentic-os owns harness-run evidence, evidence paths,
bounded logs, and summary/review pointers. session2memory owns formal memory compilation,
review-first durable suggestions, and downstream HKS ingestion. The compatibility `agentctl memory`
commands remain available, but new workflows must consume `metadata.json`, `events.jsonl`,
stdout/stderr JSONL, and `artifacts/manifest.json`.
```

Change the P1 phase table row from durable memory ownership to evidence pointer ownership:

```markdown
| P1 | deterministic session evidence and review pointers | auditable run evidence for downstream compilers | summaries, review pointers, evidence paths | durable memory compilation, embeddings, RAG |
```

- [ ] **Step 6: Update specs language**

Edit `specs/002-session-memory-pipeline.md` by adding this notice after the title block:

```markdown
> Superseded boundary note (2026-06-02): this spec remains the compatibility contract for
> deterministic summary/review pointer APIs. Formal durable memory compilation is owned by
> session2memory. New agentic-os work must use Session Evidence v1 as the source evidence
> contract.
```

Edit the pipeline diagram from:

```text
session logs -> session summary -> review queue -> approved memory -> searchable KB
```

to:

```text
session evidence -> summary/review pointer -> session2memory compiler -> durable memory
```

Edit `specs/003-thin-ui.md` memory wording so it says:

```markdown
- Provide summary/review pointer views for completed sessions. These views are compatibility
  surfaces; formal durable memory belongs to session2memory.
```

- [ ] **Step 7: Update minimal web copy**

Edit `apps/web/index.html` memory panel copy only. Replace user-visible memory tab/panel wording so it contains:

```html
證據摘要 / Review Pointer
```

and:

```html
session2memory owns formal memory compilation
```

Do not add new UI controls or change layout.

- [ ] **Step 8: Run tests and verify GREEN**

Run:

```bash
rtk uv run pytest tests/test_api.py -k 'memory_summary or memory_review_from_current_session_logs' -q
rtk uv run pytest tests/test_web.py -k 'memory_copy_identifies or readme_positions' -q
```

Expected: selected tests pass.

- [ ] **Step 9: Commit Task 5**

Run:

```bash
git add src/agentic_os/api.py README.md specs/002-session-memory-pipeline.md specs/003-thin-ui.md apps/web/index.html tests/test_api.py tests/test_web.py
git commit -m "docs: clarify session evidence memory boundary"
```

---

### Task 6: Full Regression and Closeout

**Files:**
- No new files expected.
- Review all changed files.

- [ ] **Step 1: Run focused evidence stack**

Run:

```bash
rtk uv run pytest tests/test_evidence.py tests/test_supervisor.py tests/test_api.py tests/test_cli.py tests/test_web.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full test and lint gate**

Run:

```bash
rtk uv run pytest -q && rtk uv run ruff check . && rtk uv run ruff format --check . && rtk uv run python -m compileall -q src tests && git diff --check
```

Expected:

```text
pytest exits 0
ruff check exits 0
ruff format --check exits 0
compileall exits 0
git diff --check exits 0
```

- [ ] **Step 3: Inspect public API shape manually**

Run a local shell harness through the API or CLI:

```bash
SESSION_ID="$(rtk uv run agentctl run shell --cwd "$PWD" --message "evidence smoke" | awk '{print $1}')"
rtk uv run agentctl sessions evidence "$SESSION_ID"
rtk uv run agentctl sessions evidence-events "$SESSION_ID" --json
```

Expected:

```text
sessions evidence includes metadata.schema_version=session_evidence.v1
sessions evidence-events includes run_accepted, process_started, process_exited
```

If `agentd` is not running, skip this smoke and record that only unit/API tests were run.

- [ ] **Step 4: Review diff for scope control**

Run:

```bash
git diff --stat
git diff -- src/agentic_os/evidence.py src/agentic_os/supervisor.py src/agentic_os/api.py src/agentic_os/client.py src/agentic_os/cli.py
```

Expected: changes are limited to Session Evidence v1, compatibility memory pointer metadata, and docs/copy boundary changes.

- [ ] **Step 5: Confirm no uncommitted verification drift**

Run:

```bash
git status --short
```

Expected: no output. If files changed, return to the task that owns those files, add a focused
test-first fix there, and commit with that task's file list.

- [ ] **Step 6: Request final review**

Dispatch final review over the full branch diff from the merge-base with `codex/adapter-contract-v2` or `main`, depending on the active branch ancestry. Review prompt:

```text
Review Session Evidence v1 implementation in /Users/waynetu/bootstrap/agentic-os.
Focus on correctness, evidence file durability, lifecycle coverage, API/CLI compatibility,
secret leakage risk, memory-boundary wording, and regression test coverage.
Do not edit files. Return APPROVED or CHANGES_REQUESTED with file/line findings.
```

- [ ] **Step 7: Publish only after review and gates**

If final review is approved and full gates passed:

```bash
git status --short --branch
git push -u origin codex/session-evidence-v1
```

Expected: branch tracks `origin/codex/session-evidence-v1`.

---

## Self-Review Checklist

- Spec coverage: evidence bundle, metadata, events, artifact manifest, API, CLI, memory boundary, error handling, tests, and acceptance criteria are mapped to tasks.
- No SessionRecord schema changes are planned.
- Existing stdout/stderr logs and memory routes remain compatible.
- No UI redesign is included; only minimal copy is changed.
- Formal memory ownership is assigned to `session2memory`.
- Every production behavior change has a failing-test step before implementation.
- Full gate includes pytest, Ruff check, Ruff format check, compileall, and diff check.
