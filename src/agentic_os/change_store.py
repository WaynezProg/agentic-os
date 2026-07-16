from __future__ import annotations

import sqlite3
from pathlib import Path

from agentic_os.change_models import ChangePlan

CHANGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS change_plans (
    id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_change_plans_created
ON change_plans (created_at DESC);
"""


class ChangeStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(CHANGE_SCHEMA)

    def create(self, plan: ChangePlan) -> ChangePlan:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO change_plans (
                    id,
                    operation,
                    environment_id,
                    status,
                    payload_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.id,
                    plan.operation,
                    plan.environment_id,
                    plan.status,
                    plan.model_dump_json(),
                    plan.created_at,
                    plan.updated_at,
                ),
            )
        return plan

    def update(self, plan: ChangePlan) -> ChangePlan:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE change_plans
                SET operation = ?,
                    environment_id = ?,
                    status = ?,
                    payload_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    plan.operation,
                    plan.environment_id,
                    plan.status,
                    plan.model_dump_json(),
                    plan.updated_at,
                    plan.id,
                ),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"unknown change plan: {plan.id}")
        return plan

    def get(self, change_id: str) -> ChangePlan:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM change_plans WHERE id = ?",
                (change_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown change plan: {change_id}")
        return ChangePlan.model_validate_json(row["payload_json"])

    def list(self, *, limit: int = 200) -> list[ChangePlan]:
        bounded_limit = max(1, min(limit, 1000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM change_plans
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        return [ChangePlan.model_validate_json(row["payload_json"]) for row in rows]

    def find_by_backup_ref(self, patch_id: str) -> ChangePlan | None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM change_plans
                ORDER BY created_at DESC, rowid DESC
                """
            ).fetchall()
        for row in rows:
            plan = ChangePlan.model_validate_json(row["payload_json"])
            if plan.backup_ref == patch_id:
                return plan
        return None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn
