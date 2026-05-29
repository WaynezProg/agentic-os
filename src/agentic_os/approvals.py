from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


APPROVAL_STATUS_SQL = ", ".join(f"'{status.value}'" for status in ApprovalStatus)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  source_session_id TEXT NOT NULL,
  approved_session_id TEXT,
  agent_id TEXT NOT NULL,
  cwd TEXT NOT NULL,
  argv_json TEXT NOT NULL,
  env_json TEXT NOT NULL DEFAULT '{{}}',
  reason TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ({APPROVAL_STATUS_SQL})),
  decision_reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True)
class ApprovalCreate:
    source_session_id: str
    agent_id: str
    cwd: str
    argv: list[str]
    env: dict[str, str]
    reason: str


@dataclass(frozen=True)
class ApprovalRecord:
    id: str
    source_session_id: str
    approved_session_id: str | None
    agent_id: str
    cwd: str
    argv: list[str]
    env: dict[str, str]
    reason: str
    status: ApprovalStatus
    decision_reason: str
    created_at: str
    updated_at: str


class ApprovalStore:
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

    def create(self, request: ApprovalCreate) -> ApprovalRecord:
        approval_id = f"ap_{uuid.uuid4().hex}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals (
                  id, source_session_id, agent_id, cwd, argv_json, env_json, reason, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    request.source_session_id,
                    request.agent_id,
                    request.cwd,
                    json.dumps([str(arg) for arg in request.argv]),
                    json.dumps({str(k): str(v) for k, v in request.env.items()}),
                    request.reason,
                    ApprovalStatus.PENDING.value,
                ),
            )
        return self.get(approval_id)

    def list(self) -> list[ApprovalRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM approvals
                ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, updated_at DESC, id DESC
                """
            ).fetchall()
        return [_from_row(row) for row in rows]

    def get(self, approval_id: str) -> ApprovalRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            raise KeyError(approval_id)
        return _from_row(row)

    def approve(self, approval_id: str, approved_session_id: str) -> ApprovalRecord:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE approvals
                SET status = ?, approved_session_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ?
                """,
                (
                    ApprovalStatus.APPROVED.value,
                    approved_session_id,
                    approval_id,
                    ApprovalStatus.PENDING.value,
                ),
            )
            if cursor.rowcount != 1:
                self._require_pending(approval_id)
        return self.get(approval_id)

    def claim(self, approval_id: str) -> ApprovalRecord:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE approvals
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ?
                """,
                (ApprovalStatus.APPROVED.value, approval_id, ApprovalStatus.PENDING.value),
            )
            if cursor.rowcount != 1:
                self._require_pending(approval_id)
        return self.get(approval_id)

    def link_approved_session(
        self,
        approval_id: str,
        approved_session_id: str,
    ) -> ApprovalRecord:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE approvals
                SET approved_session_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ? AND approved_session_id IS NULL
                """,
                (approved_session_id, approval_id, ApprovalStatus.APPROVED.value),
            )
            if cursor.rowcount != 1:
                current = self.get(approval_id)
                if current.status != ApprovalStatus.APPROVED:
                    raise ValueError(f"approval {approval_id} is not approved")
                raise ValueError(f"approval {approval_id} already has an approved session")
        return self.get(approval_id)

    def reject(self, approval_id: str, reason: str) -> ApprovalRecord:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE approvals
                SET status = ?, decision_reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ?
                """,
                (ApprovalStatus.REJECTED.value, reason, approval_id, ApprovalStatus.PENDING.value),
            )
            if cursor.rowcount != 1:
                self._require_pending(approval_id)
        return self.get(approval_id)

    def expire(self, approval_id: str, reason: str) -> ApprovalRecord:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE approvals
                SET status = ?, decision_reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ?
                """,
                (ApprovalStatus.EXPIRED.value, reason, approval_id, ApprovalStatus.PENDING.value),
            )
            if cursor.rowcount != 1:
                self._require_pending(approval_id)
        return self.get(approval_id)

    def _require_pending(self, approval_id: str) -> ApprovalRecord:
        current = self.get(approval_id)
        if current.status != ApprovalStatus.PENDING:
            raise ValueError(f"approval {approval_id} is not pending")
        return current


def _from_row(row: sqlite3.Row) -> ApprovalRecord:
    return ApprovalRecord(
        id=row["id"],
        source_session_id=row["source_session_id"],
        approved_session_id=row["approved_session_id"],
        agent_id=row["agent_id"],
        cwd=row["cwd"],
        argv=[str(value) for value in json.loads(row["argv_json"])],
        env={str(key): str(value) for key, value in json.loads(row["env_json"]).items()},
        reason=row["reason"],
        status=ApprovalStatus(row["status"]),
        decision_reason=row["decision_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
