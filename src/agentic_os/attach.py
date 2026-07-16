"""Harness attach preview/exec helpers (read-only attach semantics)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agentic_os.models import AgentDefinition, SessionRecord

AttachDecision = Literal["allow", "deny", "unsupported"]
AttachStatus = Literal["none", "available", "attached", "unsupported"]


@dataclass(frozen=True)
class DiscoveredSession:
    """A single external session discovered in a workspace log path."""

    agent_id: str
    external_session_id: str
    log_path: str
    started_at: str | None = None


@dataclass(frozen=True)
class DiscoveredSessionScan:
    sessions: list[DiscoveredSession]
    files_examined: int

# Vibe coding agents: developer-driven, short iterations
_VIBE_CODING = frozenset({"claude", "codex", "cursor", "opencode", "qwen"})

# Agentic runtime agents: autonomous, long sessions
_AGENTIC = frozenset({"openclaw", "hermes"})

# All supported agents for attach
_SUPPORTED = _VIBE_CODING | _AGENTIC

# Explicitly unsupported (internal/test agents)
_UNSUPPORTED = frozenset({"shell"})

_SESSION_ID_KEYS = ("sessionId", "session_id", "sessionID", "external_session_id", "id")


def parse_external_session_id(agent_id: str, stdout_log: Path) -> str | None:
    """Parse external session ID from tool-specific stdout format."""
    if agent_id not in _SUPPORTED:
        return None
    if not stdout_log.exists():
        return None
    try:
        lines = stdout_log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    # Search last 40 lines for session metadata
    for line in reversed(lines[-40:]):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        # Try standard keys
        for key in _SESSION_ID_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value

    return None


def default_attach_status(agent_id: str, *, has_attach_command: bool) -> AttachStatus:
    """Return default attach status for an agent."""
    if agent_id in _UNSUPPORTED or not has_attach_command:
        return "unsupported"
    if agent_id in _SUPPORTED:
        return "none"
    return "unsupported"


def build_attach_command(agent: AgentDefinition, session: SessionRecord) -> list[str]:
    """Build the attach command for a given agent and session."""
    if not agent.attach_command:
        return []
    command = list(agent.attach_command)
    external_id = session.external_session_id

    if not external_id:
        return command

    # All supported agents append external_session_id as last arg
    if agent.id in _SUPPORTED:
        return [*command, external_id]

    return command


def evaluate_attach(
    agent: AgentDefinition,
    session: SessionRecord,
) -> tuple[AttachDecision, str]:
    """Evaluate whether attach is permitted for this agent/session."""
    if agent.id in _UNSUPPORTED or not agent.attach_command:
        return "unsupported", f"harness {agent.id} does not support attach"
    if agent.id not in _SUPPORTED:
        return "unsupported", f"harness {agent.id} attach matrix not defined"
    if session.attach_status == "unsupported":
        return "unsupported", "session marked unsupported for attach"
    if session.attach_status == "attached":
        return "deny", "session already attached"

    # All supported agents require external_session_id
    if not session.external_session_id:
        if agent.id == "opencode":
            return "unsupported", "opencode attach requires server URL in session output"
        return "deny", "external_session_id required for attach"

    return "allow", "attach permitted"


def _session_workspace(jsonl: Path) -> str | None:
    """Best-effort cwd/workspace recorded in the session's JSONL head."""
    try:
        with jsonl.open("r", encoding="utf-8", errors="replace") as fh:
            for index, line in enumerate(fh):
                if index >= 40:
                    break
                stripped = line.strip()
                if not stripped.startswith("{"):
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                for key in ("cwd", "workspace", "workspace_path"):
                    value = payload.get(key)
                    if isinstance(value, str) and value:
                        return value
    except OSError:
        return None
    return None


def discover_external_sessions(
    *,
    workspace_path: str,
    agents: list[AgentDefinition],
    max_files: int = 500,
) -> list[DiscoveredSession]:
    return scan_external_sessions(
        workspace_path=workspace_path,
        agents=agents,
        max_files=max_files,
    ).sessions


def scan_external_sessions(
    *,
    workspace_path: str,
    agents: list[AgentDefinition],
    max_files: int = 500,
) -> DiscoveredSessionScan:
    """Scan agent log_paths for external sessions recorded in workspace_path.

    Sessions whose JSONL head carries no resolvable cwd are excluded —
    the endpoint promises workspace-scoped results, so unscopable files
    must not leak in (codex review P1).
    """
    try:
        target = Path(workspace_path).expanduser().resolve()
    except (TypeError, ValueError, OSError):
        return DiscoveredSessionScan([], 0)
    results: list[DiscoveredSession] = []
    files_examined = 0
    bounded_max_files = max(1, max_files)
    for agent in agents:
        if agent.id not in _SUPPORTED:
            continue
        for raw_path in agent.log_paths:
            try:
                root = Path(raw_path).expanduser()
            except (TypeError, ValueError):
                continue
            if not root.exists() or not root.is_dir():
                continue
            for jsonl in root.rglob("*.jsonl"):
                if files_examined >= bounded_max_files:
                    return DiscoveredSessionScan(results, files_examined)
                if not jsonl.is_file():
                    continue
                files_examined += 1
                try:
                    external_id = parse_external_session_id(agent.id, jsonl)
                except Exception:  # parser must never crash the discover flow
                    continue
                if not external_id:
                    continue
                session_ws = _session_workspace(jsonl)
                if session_ws is None:
                    continue
                try:
                    if Path(session_ws).expanduser().resolve() != target:
                        continue
                except (ValueError, OSError):
                    continue
                started_at = _read_started_at(jsonl)
                results.append(
                    DiscoveredSession(
                        agent_id=agent.id,
                        external_session_id=external_id,
                        log_path=str(jsonl),
                        started_at=started_at,
                    )
                )
    return DiscoveredSessionScan(results, files_examined)


def _read_started_at(jsonl: Path) -> str | None:
    """Best-effort: read the first JSONL line's ts/startedAt if present."""
    try:
        with jsonl.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped.startswith("{"):
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                for key in ("startedAt", "started_at", "ts", "timestamp"):
                    value = payload.get(key)
                    if isinstance(value, str) and value:
                        return value
    except OSError:
        return None
    return None


def capture_external_session_after_run(
    store: object,
    session_id: str,
    *,
    has_attach_command: bool = False,
) -> None:
    """After a run completes, capture external session ID if available."""
    from agentic_os.storage import Store

    if not isinstance(store, Store):
        return
    session = store.get_session(session_id)
    external_id = parse_external_session_id(session.agent_id, Path(session.stdout_log))
    if external_id and session.agent_id in _SUPPORTED:
        store.update_session_attach(
            session_id,
            external_session_id=external_id,
            attachable=True,
            attach_status="available",
        )
        return
    store.update_session_attach(
        session_id,
        attach_status=default_attach_status(
            session.agent_id,
            has_attach_command=has_attach_command,
        ),
        attachable=False,
    )
