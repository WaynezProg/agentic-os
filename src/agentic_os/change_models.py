from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

ChangeStatus = Literal[
    "previewed",
    "approved",
    "applying",
    "verified",
    "partial",
    "failed",
    "rolled_back",
    "rollback_failed",
    "stale",
]


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ChangeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    operation: str
    environment_id: str


class ChangeVerification(BaseModel):
    status: Literal["verified", "partial", "failed"]
    observed: dict[str, object] = Field(default_factory=dict)
    checks: list[dict[str, object]] = Field(default_factory=list)


class ChangePlan(BaseModel):
    id: str = Field(default_factory=lambda: f"chg_{uuid4().hex}")
    operation: str
    environment_id: str
    target_surfaces: list[str]
    status: ChangeStatus
    redacted_request: dict[str, object]
    before_evidence: dict[str, object]
    diff: dict[str, object]
    validation: dict[str, object]
    base_versions: dict[str, object] = Field(default_factory=dict)
    preview_result: dict[str, object] = Field(default_factory=dict)
    restart_requirements: list[str] = Field(default_factory=list)
    backup_ref: str | None = None
    apply_result: dict[str, object] | None = None
    verification: ChangeVerification | None = None
    rollback: dict[str, object] | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @classmethod
    def previewed(cls, **values: object) -> ChangePlan:
        return cls(status="previewed", **values)

    def with_updates(self, **updates: object) -> ChangePlan:
        payload = self.model_dump(mode="python")
        payload.update(updates)
        payload["updated_at"] = now_iso()
        return ChangePlan.model_validate(payload)
