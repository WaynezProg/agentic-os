from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from agentic_os.jsonio import atomic_write_json
from agentic_os.models import AttachStatus, EventRecord, SessionCreate, SessionRecord, SessionStatus


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
VALID_STATUS_VALUES = tuple(status.value for status in SessionStatus)
SESSION_STATUS_SQL = ", ".join(f"'{status.value}'" for status in SessionStatus)

SESSIONS_SCHEMA = f"""
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  cwd TEXT NOT NULL,
  argv_json TEXT NOT NULL,
  env_json TEXT NOT NULL DEFAULT '{{}}',
  status TEXT NOT NULL CHECK (status IN ({SESSION_STATUS_SQL})),
  pid INTEGER,
  pgid INTEGER,
  exit_code INTEGER,
  artifact_dir TEXT NOT NULL,
  stdout_log TEXT NOT NULL,
  stderr_log TEXT NOT NULL,
  summary_one_liner TEXT NOT NULL DEFAULT '',
  resolved_profile TEXT,
  resolved_provider TEXT,
  resolved_model TEXT,
  started_at TEXT,
  ended_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

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
  env_json TEXT NOT NULL DEFAULT '{{}}',
  status TEXT NOT NULL CHECK (status IN ({SESSION_STATUS_SQL})),
  pid INTEGER,
  pgid INTEGER,
  exit_code INTEGER,
  artifact_dir TEXT NOT NULL,
  stdout_log TEXT NOT NULL,
  stderr_log TEXT NOT NULL,
  summary_one_liner TEXT NOT NULL DEFAULT '',
  resolved_profile TEXT,
  resolved_provider TEXT,
  resolved_model TEXT,
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
            self._migrate_sessions_status_check(conn)
            self._migrate_sessions_env_json(conn)
            self._migrate_events_foreign_key(conn)
            self._migrate_sessions_attach_fields(conn)
            self._migrate_sessions_resolved_fields(conn)
            self._migrate_sessions_source_template_id(conn)
            self._migrate_sessions_workspace_path(conn)

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
                  id, agent_id, cwd, argv_json, env_json, status, artifact_dir,
                  stdout_log, stderr_log, summary_one_liner,
                  resolved_profile, resolved_provider, resolved_model,
                  source_template_id, workspace_path, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    session_id,
                    request.agent_id,
                    request.cwd,
                    json.dumps(request.argv),
                    json.dumps(request.env),
                    SessionStatus.QUEUED.value,
                    request.artifact_dir,
                    request.stdout_log,
                    request.stderr_log,
                    request.summary_one_liner,
                    request.resolved_profile,
                    request.resolved_provider,
                    request.resolved_model,
                    request.source_template_id,
                    request.workspace_path,
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
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def update_session_paths(
        self,
        session_id: str,
        *,
        artifact_dir: str,
        stdout_log: str,
        stderr_log: str,
    ) -> SessionRecord:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE sessions
                SET artifact_dir = ?, stdout_log = ?, stderr_log = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (artifact_dir, stdout_log, stderr_log, session_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(session_id)
        session = self.get_session(session_id)
        self.write_session_metadata(session.id)
        return session

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

    def record_root_exit(self, session_id: str, exit_code: int) -> SessionRecord:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE sessions
                SET exit_code = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ?
                """,
                (exit_code, session_id, SessionStatus.RUNNING.value),
            )
            if cursor.rowcount != 1:
                _raise_transition_error(conn, session_id, SessionStatus.RUNNING)
        session = self.get_session(session_id)
        self.write_session_metadata(session.id)
        return session

    def repair_running(self, session_id: str) -> SessionRecord:
        repairable_statuses = (
            SessionStatus.SUCCEEDED,
            SessionStatus.FAILED,
            SessionStatus.STOPPED,
        )
        placeholders = ", ".join("?" for _ in repairable_statuses)
        with self.connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE sessions
                SET status = ?, ended_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ({placeholders})
                """,
                (
                    SessionStatus.RUNNING.value,
                    session_id,
                    *(status.value for status in repairable_statuses),
                ),
            )
            if cursor.rowcount != 1:
                _raise_transition_error(conn, session_id, SessionStatus.RUNNING)
        session = self.get_session(session_id)
        self.write_session_metadata(session.id)
        return session

    def update_session_attach(
        self,
        session_id: str,
        *,
        external_session_id: str | None = None,
        attachable: bool | None = None,
        attach_status: AttachStatus | None = None,
    ) -> SessionRecord:
        assignments: list[str] = []
        values: list[Any] = []
        if external_session_id is not None:
            assignments.append("external_session_id = ?")
            values.append(external_session_id)
        if attachable is not None:
            assignments.append("attachable = ?")
            values.append(1 if attachable else 0)
        if attach_status is not None:
            assignments.append("attach_status = ?")
            values.append(attach_status)
        if not assignments:
            return self.get_session(session_id)
        with self.connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE sessions
                SET {", ".join(assignments)}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*values, session_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(session_id)
        session = self.get_session(session_id)
        self.write_session_metadata(session.id)
        return session

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

    def write_session_metadata(self, session_id: str) -> None:
        session = self.get_session(session_id)
        path = _session_metadata_path(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = session.model_dump(mode="json")
        payload["session_dir"] = str(path.parent)
        payload.pop("env", None)
        atomic_write_json(path, payload)

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
        session = self.get_session(session_id)
        self.write_session_metadata(session.id)
        return session

    def _migrate_sessions_status_check(self, conn: sqlite3.Connection) -> None:
        if _sessions_has_status_check(conn):
            return

        conn.execute("ALTER TABLE events RENAME TO events_before_sessions_status_migration")
        conn.execute("ALTER TABLE sessions RENAME TO sessions_without_status_check")
        conn.execute(SESSIONS_SCHEMA)

        valid_status_placeholders = ", ".join("?" for _ in VALID_STATUS_VALUES)
        env_json_projection = (
            "env_json"
            if _table_has_column(conn, "sessions_without_status_check", "env_json")
            else "'{}'"
        )
        # Legacy rows with invalid statuses cannot satisfy the rebuilt CHECK constraint.
        conn.execute(
            f"""
                INSERT INTO sessions (
                  id, agent_id, cwd, argv_json, env_json, status, pid, pgid, exit_code,
                  artifact_dir, stdout_log, stderr_log, summary_one_liner,
                  resolved_profile, resolved_provider, resolved_model,
                  started_at, ended_at, updated_at
                )
                SELECT
                  id, agent_id, cwd, argv_json, {env_json_projection}, status, pid, pgid, exit_code,
                  artifact_dir, stdout_log, stderr_log, summary_one_liner,
                  NULL, NULL, NULL,
                  started_at, ended_at, updated_at
                FROM sessions_without_status_check
                WHERE status IN ({valid_status_placeholders})
                """,
            VALID_STATUS_VALUES,
        )

        conn.execute(EVENTS_SCHEMA)
        conn.execute(
            """
            INSERT INTO events (id, session_id, event_type, message, metadata_json, created_at)
            SELECT
              events_before_sessions_status_migration.id,
              events_before_sessions_status_migration.session_id,
              events_before_sessions_status_migration.event_type,
              events_before_sessions_status_migration.message,
              events_before_sessions_status_migration.metadata_json,
              events_before_sessions_status_migration.created_at
            FROM events_before_sessions_status_migration
            WHERE EXISTS (
              SELECT 1
              FROM sessions
              WHERE sessions.id = events_before_sessions_status_migration.session_id
            )
            """
        )
        conn.execute("DROP TABLE events_before_sessions_status_migration")
        conn.execute("DROP TABLE sessions_without_status_check")

    def _migrate_sessions_env_json(self, conn: sqlite3.Connection) -> None:
        if _table_has_column(conn, "sessions", "env_json"):
            return
        conn.execute("ALTER TABLE sessions ADD COLUMN env_json TEXT NOT NULL DEFAULT '{}'")

    def _migrate_sessions_attach_fields(self, conn: sqlite3.Connection) -> None:
        if _table_has_column(conn, "sessions", "external_session_id"):
            return
        conn.execute("ALTER TABLE sessions ADD COLUMN external_session_id TEXT")
        conn.execute("ALTER TABLE sessions ADD COLUMN attachable INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE sessions ADD COLUMN attach_status TEXT NOT NULL DEFAULT 'none'")

    def _migrate_sessions_resolved_fields(self, conn: sqlite3.Connection) -> None:
        if _table_has_column(conn, "sessions", "resolved_profile"):
            return
        conn.execute("ALTER TABLE sessions ADD COLUMN resolved_profile TEXT")
        conn.execute("ALTER TABLE sessions ADD COLUMN resolved_provider TEXT")
        conn.execute("ALTER TABLE sessions ADD COLUMN resolved_model TEXT")

    def _migrate_sessions_source_template_id(self, conn: sqlite3.Connection) -> None:
        if _table_has_column(conn, "sessions", "source_template_id"):
            return
        conn.execute("ALTER TABLE sessions ADD COLUMN source_template_id TEXT")

    def _migrate_sessions_workspace_path(self, conn: sqlite3.Connection) -> None:
        if _table_has_column(conn, "sessions", "workspace_path"):
            return
        conn.execute("ALTER TABLE sessions ADD COLUMN workspace_path TEXT")

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
        env=json.loads(row["env_json"]),
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
        external_session_id=row["external_session_id"],
        attachable=bool(row["attachable"]),
        attach_status=row["attach_status"],
        resolved_profile=row["resolved_profile"],
        resolved_provider=row["resolved_provider"],
        resolved_model=row["resolved_model"],
        source_template_id=row["source_template_id"],
        workspace_path=row["workspace_path"],
    )


def _session_metadata_path(session: SessionRecord) -> Path:
    return Path(session.stdout_log).parent / "session.json"


def _table_has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    return any(row[1] == column_name for row in conn.execute(f"PRAGMA table_info({table_name})"))


def _events_has_session_foreign_key(conn: sqlite3.Connection) -> bool:
    foreign_keys = conn.execute("PRAGMA foreign_key_list(events)").fetchall()
    return any(row[2] == "sessions" and row[3] == "session_id" for row in foreign_keys)


def _sessions_has_status_check(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'sessions'"
    ).fetchone()
    if row is None:
        return False

    schema_sql = " ".join(row["sql"].lower().split())
    return "check" in schema_sql and all(
        f"'{status_value}'" in schema_sql for status_value in VALID_STATUS_VALUES
    )


def _raise_transition_error(
    conn: sqlite3.Connection, session_id: str, status: SessionStatus
) -> None:
    row = conn.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise KeyError(session_id)

    current_status = SessionStatus(row["status"])
    raise ValueError(
        f"Cannot transition session {session_id} from {current_status.value} to {status.value}"
    )
