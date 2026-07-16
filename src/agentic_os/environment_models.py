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
