from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AuditEvent:
    id: int
    domain: str
    entity_id: str
    event_type: str
    message: str
    metadata: dict[str, object]
    created_at: str


# Remote `/events` stream selection (P13). The reference gateway pushes config
# patch activity plus the approval lifecycle so a paired operator can see and act
# on pending launches. Other governance events (e.g. `policy_evaluated`) stay local.
REMOTE_STREAM_CONFIG_DOMAIN = "config_patch"
REMOTE_STREAM_APPROVAL_DOMAIN = "governance"
REMOTE_STREAM_APPROVAL_EVENT_TYPES = (
    "approval_requested",
    "approval_approved",
    "approval_rejected",
    "approval_expired",
    "run_started_after_approval",
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_domain ON audit_events (domain);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events (entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events (event_type);
"""


class AuditStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def init(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def record(
        self,
        domain: str,
        entity_id: str,
        event_type: str,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> AuditEvent:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_events (domain, entity_id, event_type, message, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (domain, entity_id, event_type, message, json.dumps(metadata or {})),
            )
            row = conn.execute(
                "SELECT * FROM audit_events WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._row_to_event(row)

    def list_events(
        self,
        *,
        domain: str | None = None,
        entity_id: str | None = None,
        event_type: str | None = None,
        limit: int = 500,
    ) -> list[AuditEvent]:
        clauses: list[str] = []
        params: list[object] = []
        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain)
        if entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM audit_events{where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_events_after_id(
        self,
        after_id: int,
        *,
        domain: str | None = None,
        limit: int = 20,
    ) -> list[AuditEvent]:
        clauses = ["id > ?"]
        params: list[object] = [after_id]
        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain)
        where = " WHERE " + " AND ".join(clauses)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM audit_events{where} ORDER BY id ASC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_remote_stream_events_after_id(
        self,
        after_id: int,
        *,
        limit: int = 20,
    ) -> list[AuditEvent]:
        """Events the remote `/events` stream is allowed to push (P13).

        Returns all `config_patch` events plus allowlisted `governance` approval
        lifecycle events with id greater than ``after_id``, ordered ascending so a
        remote cursor never rewinds.
        """
        placeholders = ", ".join("?" for _ in REMOTE_STREAM_APPROVAL_EVENT_TYPES)
        sql = f"""
            SELECT * FROM audit_events
            WHERE id > ?
              AND (
                domain = ?
                OR (domain = ? AND event_type IN ({placeholders}))
              )
            ORDER BY id ASC
            LIMIT ?
        """
        params: list[object] = [
            after_id,
            REMOTE_STREAM_CONFIG_DOMAIN,
            REMOTE_STREAM_APPROVAL_DOMAIN,
            *REMOTE_STREAM_APPROVAL_EVENT_TYPES,
            limit,
        ]
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_event(row) for row in rows]

    def policy_coverage(
        self,
        agent_ids: list[str],
        session_ids_by_agent: dict[str, list[str]],
        policy_agent_ids: list[str],
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        policy_agent_id_set = set(policy_agent_ids)
        with self._connect() as conn:
            for agent_id in agent_ids:
                row = conn.execute(
                    """
                    SELECT created_at FROM audit_events
                    WHERE domain = 'governance'
                      AND event_type = 'policy_evaluated'
                      AND entity_id = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (agent_id,),
                ).fetchone()
                last_evaluated_at = row["created_at"] if row else None

                has_policy = agent_id in policy_agent_id_set

                session_ids = session_ids_by_agent.get(agent_id, [])
                covered_rows = conn.execute(
                    """
                    SELECT metadata_json FROM audit_events
                    WHERE domain = 'governance'
                      AND event_type = 'policy_evaluated'
                      AND entity_id = ?
                    """,
                    (agent_id,),
                ).fetchall()
                covered_session_ids: set[str] = set()
                for cr in covered_rows:
                    meta = json.loads(cr["metadata_json"])
                    if "session_id" in meta:
                        covered_session_ids.add(meta["session_id"])

                runs_without = [sid for sid in session_ids if sid not in covered_session_ids]

                result.append(
                    {
                        "agent_id": agent_id,
                        "has_policy": has_policy,
                        "last_evaluated_at": last_evaluated_at,
                        "recent_run_count": len(session_ids),
                        "runs_without_policy_evaluation": runs_without,
                    }
                )
        return result

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            id=row["id"],
            domain=row["domain"],
            entity_id=row["entity_id"],
            event_type=row["event_type"],
            message=row["message"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
        )
