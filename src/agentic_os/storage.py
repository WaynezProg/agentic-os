from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from agentic_os.models import EventRecord, SessionCreate, SessionRecord, SessionStatus


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  command_json TEXT NOT NULL,
  cwd_mode TEXT NOT NULL,
  env_json TEXT NOT NULL DEFAULT '{}',
  stop_policy TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  cwd TEXT NOT NULL,
  argv_json TEXT NOT NULL,
  status TEXT NOT NULL,
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
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Store:
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
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, pid = ?, pgid = ?, started_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (SessionStatus.RUNNING.value, pid, pgid, session_id),
            )
        return self.get_session(session_id)

    def mark_stopping(self, session_id: str) -> SessionRecord:
        return self._set_status(session_id, SessionStatus.STOPPING)

    def mark_stopped(self, session_id: str) -> SessionRecord:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, ended_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (SessionStatus.STOPPED.value, session_id),
            )
        return self.get_session(session_id)

    def mark_failed(self, session_id: str, exit_code: int | None = None) -> SessionRecord:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, exit_code = ?, ended_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (SessionStatus.FAILED.value, exit_code, session_id),
            )
        return self.get_session(session_id)

    def mark_finished(self, session_id: str, exit_code: int) -> SessionRecord:
        status = SessionStatus.SUCCEEDED if exit_code == 0 else SessionStatus.FAILED
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, exit_code = ?, ended_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status.value, exit_code, session_id),
            )
        return self.get_session(session_id)

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
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status.value, session_id),
            )
        return self.get_session(session_id)


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
