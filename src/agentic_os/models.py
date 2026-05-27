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
    env: dict[str, str] = Field(default_factory=dict, exclude=True)
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
