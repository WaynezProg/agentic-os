"""Harness attach preview/exec helpers (read-only attach semantics)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from agentic_os.models import AgentDefinition, SessionRecord

AttachDecision = Literal["allow", "deny", "unsupported"]
AttachStatus = Literal["none", "available", "attached", "unsupported"]

_SUPPORTED = frozenset({"openclaw", "hermes", "opencode"})
_UNSUPPORTED = frozenset({"claude", "codex", "qwen", "shell"})
_SESSION_ID_KEYS = ("sessionId", "session_id", "sessionID", "external_session_id", "id")


def parse_external_session_id(agent_id: str, stdout_log: Path) -> str | None:
    if agent_id != "openclaw":
        return None
    if not stdout_log.exists():
        return None
    try:
        lines = stdout_log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
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
        for key in _SESSION_ID_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def default_attach_status(agent_id: str, *, has_attach_command: bool) -> AttachStatus:
    if agent_id in _UNSUPPORTED or not has_attach_command:
        return "unsupported"
    if agent_id in _SUPPORTED:
        return "none"
    return "unsupported"


def build_attach_command(agent: AgentDefinition, session: SessionRecord) -> list[str]:
    if not agent.attach_command:
        return []
    command = list(agent.attach_command)
    external_id = session.external_session_id
    if agent.id == "openclaw" and external_id:
        return [*command, external_id]
    if agent.id == "hermes" and external_id:
        return ["hermes", "--resume", external_id]
    if agent.id == "opencode" and external_id:
        return [*command, external_id]
    return command


def evaluate_attach(
    agent: AgentDefinition,
    session: SessionRecord,
) -> tuple[AttachDecision, str]:
    if agent.id in _UNSUPPORTED or not agent.attach_command:
        return "unsupported", f"harness {agent.id} does not support attach"
    if agent.id not in _SUPPORTED:
        return "unsupported", f"harness {agent.id} attach matrix not defined"
    if session.attach_status == "unsupported":
        return "unsupported", "session marked unsupported for attach"
    if session.attach_status == "attached":
        return "deny", "session already attached"
    if agent.id in {"openclaw", "hermes", "opencode"} and not session.external_session_id:
        if agent.id == "opencode":
            return "unsupported", "opencode attach requires server URL in session output"
        return "deny", "external_session_id required for attach"
    return "allow", "attach permitted"


def capture_external_session_after_run(
    store: object,
    session_id: str,
    *,
    has_attach_command: bool = False,
) -> None:
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
