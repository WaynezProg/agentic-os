from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from agentic_os.models import EventRecord, SessionCreate, SessionRecord, SessionStatus


ALLOWED_TRANSITIONS = {
    SessionStatus.QUEUED: frozenset({SessionStatus.RUNNING, SessionStatus.FAILED}),
    SessionStatus.RUNNING: frozenset(
        {
            SessionStatus.STOPPING,
            SessionStatus.SUCCEEDED,
            SessionStatus.FAILED,
            SessionStatus.STOPPED,
        }
    ),
    SessionStatus.STOPPING: frozenset({SessionStatus.STOPPED, SessionStatus.FAILED}),
    SessionStatus.SUCCEEDED: frozenset(),
    SessionStatus.FAILED: frozenset(),
    SessionStatus.STOPPED: frozenset(),
}
ALLOWED_PREVIOUS_STATUSES = {
    status: tuple(
        current_status
        for current_status in SessionStatus
        if status in ALLOWED_TRANSITIONS[current_status]
    )
    for status in SessionStatus
}
SESSION_STATUS_SQL = ", ".join(f"'{status.value}'" for status in SessionStatus)

EVENTS_SCHEMA = """
CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
"""

SCHEMA = f"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  command_json TEXT NOT NULL,
  cwd_mode TEXT NOT NULL,
  env_json TEXT NOT NULL DEFAULT '{{}}',
  stop_policy TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  cwd TEXT NOT NULL,
  argv_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ({SESSION_STATUS_SQL})),
  pid INTEGER,
  pgid INTEGER,
  exit_code INTEGER,
  artifact_dir TEXT NOT NULL,
  stdout_log TEXT NOT NULL,
  stderr_log TEXT NOT NULL,
  summary_one_liner TEXT NOT NULL DEFAULT '',
  started_at TEXT,
  ended_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{{}}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate_events_foreign_key(conn)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def create_session(self, request: SessionCreate) -> SessionRecord:
        session_id = f"s_{uuid.uuid4().hex}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                  id, agent_id, cwd, argv_json, status, artifact_dir,
                  stdout_log, stderr_log, summary_one_liner, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    session_id,
                    request.agent_id,
                    request.cwd,
                    json.dumps(request.argv),
                    SessionStatus.QUEUED.value,
                    request.artifact_dir,
                    request.stdout_log,
                    request.stderr_log,
                    request.summary_one_liner,
                ),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> SessionRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return _session_from_row(row)

    def list_sessions(self) -> list[SessionRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC, id DESC").fetchall()
        return [_session_from_row(row) for row in rows]

    def mark_running(self, session_id: str, pid: int, pgid: int) -> SessionRecord:
        return self._transition_session(
            session_id,
            SessionStatus.RUNNING,
            "pid = ?, pgid = ?, started_at = CURRENT_TIMESTAMP",
            (pid, pgid),
        )

    def mark_stopping(self, session_id: str) -> SessionRecord:
        return self._set_status(session_id, SessionStatus.STOPPING)

    def mark_stopped(self, session_id: str) -> SessionRecord:
        return self._transition_session(
            session_id,
            SessionStatus.STOPPED,
            "ended_at = CURRENT_TIMESTAMP",
        )

    def mark_failed(self, session_id: str, exit_code: int | None = None) -> SessionRecord:
        return self._transition_session(
            session_id,
            SessionStatus.FAILED,
            "exit_code = ?, ended_at = CURRENT_TIMESTAMP",
            (exit_code,),
        )

    def mark_finished(self, session_id: str, exit_code: int) -> SessionRecord:
        status = SessionStatus.SUCCEEDED if exit_code == 0 else SessionStatus.FAILED
        return self._transition_session(
            session_id,
            status,
            "exit_code = ?, ended_at = CURRENT_TIMESTAMP",
            (exit_code,),
        )

    def record_event(
        self,
        session_id: str,
        event_type: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO events (session_id, event_type, message, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, event_type, message, json.dumps(metadata or {})),
            )

    def list_events(self, session_id: str) -> list[EventRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [
            EventRecord(
                id=row["id"],
                session_id=row["session_id"],
                event_type=row["event_type"],
                message=row["message"],
                metadata=json.loads(row["metadata_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _set_status(self, session_id: str, status: SessionStatus) -> SessionRecord:
        return self._transition_session(session_id, status)

    def _transition_session(
        self,
        session_id: str,
        status: SessionStatus,
        assignments: str = "",
        values: tuple[Any, ...] = (),
    ) -> SessionRecord:
        allowed_previous_statuses = ALLOWED_PREVIOUS_STATUSES[status]
        if not allowed_previous_statuses:
            with self.connect() as conn:
                _raise_transition_error(conn, session_id, status)

        placeholders = ", ".join("?" for _ in allowed_previous_statuses)
        set_clause = "status = ?"
        if assignments:
            set_clause = f"{set_clause}, {assignments}"
        set_clause = f"{set_clause}, updated_at = CURRENT_TIMESTAMP"

        with self.connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE sessions
                SET {set_clause}
                WHERE id = ? AND status IN ({placeholders})
                """,
                (
                    status.value,
                    *values,
                    session_id,
                    *(previous_status.value for previous_status in allowed_previous_statuses),
                ),
            )
            if cursor.rowcount != 1:
                _raise_transition_error(conn, session_id, status)
        return self.get_session(session_id)

    def _migrate_events_foreign_key(self, conn: sqlite3.Connection) -> None:
        if _events_has_session_foreign_key(conn):
            return

        conn.execute("ALTER TABLE events RENAME TO events_without_session_fk")
        conn.execute(EVENTS_SCHEMA)
        conn.execute(
            """
            INSERT INTO events (id, session_id, event_type, message, metadata_json, created_at)
            SELECT
              events_without_session_fk.id,
              events_without_session_fk.session_id,
              events_without_session_fk.event_type,
              events_without_session_fk.message,
              events_without_session_fk.metadata_json,
              events_without_session_fk.created_at
            FROM events_without_session_fk
            WHERE EXISTS (
              SELECT 1
              FROM sessions
              WHERE sessions.id = events_without_session_fk.session_id
            )
            """
        )
        conn.execute("DROP TABLE events_without_session_fk")


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        agent_id=row["agent_id"],
        cwd=row["cwd"],
        argv=json.loads(row["argv_json"]),
        status=SessionStatus(row["status"]),
        pid=row["pid"],
        pgid=row["pgid"],
        exit_code=row["exit_code"],
        artifact_dir=row["artifact_dir"],
        stdout_log=row["stdout_log"],
        stderr_log=row["stderr_log"],
        summary_one_liner=row["summary_one_liner"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        updated_at=row["updated_at"],
    )


def _events_has_session_foreign_key(conn: sqlite3.Connection) -> bool:
    foreign_keys = conn.execute("PRAGMA foreign_key_list(events)").fetchall()
    return any(row[2] == "sessions" and row[3] == "session_id" for row in foreign_keys)


def _raise_transition_error(
    conn: sqlite3.Connection, session_id: str, status: SessionStatus
) -> None:
    row = conn.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise KeyError(session_id)

    current_status = SessionStatus(row["status"])
    raise ValueError(
        f"Cannot transition session {session_id} "
        f"from {current_status.value} to {status.value}"
    )
