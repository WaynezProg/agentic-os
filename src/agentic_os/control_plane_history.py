from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from agentic_os.patch_engine import PatchEngine

EntityType = Literal["skill", "mcp", "policy"]

HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS control_plane_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('skill', 'mcp', 'policy')),
  entity_id TEXT NOT NULL,
  patch_id TEXT NOT NULL UNIQUE,
  version INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'api',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  rolled_back_at TEXT
);
"""


@dataclass(frozen=True)
class ControlPlaneMutationResult:
    patch_id: str
    applied: bool
    diff: dict[str, Any]
    audit_event_id: int | None
    record: Any = None


@dataclass(frozen=True)
class ControlPlaneHistoryEntry:
    patch_id: str
    entity_type: str
    entity_id: str
    version: int
    snapshot_json: str
    source: str
    created_at: str
    rolled_back_at: str | None


class HistoryConflictError(Exception):
    pass


def mutation_envelope(result: ControlPlaneMutationResult) -> dict[str, Any]:
    return {
        "patch_id": result.patch_id,
        "applied": result.applied,
        "diff": result.diff,
        "audit_event_id": result.audit_event_id,
    }


def entity_diff(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, Any]:
    return PatchEngine.diff(before or {}, after)


def next_history_version(conn: sqlite3.Connection, entity_type: EntityType, entity_id: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(version), 0) AS max_version
        FROM control_plane_history
        WHERE entity_type = ? AND entity_id = ?
        """,
        (entity_type, entity_id),
    ).fetchone()
    max_version = int(row["max_version"]) if row is not None else 0
    return max_version + 1


def insert_history(
    conn: sqlite3.Connection,
    *,
    entity_type: EntityType,
    entity_id: str,
    patch_id: str,
    version: int,
    snapshot: dict[str, Any],
    source: str,
) -> None:
    conn.execute(
        """
        INSERT INTO control_plane_history (
          entity_type, entity_id, patch_id, version, snapshot_json, source
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (entity_type, entity_id, patch_id, version, json.dumps(snapshot), source),
    )


def list_history(
    conn: sqlite3.Connection,
    *,
    entity_type: EntityType,
    entity_id: str,
    limit: int = 50,
) -> list[ControlPlaneHistoryEntry]:
    rows = conn.execute(
        """
        SELECT patch_id, entity_type, entity_id, version, snapshot_json, source,
               created_at, rolled_back_at
        FROM control_plane_history
        WHERE entity_type = ? AND entity_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (entity_type, entity_id, limit),
    ).fetchall()
    return [_history_from_row(row) for row in rows]


def get_history_entry(
    conn: sqlite3.Connection,
    *,
    entity_type: EntityType,
    entity_id: str,
    patch_id: str,
) -> ControlPlaneHistoryEntry | None:
    row = conn.execute(
        """
        SELECT patch_id, entity_type, entity_id, version, snapshot_json, source,
               created_at, rolled_back_at
        FROM control_plane_history
        WHERE entity_type = ? AND entity_id = ? AND patch_id = ?
        """,
        (entity_type, entity_id, patch_id),
    ).fetchone()
    if row is None:
        return None
    return _history_from_row(row)


def mark_history_rolled_back(conn: sqlite3.Connection, patch_id: str) -> None:
    conn.execute(
        """
        UPDATE control_plane_history
        SET rolled_back_at = CURRENT_TIMESTAMP
        WHERE patch_id = ?
        """,
        (patch_id,),
    )


def history_row_dict(entry: ControlPlaneHistoryEntry) -> dict[str, Any]:
    target_kind = {
        "skill": "skill",
        "mcp": "mcp_server",
        "policy": "policy",
    }[entry.entity_type]
    return {
        "patch_id": entry.patch_id,
        "target_kind": target_kind,
        "surface_id": entry.entity_id,
        "target_path": entry.entity_id,
        "source": entry.source,
        "created_at": entry.created_at,
        "rolled_back_at": entry.rolled_back_at,
        "version": entry.version,
    }


def new_patch_id() -> str:
    return f"p_{uuid.uuid4().hex}"


def _history_from_row(row: sqlite3.Row) -> ControlPlaneHistoryEntry:
    return ControlPlaneHistoryEntry(
        patch_id=row["patch_id"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        version=int(row["version"]),
        snapshot_json=row["snapshot_json"],
        source=row["source"],
        created_at=row["created_at"],
        rolled_back_at=row["rolled_back_at"],
    )
