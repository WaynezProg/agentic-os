"""Workflow Surface Catalog scanner.

Scans harness-specific directories across user/project/local scopes,
classifies surfaces (hooks, commands, skills, subagents, mcp_servers,
permissions), and provides merged/diff views.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_os.control_plane import _redact_value

# Scope paths by harness type
_HARNESS_SCOPES = {
    "claude": {
        "user": ".claude",
        "project": ".claude",
        "local": ".claude/local",
    },
    "codex": {
        "user": ".codex",
        "project": ".codex",
        "local": ".codex/local",
    },
    "opencode": {
        "user": ".config/opencode",
        "project": ".opencode",
        "local": ".opencode/local",
    },
    "qwen": {
        "user": ".qwen",
        "project": ".qwen",
        "local": ".qwen/local",
    },
    "openclaw": {
        "user": ".openclaw",
        "project": ".openclaw",
        "local": ".openclaw/local",
    },
    "hermes": {
        "user": ".hermes",
        "project": ".hermes",
        "local": ".hermes/local",
    },
    "cursor": {
        "user": ".cursor",
        "project": ".cursor",
        "local": ".cursor/local",
    },
}

SUPPORTED_HARNESSES = tuple(_HARNESS_SCOPES.keys())
_JSON_SETTINGS_FILES = {
    "claude": "settings.json",
    "qwen": "settings.json",
    "opencode": "config.json",
    "cursor": "cli-config.json",
}
_TOML_CONFIG_HARNESSES = frozenset({"openclaw", "hermes", "codex"})
_CURSOR_EXTRA_JSON_FILES = ("mcp.json", "hooks.json")
VALID_TYPES = ("hook", "command", "skill", "subagent", "mcp_server", "permission")


@dataclass(frozen=True)
class SurfaceRecord:
    id: str
    type: str
    name: str
    scope: str
    harness: str
    source: str
    enabled: bool
    metadata: dict[str, Any] = field(default_factory=dict)
    overridden_by: str | None = None
    overrides: str | None = None


def scan(harness: str, cwd: str | None = None, home_dir: Path | None = None) -> list[SurfaceRecord]:
    """Scan all scopes for a harness and return classified surface records."""
    if harness not in _HARNESS_SCOPES:
        return []

    records: list[SurfaceRecord] = []
    scopes = _HARNESS_SCOPES[harness]
    cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
    base_home = home_dir or Path.home()

    # Scan user scope
    user_dir = base_home / scopes["user"]
    records.extend(_scan_scope(harness, user_dir, "user"))

    # Scan project scope
    project_rel = scopes["project"]
    project_dir = cwd_path / project_rel
    records.extend(_scan_scope(harness, project_dir, "project"))

    # Scan local scope
    local_rel = scopes["local"]
    local_dir = cwd_path / local_rel
    records.extend(_scan_scope(harness, local_dir, "local"))

    return records


def merge(records: list[SurfaceRecord]) -> list[SurfaceRecord]:
    """Merge records across scopes, marking overrides.

    Priority: local > project > user.
    """
    by_key: dict[str, list[SurfaceRecord]] = {}
    for r in records:
        key = f"{r.type}:{r.name}"
        by_key.setdefault(key, []).append(r)

    result: list[SurfaceRecord] = []
    for key, group in by_key.items():
        # Sort by scope priority (local highest)
        scope_order = {"local": 3, "project": 2, "user": 1, "managed": 0}
        group.sort(key=lambda r: scope_order.get(r.scope, 0), reverse=True)
        winner = group[0]
        if len(group) > 1:
            # Winner overrides the rest
            overridden = group[1:]
            winner = winner.__class__(
                id=winner.id,
                type=winner.type,
                name=winner.name,
                scope=winner.scope,
                harness=winner.harness,
                source=winner.source,
                enabled=winner.enabled,
                metadata=winner.metadata,
                overrides=",".join(r.scope for r in overridden),
            )
            for r in overridden:
                result.append(
                    r.__class__(
                        id=r.id,
                        type=r.type,
                        name=r.name,
                        scope=r.scope,
                        harness=r.harness,
                        source=r.source,
                        enabled=r.enabled,
                        metadata=r.metadata,
                        overridden_by=winner.scope,
                    )
                )
        result.append(winner)

    return result


def diff(
    records_a: list[SurfaceRecord], records_b: list[SurfaceRecord]
) -> dict[str, list[dict[str, Any]]]:
    """Compare two surface lists and return added/removed/modified."""
    key_a = {f"{r.type}:{r.name}": r for r in records_a}
    key_b = {f"{r.type}:{r.name}": r for r in records_b}

    added = []
    removed = []
    modified = []

    for key, r in key_b.items():
        if key not in key_a:
            added.append(_surface_dict(r))
        elif _surface_key_diff(key_a[key], r):
            modified.append(
                {
                    "surface": _surface_dict(r),
                    "previous": _surface_dict(key_a[key]),
                }
            )

    for key, r in key_a.items():
        if key not in key_b:
            removed.append(_surface_dict(r))

    return {"added": added, "removed": removed, "modified": modified}


def _surface_dict(r: SurfaceRecord) -> dict[str, Any]:
    return {
        "id": r.id,
        "type": r.type,
        "name": r.name,
        "scope": r.scope,
        "harness": r.harness,
        "source": r.source,
        "enabled": r.enabled,
        "metadata": r.metadata,
    }


def _surface_key_diff(a: SurfaceRecord, b: SurfaceRecord) -> bool:
    return a.source != b.source or a.enabled != b.enabled or a.metadata != b.metadata


def _scan_scope(
    harness: str,
    scope_dir: Path,
    scope_name: str,
) -> list[SurfaceRecord]:
    records: list[SurfaceRecord] = []

    base = scope_dir

    # Read settings.json / config file
    if harness in _JSON_SETTINGS_FILES:
        settings_path = base / _JSON_SETTINGS_FILES[harness]
        if settings_path.exists():
            records.extend(_scan_claude_settings(settings_path, scope_name, harness))
    elif harness in _TOML_CONFIG_HARNESSES:
        config_path = base / "config.toml"
        if config_path.exists():
            records.extend(_scan_toml_config(config_path, scope_name, harness))

    if harness == "cursor":
        for filename in _CURSOR_EXTRA_JSON_FILES:
            extra_path = base / filename
            if not extra_path.exists():
                continue
            if filename == "mcp.json":
                records.extend(_scan_claude_settings(extra_path, scope_name, harness))
            elif filename == "hooks.json":
                records.extend(_scan_cursor_hooks(extra_path, scope_name, harness))

    # Scan commands/
    commands_dir = base / "commands"
    if commands_dir.is_dir():
        records.extend(_scan_commands(commands_dir, scope_name, harness))

    # Scan skills/
    skills_dir = base / "skills"
    if skills_dir.is_dir():
        records.extend(_scan_skills(skills_dir, scope_name, harness))

    # Scan agents/
    agents_dir = base / "agents"
    if agents_dir.is_dir():
        records.extend(_scan_subagents(agents_dir, scope_name, harness))

    return records


def _scan_claude_settings(
    path: Path,
    scope: str,
    harness: str,
) -> list[SurfaceRecord]:
    records: list[SurfaceRecord] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return records

    # Hooks
    hooks = data.get("hooks", {})
    if isinstance(hooks, dict):
        for hook_name, hook_config in hooks.items():
            records.append(
                SurfaceRecord(
                    id=f"hook:{hook_name}@{scope}",
                    type="hook",
                    name=hook_name,
                    scope=scope,
                    harness=harness,
                    source=str(path),
                    enabled=True,
                    metadata={"config": _redact_value(hook_config)}
                    if isinstance(hook_config, dict)
                    else {},
                )
            )

    # MCP servers
    mcp_servers = data.get("mcpServers", {})
    if isinstance(mcp_servers, dict):
        for server_name, server_config in mcp_servers.items():
            transport = "stdio"
            if isinstance(server_config, dict):
                if server_config.get("command"):
                    transport = "stdio"
                elif server_config.get("url"):
                    transport = "sse"
            records.append(
                SurfaceRecord(
                    id=f"mcp_server:{server_name}@{scope}",
                    type="mcp_server",
                    name=server_name,
                    scope=scope,
                    harness=harness,
                    source=str(path),
                    enabled=True,
                    metadata={"transport": transport},
                )
            )

    # Permissions
    permissions = data.get("permissions", {})
    if isinstance(permissions, dict):
        for perm_name, perm_config in permissions.items():
            records.append(
                SurfaceRecord(
                    id=f"permission:{perm_name}@{scope}",
                    type="permission",
                    name=perm_name,
                    scope=scope,
                    harness=harness,
                    source=str(path),
                    enabled=True,
                    metadata={"config": _redact_value(perm_config)}
                    if isinstance(perm_config, dict)
                    else {},
                )
            )

    # Subagents from settings
    custom_agents = data.get("customAgents", {})
    if isinstance(custom_agents, dict):
        for agent_name, agent_config in custom_agents.items():
            write_perm = False
            if isinstance(agent_config, dict):
                write_perm = agent_config.get("writePermission", False)
            records.append(
                SurfaceRecord(
                    id=f"subagent:{agent_name}@{scope}",
                    type="subagent",
                    name=agent_name,
                    scope=scope,
                    harness=harness,
                    source=str(path),
                    enabled=True,
                    metadata={"write_permission": write_perm},
                )
            )

    return records


def _scan_cursor_hooks(
    path: Path,
    scope: str,
    harness: str,
) -> list[SurfaceRecord]:
    """Scan Cursor hooks.json (event name -> list of hook entries)."""
    records: list[SurfaceRecord] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return records

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return records

    for event_name, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            matcher = entry.get("matcher")
            matcher_label = matcher if isinstance(matcher, str) and matcher else str(index)
            hook_name = f"{event_name}:{matcher_label}"
            records.append(
                SurfaceRecord(
                    id=f"hook:{hook_name}@{scope}",
                    type="hook",
                    name=hook_name,
                    scope=scope,
                    harness=harness,
                    source=str(path),
                    enabled=True,
                    metadata=_redact_value(
                        {
                            "event": event_name,
                            "command": entry.get("command"),
                            "matcher": matcher,
                        }
                    ),
                )
            )

    return records


def _scan_toml_config(
    path: Path,
    scope: str,
    harness: str,
) -> list[SurfaceRecord]:
    records: list[SurfaceRecord] = []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return records
    if not isinstance(data, dict):
        return records
    for section_name, section_value in data.items():
        records.append(
            SurfaceRecord(
                id=f"permission:{section_name}@{scope}",
                type="permission",
                name=str(section_name),
                scope=scope,
                harness=harness,
                source=str(path),
                enabled=True,
                metadata={"section": _redact_value(section_value)}
                if isinstance(section_value, dict)
                else {},
            )
        )
    return records


def _scan_commands(
    commands_dir: Path,
    scope: str,
    harness: str,
) -> list[SurfaceRecord]:
    records: list[SurfaceRecord] = []
    for cmd_file in sorted(commands_dir.iterdir()):
        if cmd_file.suffix in (".md", ".toml"):
            cmd_name = cmd_file.stem
            description = _extract_command_description(cmd_file)
            records.append(
                SurfaceRecord(
                    id=f"command:{cmd_name}@{scope}",
                    type="command",
                    name=cmd_name,
                    scope=scope,
                    harness=harness,
                    source=str(cmd_file),
                    enabled=True,
                    metadata={"description": description},
                )
            )
    return records


def _scan_skills(
    skills_dir: Path,
    scope: str,
    harness: str,
) -> list[SurfaceRecord]:
    records: list[SurfaceRecord] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        skill_md = skill_dir / "SKILL.md"
        description = ""
        if skill_md.exists():
            description = _extract_skill_description(skill_md)
        records.append(
            SurfaceRecord(
                id=f"skill:{skill_name}@{scope}",
                type="skill",
                name=skill_name,
                scope=scope,
                harness=harness,
                source=str(skill_dir),
                enabled=True,
                metadata={"description": description},
            )
        )
    return records


def _scan_subagents(
    agents_dir: Path,
    scope: str,
    harness: str,
) -> list[SurfaceRecord]:
    records: list[SurfaceRecord] = []
    for agent_file in sorted(agents_dir.iterdir()):
        if agent_file.suffix in (".md", ".toml"):
            agent_name = agent_file.stem
            records.append(
                SurfaceRecord(
                    id=f"subagent:{agent_name}@{scope}",
                    type="subagent",
                    name=agent_name,
                    scope=scope,
                    harness=harness,
                    source=str(agent_file),
                    enabled=True,
                    metadata={},
                )
            )
    return records


def _extract_command_description(path: Path) -> str:
    """Extract description from a command file (first non-frontmatter line or heading)."""
    try:
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
            if line.strip() and not line.startswith("---"):
                return line.strip()[:100]
    except OSError:
        pass
    return ""


def _resolve_scope_dir(
    harness: str,
    scope: str,
    cwd: Path | None = None,
    home_dir: Path | None = None,
) -> Path:
    if harness not in _HARNESS_SCOPES:
        msg = f"unsupported harness: {harness}"
        raise ValueError(msg)
    cwd_path = cwd or Path.cwd()
    base_home = home_dir or Path.home()
    return {
        "user": base_home / _HARNESS_SCOPES[harness]["user"],
        "project": cwd_path.resolve() / _HARNESS_SCOPES[harness]["project"],
        "local": cwd_path.resolve() / _HARNESS_SCOPES[harness]["local"],
    }[scope]


def resolve_standalone_surface_path(
    harness: str,
    scope: str,
    surface_kind: str,
    name: str,
    cwd: Path | None = None,
    home_dir: Path | None = None,
) -> Path:
    """Return file path for standalone surface writes (skills, commands)."""
    scope_dir = _resolve_scope_dir(harness, scope, cwd, home_dir)
    if surface_kind == "skill":
        return scope_dir / "skills" / name / "SKILL.md"
    if surface_kind == "command":
        return scope_dir / "commands" / f"{name}.md"
    msg = f"unsupported standalone surface kind: {surface_kind}"
    raise ValueError(msg)


def resolve_surface_write_target(
    harness: str,
    scope: str,
    surface_kind: str,
    cwd: Path | None = None,
    home_dir: Path | None = None,
) -> tuple[Path, str]:
    """Return (file_path, file_format) for structured surface writes."""
    scope_dir = _resolve_scope_dir(harness, scope, cwd, home_dir)
    if harness == "cursor" and surface_kind == "mcp_server":
        return scope_dir / "mcp.json", "json"
    if harness == "cursor" and surface_kind == "hook":
        return scope_dir / "hooks.json", "json"
    if harness in _JSON_SETTINGS_FILES:
        return scope_dir / _JSON_SETTINGS_FILES[harness], "json"
    return scope_dir / "config.toml", "toml"


def _extract_skill_description(path: Path) -> str:
    """Extract description from SKILL.md (first heading after frontmatter)."""
    try:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        # Handle YAML frontmatter (between two --- lines)
        in_frontmatter = False
        if lines and lines[0].strip() == "---":
            in_frontmatter = True
        for i, line in enumerate(lines):
            if in_frontmatter:
                if line.strip() == "---" and i > 0:
                    in_frontmatter = False
                continue
            if line.startswith("# "):
                return line[2:].strip()
            if line.strip():
                return line.strip()[:100]
    except OSError:
        pass
    return ""
