from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import SplitResult, urlsplit, urlunsplit


Decision = Literal["allow", "deny", "approval_required"]
Transport = Literal["stdio", "http", "sse"]

_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]+")
_SECRET_KEY_PATTERN = re.compile(
    r"(?i)(token|secret|password|passwd|apikey|api_key|api-key|authorization|bearer)"
)
_KEY_VALUE_SECRET_PATTERN = re.compile(
    r"(?i)(token|secret|password|passwd|apikey|api_key|api-key|authorization|bearer)=([^\s&]+)"
)
_WHITESPACE_SECRET_FLAG_PATTERN = re.compile(
    r"(?i)(--(?:token|secret|password|passwd|api-key|api_key|authorization|bearer))\s+([^\s&]+)"
)
_AUTHORIZATION_BEARER_PATTERN = re.compile(r"(?i)(authorization:\s*bearer)\s+([^\s&]+)")
_SECRET_FLAGS = {
    "--token",
    "--secret",
    "--password",
    "--passwd",
    "--api-key",
    "--api_key",
    "--authorization",
    "--bearer",
}
_WRITE_TOOL_NAMES = {
    "write",
    "edit",
    "apply_patch",
    "exec",
    "spawn",
    "subprocess",
    "mcp.write",
    "browser.click",
    "browser.type",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'local',
  entrypoint TEXT NOT NULL DEFAULT '',
  tags_json TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mcp_servers (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  transport TEXT NOT NULL CHECK (transport IN ('stdio', 'http', 'sse')),
  command_preview_json TEXT NOT NULL DEFAULT '[]',
  url TEXT,
  env_keys_json TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_policies (
  agent_id TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 1,
  readonly INTEGER NOT NULL DEFAULT 0,
  allowed_skill_ids_json TEXT NOT NULL DEFAULT '[]',
  allowed_mcp_server_ids_json TEXT NOT NULL DEFAULT '[]',
  allowed_tool_names_json TEXT NOT NULL DEFAULT '[]',
  approval_required_tool_names_json TEXT NOT NULL DEFAULT '[]',
  allowed_model_ids_json TEXT NOT NULL DEFAULT '[]',
  cwd_roots_json TEXT NOT NULL DEFAULT '[]',
  rate_limit_per_minute INTEGER NOT NULL DEFAULT 60,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True)
class SkillUpsert:
    label: str
    description: str = ""
    source: str = "local"
    entrypoint: str = ""
    tags: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass(frozen=True)
class SkillRecord:
    id: str
    label: str
    description: str
    source: str
    entrypoint: str
    tags: list[str]
    enabled: bool
    deprecated: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class McpServerUpsert:
    label: str
    description: str = ""
    transport: Transport = "stdio"
    command_preview: list[str] = field(default_factory=list)
    url: str | None = None
    env_keys: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass(frozen=True)
class McpServerRecord:
    id: str
    label: str
    description: str
    transport: str
    command_preview: list[str]
    url: str | None
    env_keys: list[str]
    enabled: bool
    deprecated: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PolicyUpsert:
    enabled: bool = True
    readonly: bool = False
    allowed_skill_ids: list[str] = field(default_factory=list)
    allowed_mcp_server_ids: list[str] = field(default_factory=list)
    allowed_tool_names: list[str] = field(default_factory=list)
    approval_required_tool_names: list[str] = field(default_factory=list)
    allowed_model_ids: list[str] = field(default_factory=list)
    cwd_roots: list[str] = field(default_factory=list)
    rate_limit_per_minute: int = 60


@dataclass(frozen=True)
class PolicyRecord:
    agent_id: str
    enabled: bool
    deprecated: bool
    readonly: bool
    allowed_skill_ids: list[str]
    allowed_mcp_server_ids: list[str]
    allowed_tool_names: list[str]
    approval_required_tool_names: list[str]
    allowed_model_ids: list[str]
    cwd_roots: list[str]
    rate_limit_per_minute: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PolicyEvaluationRequest:
    agent_id: str
    skill_id: str | None = None
    mcp_server_id: str | None = None
    tool_name: str | None = None
    model_id: str | None = None
    cwd: str | None = None


@dataclass(frozen=True)
class PolicyEvaluationResult:
    agent_id: str
    decision: Decision
    reason: str
    readonly: bool
    rate_limit_per_minute: int | None
    warnings: list[str] = field(default_factory=list)


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column_sql: str) -> None:
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_sql}")
    except sqlite3.OperationalError:
        pass  # column already exists


class ControlPlaneStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            _add_column_if_missing(conn, "skills", "deprecated INTEGER NOT NULL DEFAULT 0")
            _add_column_if_missing(conn, "mcp_servers", "deprecated INTEGER NOT NULL DEFAULT 0")
            _add_column_if_missing(conn, "agent_policies", "deprecated INTEGER NOT NULL DEFAULT 0")

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_skill(self, skill_id: str, request: SkillUpsert) -> SkillRecord:
        _validate_id(skill_id)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO skills (
                  id, label, description, source, entrypoint, tags_json, enabled, deprecated
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(id) DO UPDATE SET
                  label = excluded.label,
                  description = excluded.description,
                  source = excluded.source,
                  entrypoint = excluded.entrypoint,
                  tags_json = excluded.tags_json,
                  enabled = excluded.enabled,
                  deprecated = 0,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (
                    skill_id,
                    request.label,
                    request.description,
                    request.source,
                    request.entrypoint,
                    _json_list(request.tags),
                    int(request.enabled),
                ),
            )
        return self.get_skill(skill_id)

    def list_skills(self) -> list[SkillRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM skills ORDER BY id ASC").fetchall()
        return [_skill_from_row(row) for row in rows]

    def get_skill(self, skill_id: str) -> SkillRecord:
        _validate_id(skill_id)
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
        if row is None:
            raise KeyError(skill_id)
        return _skill_from_row(row)

    def disable_skill(self, skill_id: str) -> SkillRecord:
        _validate_id(skill_id)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE skills
                SET enabled = 0, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (skill_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(skill_id)
        return self.get_skill(skill_id)

    def deprecate_skill(self, skill_id: str) -> SkillRecord:
        _validate_id(skill_id)
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE skills SET deprecated = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (skill_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(skill_id)
        return self.get_skill(skill_id)

    def upsert_mcp_server(self, server_id: str, request: McpServerUpsert) -> McpServerRecord:
        _validate_id(server_id)
        _validate_transport(request.transport)
        command_preview = _redact_command_preview(request.command_preview)
        url = _redact_url(request.url) if request.url else None
        env_keys = _normalize_env_keys(request.env_keys)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO mcp_servers (
                  id, label, description, transport, command_preview_json,
                  url, env_keys_json, enabled, deprecated
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(id) DO UPDATE SET
                  label = excluded.label,
                  description = excluded.description,
                  transport = excluded.transport,
                  command_preview_json = excluded.command_preview_json,
                  url = excluded.url,
                  env_keys_json = excluded.env_keys_json,
                  enabled = excluded.enabled,
                  deprecated = 0,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (
                    server_id,
                    request.label,
                    request.description,
                    request.transport,
                    _json_list(command_preview),
                    url,
                    _json_list(env_keys),
                    int(request.enabled),
                ),
            )
        return self.get_mcp_server(server_id)

    def list_mcp_servers(self) -> list[McpServerRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM mcp_servers ORDER BY id ASC").fetchall()
        return [_mcp_from_row(row) for row in rows]

    def get_mcp_server(self, server_id: str) -> McpServerRecord:
        _validate_id(server_id)
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
        if row is None:
            raise KeyError(server_id)
        return _mcp_from_row(row)

    def disable_mcp_server(self, server_id: str) -> McpServerRecord:
        _validate_id(server_id)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE mcp_servers
                SET enabled = 0, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (server_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(server_id)
        return self.get_mcp_server(server_id)

    def deprecate_mcp_server(self, server_id: str) -> McpServerRecord:
        _validate_id(server_id)
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE mcp_servers SET deprecated = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (server_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(server_id)
        return self.get_mcp_server(server_id)

    def upsert_policy(self, agent_id: str, request: PolicyUpsert) -> PolicyRecord:
        _validate_id(agent_id)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_policies (
                  agent_id, enabled, readonly, allowed_skill_ids_json,
                  allowed_mcp_server_ids_json, allowed_tool_names_json,
                  approval_required_tool_names_json, allowed_model_ids_json,
                  cwd_roots_json, rate_limit_per_minute, deprecated
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(agent_id) DO UPDATE SET
                  enabled = excluded.enabled,
                  readonly = excluded.readonly,
                  allowed_skill_ids_json = excluded.allowed_skill_ids_json,
                  allowed_mcp_server_ids_json = excluded.allowed_mcp_server_ids_json,
                  allowed_tool_names_json = excluded.allowed_tool_names_json,
                  approval_required_tool_names_json = excluded.approval_required_tool_names_json,
                  allowed_model_ids_json = excluded.allowed_model_ids_json,
                  cwd_roots_json = excluded.cwd_roots_json,
                  rate_limit_per_minute = excluded.rate_limit_per_minute,
                  deprecated = 0,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (
                    agent_id,
                    int(request.enabled),
                    int(request.readonly),
                    _json_list(request.allowed_skill_ids),
                    _json_list(request.allowed_mcp_server_ids),
                    _json_list(request.allowed_tool_names),
                    _json_list(request.approval_required_tool_names),
                    _json_list(request.allowed_model_ids),
                    _json_list(request.cwd_roots),
                    request.rate_limit_per_minute,
                ),
            )
        return self.get_policy(agent_id)

    def list_policies(self) -> list[PolicyRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM agent_policies ORDER BY agent_id ASC").fetchall()
        return [_policy_from_row(row) for row in rows]

    def get_policy(self, agent_id: str) -> PolicyRecord:
        _validate_id(agent_id)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_policies WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        if row is None:
            raise KeyError(agent_id)
        return _policy_from_row(row)

    def deprecate_policy(self, agent_id: str) -> PolicyRecord:
        _validate_id(agent_id)
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE agent_policies SET deprecated = 1, updated_at = CURRENT_TIMESTAMP WHERE agent_id = ?",
                (agent_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(agent_id)
        return self.get_policy(agent_id)

    def evaluate_policy(self, request: PolicyEvaluationRequest) -> PolicyEvaluationResult:
        _validate_id(request.agent_id)
        try:
            policy = self.get_policy(request.agent_id)
        except KeyError:
            return _decision(
                request.agent_id, "deny", f"no policy configured for {request.agent_id}"
            )

        if not policy.enabled:
            return _decision(
                request.agent_id,
                "deny",
                f"policy disabled for {request.agent_id}",
                policy,
            )

        warnings: list[str] = []
        if policy.deprecated:
            warnings.append(f"policy for {request.agent_id} is deprecated")

        if request.skill_id:
            skill_result, skill_warnings = self._evaluate_skill(request.skill_id, policy)
            warnings.extend(skill_warnings)
            if skill_result is not None:
                return PolicyEvaluationResult(
                    agent_id=skill_result.agent_id,
                    decision=skill_result.decision,
                    reason=skill_result.reason,
                    readonly=skill_result.readonly,
                    rate_limit_per_minute=skill_result.rate_limit_per_minute,
                    warnings=warnings,
                )

        if request.mcp_server_id:
            mcp_result, mcp_warnings = self._evaluate_mcp(request.mcp_server_id, policy)
            warnings.extend(mcp_warnings)
            if mcp_result is not None:
                return PolicyEvaluationResult(
                    agent_id=mcp_result.agent_id,
                    decision=mcp_result.decision,
                    reason=mcp_result.reason,
                    readonly=mcp_result.readonly,
                    rate_limit_per_minute=mcp_result.rate_limit_per_minute,
                    warnings=warnings,
                )

        if request.model_id and not _is_allowed(policy.allowed_model_ids, request.model_id):
            return _decision(
                request.agent_id,
                "deny",
                f"model {request.model_id} is not allowed for {request.agent_id}",
                policy,
                warnings=warnings,
            )

        if request.tool_name and not _is_allowed(policy.allowed_tool_names, request.tool_name):
            return _decision(
                request.agent_id,
                "deny",
                f"tool {request.tool_name} is not allowed for {request.agent_id}",
                policy,
                warnings=warnings,
            )

        if request.cwd and not _cwd_allowed(request.cwd, policy.cwd_roots):
            return _decision(
                request.agent_id,
                "deny",
                f"cwd is outside allowed roots for {request.agent_id}",
                policy,
                warnings=warnings,
            )

        if request.tool_name:
            if policy.readonly and request.tool_name in _WRITE_TOOL_NAMES:
                return _decision(
                    request.agent_id,
                    "deny",
                    f"readonly policy denies {request.tool_name}",
                    policy,
                    warnings=warnings,
                )

        if policy.rate_limit_per_minute < 1:
            return _decision(
                request.agent_id,
                "deny",
                "rate_limit_per_minute must be at least 1",
                policy,
                warnings=warnings,
            )

        if request.tool_name:
            if _is_allowed(policy.approval_required_tool_names, request.tool_name):
                return _decision(
                    request.agent_id,
                    "approval_required",
                    f"tool {request.tool_name} requires approval",
                    policy,
                    warnings=warnings,
                )

        return PolicyEvaluationResult(
            agent_id=request.agent_id,
            decision="allow",
            reason="policy allowed request",
            readonly=policy.readonly,
            rate_limit_per_minute=policy.rate_limit_per_minute,
            warnings=warnings,
        )

    def _evaluate_skill(
        self,
        skill_id: str,
        policy: PolicyRecord,
    ) -> tuple[PolicyEvaluationResult | None, list[str]]:
        warnings: list[str] = []
        try:
            skill = self.get_skill(skill_id)
        except KeyError:
            return _decision(policy.agent_id, "deny", f"unknown skill {skill_id}", policy), []
        if not skill.enabled:
            return _decision(policy.agent_id, "deny", f"skill {skill_id} is disabled", policy), []
        if not _is_allowed(policy.allowed_skill_ids, skill_id):
            return (
                _decision(
                    policy.agent_id,
                    "deny",
                    f"skill {skill_id} is not allowed for {policy.agent_id}",
                    policy,
                ),
                [],
            )
        if skill.deprecated:
            warnings.append(f"skill {skill_id} is deprecated")
        return None, warnings

    def _evaluate_mcp(
        self,
        server_id: str,
        policy: PolicyRecord,
    ) -> tuple[PolicyEvaluationResult | None, list[str]]:
        warnings: list[str] = []
        try:
            server = self.get_mcp_server(server_id)
        except KeyError:
            return _decision(policy.agent_id, "deny", f"unknown mcp server {server_id}", policy), []
        if not server.enabled:
            return (
                _decision(policy.agent_id, "deny", f"mcp server {server_id} is disabled", policy),
                [],
            )
        if not _is_allowed(policy.allowed_mcp_server_ids, server_id):
            return (
                _decision(
                    policy.agent_id,
                    "deny",
                    f"mcp server {server_id} is not allowed for {policy.agent_id}",
                    policy,
                ),
                [],
            )
        if server.deprecated:
            warnings.append(f"mcp server {server_id} is deprecated")
        return None, warnings


def _decision(
    agent_id: str,
    decision: Decision,
    reason: str,
    policy: PolicyRecord | None = None,
    warnings: list[str] | None = None,
) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        agent_id=agent_id,
        decision=decision,
        reason=reason,
        readonly=policy.readonly if policy else False,
        rate_limit_per_minute=policy.rate_limit_per_minute if policy else None,
        warnings=warnings or [],
    )


def _is_allowed(allowed_values: list[str], requested_value: str) -> bool:
    return "*" in allowed_values or requested_value in allowed_values


def _cwd_allowed(cwd: str, roots: list[str]) -> bool:
    if not roots:
        return False
    cwd_path = Path(cwd).expanduser().resolve(strict=False)
    for root in roots:
        root_path = Path(root).expanduser().resolve(strict=False)
        if cwd_path == root_path or root_path in cwd_path.parents:
            return True
    return False


def _redact_command_preview(command_preview: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for part in command_preview:
        text = str(part)
        lower = text.lower()
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            continue
        if lower in _SECRET_FLAGS:
            redacted.append(text)
            redact_next = True
            continue
        redacted.append(_redact_text(text))
    return redacted


def _redact_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.username or parts.password:
        hostname = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        netloc = f"[REDACTED]@{hostname}{port}"
        parts = SplitResult(parts.scheme, netloc, parts.path, parts.query, parts.fragment)
    return _redact_text(urlunsplit(parts))


def _normalize_env_keys(env_keys: list[str]) -> list[str]:
    keys: list[str] = []
    for raw_key in env_keys:
        key = str(raw_key).split("=", 1)[0].strip()
        if key:
            keys.append(key)
    return keys


def _redact_text(value: str) -> str:
    if _SECRET_KEY_PATTERN.fullmatch(value):
        return "[REDACTED]"
    redacted = _KEY_VALUE_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    redacted = _WHITESPACE_SECRET_FLAG_PATTERN.sub(
        lambda match: f"{match.group(1)} [REDACTED]",
        redacted,
    )
    return _AUTHORIZATION_BEARER_PATTERN.sub(
        lambda match: f"{match.group(1)} [REDACTED]",
        redacted,
    )


def _json_list(values: list[str]) -> str:
    return json.dumps([str(value) for value in values])


def _load_json_list(value: str) -> list[str]:
    data = json.loads(value)
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]


def _validate_id(value: str) -> None:
    if not _ID_PATTERN.fullmatch(value):
        raise ValueError("unsafe path id")


def _validate_transport(value: str) -> None:
    if value not in {"stdio", "http", "sse"}:
        raise ValueError(f"unsupported MCP transport: {value}")


def _skill_from_row(row: sqlite3.Row) -> SkillRecord:
    return SkillRecord(
        id=row["id"],
        label=row["label"],
        description=row["description"],
        source=row["source"],
        entrypoint=row["entrypoint"],
        tags=_load_json_list(row["tags_json"]),
        enabled=bool(row["enabled"]),
        deprecated=bool(row["deprecated"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _mcp_from_row(row: sqlite3.Row) -> McpServerRecord:
    return McpServerRecord(
        id=row["id"],
        label=row["label"],
        description=row["description"],
        transport=row["transport"],
        command_preview=_load_json_list(row["command_preview_json"]),
        url=row["url"],
        env_keys=_load_json_list(row["env_keys_json"]),
        enabled=bool(row["enabled"]),
        deprecated=bool(row["deprecated"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _policy_from_row(row: sqlite3.Row) -> PolicyRecord:
    return PolicyRecord(
        agent_id=row["agent_id"],
        enabled=bool(row["enabled"]),
        deprecated=bool(row["deprecated"]),
        readonly=bool(row["readonly"]),
        allowed_skill_ids=_load_json_list(row["allowed_skill_ids_json"]),
        allowed_mcp_server_ids=_load_json_list(row["allowed_mcp_server_ids_json"]),
        allowed_tool_names=_load_json_list(row["allowed_tool_names_json"]),
        approval_required_tool_names=_load_json_list(row["approval_required_tool_names_json"]),
        allowed_model_ids=_load_json_list(row["allowed_model_ids_json"]),
        cwd_roots=_load_json_list(row["cwd_roots_json"]),
        rate_limit_per_minute=row["rate_limit_per_minute"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
