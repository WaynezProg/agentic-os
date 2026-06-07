from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUN_TEMPLATES_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_templates (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  harness_id TEXT NOT NULL,
  profile_name TEXT,
  cwd TEXT NOT NULL,
  message_template TEXT NOT NULL,
  required_variables_json TEXT NOT NULL DEFAULT '[]',
  approval_policy_hint TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True)
class RunTemplateInput:
    name: str
    harness_id: str
    cwd: str
    message_template: str
    profile_name: str | None = None
    required_variables: list[str] | None = None
    approval_policy_hint: str = ""


@dataclass(frozen=True)
class RunTemplateRecord:
    id: str
    name: str
    harness_id: str
    cwd: str
    message_template: str
    profile_name: str | None
    required_variables: list[str]
    approval_policy_hint: str
    created_at: str
    updated_at: str


class RunTemplateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(RUN_TEMPLATES_SCHEMA)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_templates(self, *, cwd: str | None = None) -> list[RunTemplateRecord]:
        query = "SELECT * FROM run_templates"
        params: tuple[Any, ...] = ()
        if cwd is not None:
            query += " WHERE cwd = ?"
            params = (_resolve_cwd(cwd),)
        query += " ORDER BY updated_at DESC, name ASC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_template_from_row(row) for row in rows]

    def get(self, template_id: str) -> RunTemplateRecord:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_templates WHERE id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            raise KeyError(template_id)
        return _template_from_row(row)

    def create(self, request: RunTemplateInput) -> RunTemplateRecord:
        template_id = f"rt_{uuid.uuid4().hex}"
        now = _now_iso()
        cwd = _resolve_cwd(request.cwd)
        variables = request.required_variables or []
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO run_templates (
                  id, name, harness_id, profile_name, cwd, message_template,
                  required_variables_json, approval_policy_hint, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    request.name,
                    request.harness_id,
                    request.profile_name,
                    cwd,
                    request.message_template,
                    json.dumps(variables),
                    request.approval_policy_hint,
                    now,
                    now,
                ),
            )
        return self.get(template_id)

    def update(self, template_id: str, request: RunTemplateInput) -> RunTemplateRecord:
        _ = self.get(template_id)
        cwd = _resolve_cwd(request.cwd)
        variables = request.required_variables or []
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE run_templates
                SET name = ?, harness_id = ?, profile_name = ?, cwd = ?,
                    message_template = ?, required_variables_json = ?,
                    approval_policy_hint = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    request.name,
                    request.harness_id,
                    request.profile_name,
                    cwd,
                    request.message_template,
                    json.dumps(variables),
                    request.approval_policy_hint,
                    _now_iso(),
                    template_id,
                ),
            )
        return self.get(template_id)

    def delete(self, template_id: str) -> None:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM run_templates WHERE id = ?", (template_id,))
        if cursor.rowcount == 0:
            raise KeyError(template_id)


def _resolve_cwd(cwd: str | Path) -> str:
    resolved = Path(cwd).expanduser().resolve()
    if not resolved.exists():
        raise ValueError(f"cwd does not exist: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"cwd is not a directory: {resolved}")
    return str(resolved)


def _template_from_row(row: sqlite3.Row) -> RunTemplateRecord:
    variables_raw = row["required_variables_json"]
    variables = json.loads(variables_raw) if variables_raw else []
    if not isinstance(variables, list):
        variables = []
    return RunTemplateRecord(
        id=row["id"],
        name=row["name"],
        harness_id=row["harness_id"],
        profile_name=row["profile_name"],
        cwd=row["cwd"],
        message_template=row["message_template"],
        required_variables=[str(item) for item in variables],
        approval_policy_hint=row["approval_policy_hint"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def render_message_template(template: str, variables: dict[str, str]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered
