from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from agentic_os.memory import BuiltSummary
from agentic_os.models import SessionRecord


REVIEW_STATUSES = ("pending", "approved", "rejected")

SCHEMA = """
CREATE TABLE IF NOT EXISTS session_summaries (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL UNIQUE,
  agent_id TEXT NOT NULL,
  status TEXT NOT NULL,
  one_liner TEXT NOT NULL,
  last_task TEXT NOT NULL,
  last_branch TEXT NOT NULL,
  stopped_at TEXT,
  stdout_lines INTEGER NOT NULL,
  stderr_lines INTEGER NOT NULL,
  error_lines INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memory_review_items (
  id TEXT PRIMARY KEY,
  summary_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  source TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS memory_review_items_active_summary_idx
ON memory_review_items(summary_id)
WHERE status != 'rejected';

CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  review_item_id TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
USING fts5(memory_id UNINDEXED, title, body, source);
"""


@dataclass(frozen=True)
class SessionSummaryRecord:
    id: str
    session_id: str
    agent_id: str
    status: str
    one_liner: str
    last_task: str
    last_branch: str
    stopped_at: str | None
    stdout_lines: int
    stderr_lines: int
    error_lines: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MemoryReviewItem:
    id: str
    summary_id: str
    session_id: str
    kind: str
    title: str
    body: str
    source: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    review_item_id: str
    session_id: str
    kind: str
    title: str
    body: str
    source: str
    created_at: str
    updated_at: str


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._init_fts(conn)
            if _has_fts(conn):
                _rebuild_fts(conn)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_summary(
        self,
        session: SessionRecord,
        summary: BuiltSummary,
    ) -> SessionSummaryRecord:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO session_summaries (
                  id, session_id, agent_id, status, one_liner, last_task, last_branch,
                  stopped_at, stdout_lines, stderr_lines, error_lines
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  agent_id = excluded.agent_id,
                  status = excluded.status,
                  one_liner = excluded.one_liner,
                  last_task = excluded.last_task,
                  last_branch = excluded.last_branch,
                  stopped_at = excluded.stopped_at,
                  stdout_lines = excluded.stdout_lines,
                  stderr_lines = excluded.stderr_lines,
                  error_lines = excluded.error_lines,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (
                    _new_id("sum"),
                    session.id,
                    session.agent_id,
                    session.status.value,
                    summary.one_liner,
                    summary.last_task,
                    summary.last_branch,
                    summary.stopped_at,
                    summary.stdout_lines,
                    summary.stderr_lines,
                    summary.error_lines,
                ),
            )
        return self.get_summary(session.id)

    def get_summary(self, session_id: str) -> SessionSummaryRecord:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM session_summaries WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return _summary_from_row(row)

    def create_review_item(self, summary: SessionSummaryRecord) -> MemoryReviewItem:
        with self.connect() as conn:
            active = conn.execute(
                """
                SELECT *
                FROM memory_review_items
                WHERE summary_id = ? AND status != 'rejected'
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (summary.id,),
            ).fetchone()
            if active is not None:
                return _review_item_from_row(active)

            conn.execute(
                """
                INSERT INTO memory_review_items (
                  id, summary_id, session_id, kind, title, body, source, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    _new_id("mri"),
                    summary.id,
                    summary.session_id,
                    "project_memory",
                    summary.one_liner,
                    _summary_body(summary),
                    _summary_source(summary),
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM memory_review_items
                WHERE summary_id = ? AND status != 'rejected'
                """,
                (summary.id,),
            ).fetchone()
        if row is None:
            raise KeyError(summary.id)
        return _review_item_from_row(row)

    def list_review_items(self) -> list[MemoryReviewItem]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM memory_review_items
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
        return [_review_item_from_row(row) for row in rows]

    def approve_review_item(self, item_id: str) -> MemoryRecord:
        with self.connect() as conn:
            item = _get_review_item_row(conn, item_id)
            if item["status"] != "pending":
                raise ValueError(f"Review item {item_id} is not pending")

            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO memories (
                  id, review_item_id, session_id, kind, title, body, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id("mem"),
                    item["id"],
                    item["session_id"],
                    item["kind"],
                    item["title"],
                    item["body"],
                    item["source"],
                ),
            )
            memory = _get_memory_by_review_item_row(conn, item_id)
            if cursor.rowcount == 1 and _has_fts(conn):
                conn.execute(
                    """
                    INSERT INTO memories_fts (memory_id, title, body, source)
                    VALUES (?, ?, ?, ?)
                    """,
                    (memory["id"], memory["title"], memory["body"], memory["source"]),
                )

            conn.execute(
                """
                UPDATE memory_review_items
                SET status = 'approved', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (item_id,),
            )
        return _memory_from_row(memory)

    def reject_review_item(self, item_id: str) -> MemoryReviewItem:
        with self.connect() as conn:
            item = _get_review_item_row(conn, item_id)
            if item["status"] != "pending":
                raise ValueError(f"Review item {item_id} is not pending")

            conn.execute(
                """
                UPDATE memory_review_items
                SET status = 'rejected', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (item_id,),
            )
        return self._get_review_item(item_id)

    def list_memories(self) -> list[MemoryRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM memories
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
        return [_memory_from_row(row) for row in rows]

    def search_memories(self, query: str) -> list[MemoryRecord]:
        normalized_query = query.strip()
        if not normalized_query:
            return []

        with self.connect() as conn:
            if _has_fts(conn):
                rows = conn.execute(
                    """
                    SELECT memories.*
                    FROM memories_fts
                    JOIN memories ON memories.id = memories_fts.memory_id
                    WHERE memories_fts MATCH ?
                    ORDER BY rank, memories.created_at ASC, memories.id ASC
                    """,
                    (_fts_query(normalized_query),),
                ).fetchall()
            else:
                like_query = f"%{normalized_query.lower()}%"
                rows = conn.execute(
                    """
                    SELECT *
                    FROM memories
                    WHERE lower(title) LIKE ?
                       OR lower(body) LIKE ?
                       OR lower(source) LIKE ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (like_query, like_query, like_query),
                ).fetchall()
        return [_memory_from_row(row) for row in rows]

    def _get_review_item(self, item_id: str) -> MemoryReviewItem:
        with self.connect() as conn:
            return _review_item_from_row(_get_review_item_row(conn, item_id))

    def _init_fts(self, conn: sqlite3.Connection) -> None:
        try:
            conn.executescript(FTS_SCHEMA)
        except sqlite3.OperationalError as exc:
            if "fts5" not in str(exc).lower():
                raise


def _summary_body(summary: SessionSummaryRecord) -> str:
    return summary.last_task or summary.one_liner


def _summary_source(summary: SessionSummaryRecord) -> str:
    return f"session:{summary.session_id}"


def _get_review_item_row(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM memory_review_items WHERE id = ?",
        (item_id,),
    ).fetchone()
    if row is None:
        raise KeyError(item_id)
    return row


def _get_memory_by_review_item_row(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM memories WHERE review_item_id = ?",
        (item_id,),
    ).fetchone()
    if row is None:
        raise KeyError(item_id)
    return row


def _summary_from_row(row: sqlite3.Row) -> SessionSummaryRecord:
    return SessionSummaryRecord(
        id=row["id"],
        session_id=row["session_id"],
        agent_id=row["agent_id"],
        status=row["status"],
        one_liner=row["one_liner"],
        last_task=row["last_task"],
        last_branch=row["last_branch"],
        stopped_at=row["stopped_at"],
        stdout_lines=row["stdout_lines"],
        stderr_lines=row["stderr_lines"],
        error_lines=row["error_lines"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _review_item_from_row(row: sqlite3.Row) -> MemoryReviewItem:
    return MemoryReviewItem(
        id=row["id"],
        summary_id=row["summary_id"],
        session_id=row["session_id"],
        kind=row["kind"],
        title=row["title"],
        body=row["body"],
        source=row["source"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _memory_from_row(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        review_item_id=row["review_item_id"],
        session_id=row["session_id"],
        kind=row["kind"],
        title=row["title"],
        body=row["body"],
        source=row["source"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _has_fts(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'memories_fts'
        """
    ).fetchone()
    return row is not None


def _rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM memories_fts")
    conn.execute(
        """
        INSERT INTO memories_fts (memory_id, title, body, source)
        SELECT id, title, body, source
        FROM memories
        ORDER BY created_at ASC, id ASC
        """
    )


def _fts_query(query: str) -> str:
    terms = [term.replace('"', '""') for term in query.split()]
    return " ".join(f'"{term}"' for term in terms)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
