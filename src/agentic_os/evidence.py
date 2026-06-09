from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from agentic_os.adapter_contract import SEMANTIC_HARNESS_IDS
from agentic_os.control_plane import _SECRET_FLAGS, _redact_value
from agentic_os.jsonio import atomic_write_json
from agentic_os.models import SessionRecord

EvidenceSeverity = Literal["debug", "info", "warning", "error"]
_PUBLIC_USAGE_COUNT_KEYS = {"input_tokens", "output_tokens", "total_tokens"}


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
        paths = self._ensure_bundle_files(session)
        if not paths.metadata.exists():
            self.write_metadata(session)
        return paths

    def write_metadata(self, session: SessionRecord) -> dict[str, Any]:
        paths = self._ensure_bundle_files(session)
        payload: dict[str, Any] = {
            "schema_version": "session_evidence.v1",
            "session_id": session.id,
            "harness_id": session.agent_id,
            "status": session.status.value,
            "cwd": session.cwd,
            "argv": _redact_argv(session.argv),
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
            "adapter_contract_version": (
                "v2" if session.agent_id in SEMANTIC_HARNESS_IDS else "v1"
            ),
            "working_tree": _working_tree_snapshot(Path(session.cwd)),
            "evidence_paths": self.path_payload(paths),
        }
        self._write_json(paths.metadata, payload)
        return payload

    def zip_for_session(self, session: SessionRecord) -> bytes:
        """Return a zip bundle with metadata.json, events.jsonl, stdout.log, stderr.log."""
        paths = self.ensure_bundle(session)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            if paths.metadata.exists():
                archive.write(paths.metadata, arcname="metadata.json")
            if paths.events.exists():
                archive.write(paths.events, arcname="events.jsonl")
            if paths.stdout.exists():
                archive.write(paths.stdout, arcname="stdout.log")
            if paths.stderr.exists():
                archive.write(paths.stderr, arcname="stderr.log")
            manifest_path = paths.artifact_dir / "manifest.json"
            if manifest_path.exists():
                archive.write(manifest_path, arcname="artifact_manifest.json")
        return buffer.getvalue()

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
            "message": str(_redact_value(message)),
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
        self._write_json(
            paths.artifact_manifest,
            {
                "schema_version": "artifact_manifest.v1",
                "session_id": session.id,
                "artifacts": artifacts,
            },
        )
        self.append_event(
            session,
            "artifact_recorded",
            f"artifact recorded: {path.name}",
            {"artifact_id": entry["id"], "path": entry["path"], "kind": kind},
        )
        return entry

    def _ensure_bundle_files(self, session: SessionRecord) -> EvidencePaths:
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

    def _display_path(self, path: Path) -> str:
        resolved = path.resolve()
        for root in (Path.cwd().resolve(), self.state_dir.resolve()):
            try:
                return str(resolved.relative_to(root))
            except ValueError:
                continue
        return str(resolved)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        atomic_write_json(path, payload)


def _event_from_raw(raw: dict[str, Any], index: int) -> EvidenceEvent | None:
    required = ("ts", "session_id", "harness_id", "event_type", "severity", "message", "metadata")
    if any(key not in raw for key in required):
        return None
    if raw["severity"] not in {"debug", "info", "warning", "error"}:
        return None
    if not isinstance(raw["metadata"], dict):
        return None
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


def _redact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _redact_evidence_value(value, str(key)) for key, value in metadata.items()}


def _redact_evidence_value(value: Any, key: str | None = None) -> Any:
    if (
        key in _PUBLIC_USAGE_COUNT_KEYS
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        return value
    if isinstance(value, list):
        return _redact_value(_redact_argv(value), key)
    if isinstance(value, dict):
        return _redact_value(_redact_metadata(value), key)
    return _redact_value(value, key)


def _redact_argv(values: list[Any]) -> list[Any]:
    redacted: list[Any] = []
    redact_next = False
    for value in values:
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            continue
        if isinstance(value, str) and value.lower() in _SECRET_FLAGS:
            redacted.append(value)
            redact_next = True
            continue
        redacted.append(_redact_evidence_value(value))
    return redacted


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
