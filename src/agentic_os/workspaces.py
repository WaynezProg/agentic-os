from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACES_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
  path TEXT PRIMARY KEY,
  label TEXT NOT NULL DEFAULT '',
  last_opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workspace_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

ACTIVE_WORKSPACE_KEY = "active_workspace"
MAX_RECENT_WORKSPACES = 20


@dataclass(frozen=True)
class WorkspaceRecord:
    path: str
    label: str
    last_opened_at: str
    added_at: str


class WorkspaceStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(WORKSPACES_SCHEMA)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_workspaces(self) -> list[WorkspaceRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT path, label, last_opened_at, added_at FROM workspaces "
                "ORDER BY last_opened_at DESC, path ASC"
            ).fetchall()
        return [_workspace_from_row(row) for row in rows]

    def get_active(self) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM workspace_state WHERE key = ?",
                (ACTIVE_WORKSPACE_KEY,),
            ).fetchone()
        return None if row is None else str(row["value"])

    def set_active(self, path: str) -> WorkspaceRecord:
        resolved = _resolve_workspace_path(path)
        record = self.touch(resolved)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO workspace_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (ACTIVE_WORKSPACE_KEY, record.path),
            )
        return record

    def touch(self, path: str) -> WorkspaceRecord:
        resolved = _resolve_workspace_path(path)
        label = Path(resolved).name or resolved
        now = _now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO workspaces (path, label, last_opened_at, added_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                  label = excluded.label,
                  last_opened_at = excluded.last_opened_at
                """,
                (resolved, label, now, now),
            )
            self._trim_recent(conn)
        return self.get(resolved)

    def get(self, path: str) -> WorkspaceRecord:
        resolved = _resolve_workspace_path(path)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT path, label, last_opened_at, added_at FROM workspaces WHERE path = ?",
                (resolved,),
            ).fetchone()
        if row is None:
            raise KeyError(resolved)
        return _workspace_from_row(row)

    def remove(self, path: str) -> None:
        resolved = _resolve_workspace_path(path)
        with self.connect() as conn:
            conn.execute("DELETE FROM workspaces WHERE path = ?", (resolved,))
            active = conn.execute(
                "SELECT value FROM workspace_state WHERE key = ?",
                (ACTIVE_WORKSPACE_KEY,),
            ).fetchone()
            if active is not None and active["value"] == resolved:
                conn.execute(
                    "DELETE FROM workspace_state WHERE key = ?",
                    (ACTIVE_WORKSPACE_KEY,),
                )

    def _trim_recent(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            DELETE FROM workspaces
            WHERE path NOT IN (
              SELECT path FROM workspaces
              ORDER BY last_opened_at DESC, path ASC
              LIMIT ?
            )
            """,
            (MAX_RECENT_WORKSPACES,),
        )


def _resolve_workspace_path(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise ValueError(f"workspace path does not exist: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"workspace path is not a directory: {resolved}")
    return str(resolved)


def _workspace_from_row(row: sqlite3.Row) -> WorkspaceRecord:
    return WorkspaceRecord(
        path=row["path"],
        label=row["label"],
        last_opened_at=row["last_opened_at"],
        added_at=row["added_at"],
    )


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_workspace_dashboard(
    cwd: str,
    *,
    profiles_module: Any,
    registry: Any,
    store: Any,
    approval_store: Any,
    audit_store: Any | None = None,
) -> dict[str, object]:
    from agentic_os.approvals import ApprovalStatus
    from agentic_os.models import SessionStatus

    resolved_cwd = _resolve_workspace_path(cwd)
    profiles = profiles_module.list_profiles(resolved_cwd)
    bindings = profiles_module.list_project_bindings(resolved_cwd)
    profile_name = profiles_module.resolve_project_profile(resolved_cwd, bindings)
    active_profile = profiles.get(profile_name) if profile_name else None
    cwd_path = Path(resolved_cwd)
    sessions = [
        session
        for session in store.list_sessions()
        if Path(session.cwd).resolve() == cwd_path
    ]
    running = sum(1 for session in sessions if session.status == SessionStatus.RUNNING)
    failed = sum(1 for session in sessions if session.status == SessionStatus.FAILED)
    pending_approvals = sum(
        1 for approval in approval_store.list() if approval.status == ApprovalStatus.PENDING
    )
    recent_patches = 0
    if audit_store is not None:
        recent_patches = len(
            [
                event
                for event in audit_store.list_events(domain="config_patch", limit=20)
                if event.entity_id
            ]
        )
    harnesses = [agent.id for agent in registry.list_agents() if agent.enabled]
    return {
        "cwd": resolved_cwd,
        "active_profile": profile_name,
        "provider": active_profile.provider if active_profile is not None else None,
        "model": active_profile.model if active_profile is not None else None,
        "harness_id": active_profile.harness_id if active_profile is not None else None,
        "sessions": {
            "total": len(sessions),
            "running": running,
            "failed": failed,
        },
        "pending_approvals": pending_approvals,
        "recent_config_patches": recent_patches,
        "harnesses": harnesses,
    }
