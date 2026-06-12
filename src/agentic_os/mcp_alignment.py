"""Cross-tool MCP server alignment (P42).

Reads MCP server names/definitions from each tool's real config and
builds SafeEditEngine patches to copy a server between tools or remove
one. Server definitions (commands, env values, URLs) move file-to-file
inside this process; only key names ever leave via `summarize_def`.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from agentic_os.patch_engine import PatchOp
from agentic_os.safe_edit import PatchTarget

# Same real locations capability_inventory reads — these are where MCP
# servers actually live, which differs from P10's settings-file targets
# (claude keeps mcpServers in ~/.claude.json, not ~/.claude/settings.json).
_TOOL_CONFIGS: dict[str, tuple[str, str, str]] = {
    # tool: (relative config path, root key, format)
    "claude": (".claude.json", "mcpServers", "json"),
    "cursor": (".cursor/mcp.json", "mcpServers", "json"),
    "gemini": (".gemini/settings.json", "mcpServers", "json"),
    "qwen": (".qwen/settings.json", "mcpServers", "json"),
    "opencode": (".config/opencode/opencode.json", "mcp", "json"),
    "codex": (".codex/config.toml", "mcp_servers", "toml"),
}

# Tools sharing the {command, args, env, url} value shape; extras are
# carried only between members of this family.
_MCPSERVERS_FAMILY = frozenset({"claude", "cursor", "gemini", "qwen"})
_CANONICAL_KEYS = frozenset({"command", "args", "env", "url"})

SUPPORTED_TOOLS = tuple(_TOOL_CONFIGS)


@dataclass(frozen=True)
class CanonicalServer:
    transport: str  # "stdio" | "remote"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    extras: dict[str, object] = field(default_factory=dict)


def config_path(tool: str, home: Path) -> Path:
    rel, _, _ = _require_tool(tool)
    return home / rel


def root_key(tool: str) -> str:
    return _require_tool(tool)[1]


def config_format(tool: str) -> str:
    return _require_tool(tool)[2]


def _require_tool(tool: str) -> tuple[str, str, str]:
    entry = _TOOL_CONFIGS.get(tool)
    if entry is None:
        msg = f"unsupported tool: {tool}"
        raise ValueError(msg)
    return entry


def _load_config(tool: str, home: Path) -> dict[str, object]:
    path = config_path(tool, home)
    if not path.is_file():
        return {}
    if config_format(tool) == "toml":
        with path.open("rb") as fh:
            return tomllib.load(fh)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def target_config_parse_error(tool: str, home: Path) -> str | None:
    """Refuse-to-write guard: existing-but-unparseable config.

    SafeEditEngine treats unparseable JSON as an empty document, which
    would rewrite the file and drop everything else in it. A missing
    file is fine (it will be created).
    """
    path = config_path(tool, home)
    if not path.is_file():
        return None
    try:
        _load_config(tool, home)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, OSError) as exc:
        return f"target config parse failed: {path.name}: {exc}"
    return None


def _servers(tool: str, home: Path) -> dict[str, object]:
    try:
        config = _load_config(tool, home)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, OSError):
        return {}
    servers = config.get(root_key(tool))
    return servers if isinstance(servers, dict) else {}


def read_server_names(tool: str, home: Path) -> list[str]:
    return sorted(_servers(tool, home))


def read_server_def(tool: str, name: str, home: Path) -> dict[str, object] | None:
    value = _servers(tool, home).get(name)
    return value if isinstance(value, dict) else None


# --- canonical translation ---


def to_canonical(tool: str, raw: dict[str, object]) -> CanonicalServer:
    _require_tool(tool)
    if tool == "opencode":
        return _opencode_to_canonical(raw)
    command = raw.get("command")
    url = raw.get("url")
    args = raw.get("args")
    env = raw.get("env")
    extras = {
        key: value
        for key, value in raw.items()
        if key not in _CANONICAL_KEYS
    }
    if isinstance(command, str) and command:
        return CanonicalServer(
            transport="stdio",
            command=command,
            args=[str(a) for a in args] if isinstance(args, list) else [],
            env={str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {},
            extras=extras,
        )
    if isinstance(url, str) and url:
        return CanonicalServer(transport="remote", url=url, extras=extras)
    msg = "unsupported server shape: needs command or url"
    raise ValueError(msg)


def _opencode_to_canonical(raw: dict[str, object]) -> CanonicalServer:
    kind = raw.get("type")
    if kind == "remote":
        url = raw.get("url")
        if isinstance(url, str) and url:
            return CanonicalServer(transport="remote", url=url)
        msg = "unsupported server shape: remote without url"
        raise ValueError(msg)
    command = raw.get("command")
    if isinstance(command, list) and command:
        argv = [str(part) for part in command]
        environment = raw.get("environment")
        return CanonicalServer(
            transport="stdio",
            command=argv[0],
            args=argv[1:],
            env=(
                {str(k): str(v) for k, v in environment.items()}
                if isinstance(environment, dict)
                else {}
            ),
        )
    msg = "unsupported server shape: needs command list or url"
    raise ValueError(msg)


def from_canonical(tool: str, canon: CanonicalServer) -> dict[str, object]:
    _require_tool(tool)
    if tool == "opencode":
        if canon.transport == "remote":
            return {"type": "remote", "url": canon.url, "enabled": True}
        return {
            "type": "local",
            "command": [canon.command, *canon.args],
            **({"environment": dict(canon.env)} if canon.env else {}),
            "enabled": True,
        }
    out: dict[str, object] = {}
    if canon.transport == "remote":
        out["url"] = canon.url
    else:
        out["command"] = canon.command
        if canon.args:
            out["args"] = list(canon.args)
        if canon.env:
            out["env"] = dict(canon.env)
    if tool in _MCPSERVERS_FAMILY and canon.extras:
        for key, value in canon.extras.items():
            out.setdefault(key, value)
    return out


def summarize_def(raw: dict[str, object] | None) -> dict[str, object]:
    """Keys-only summary safe for API responses. Never includes values."""
    if not isinstance(raw, dict):
        return {"transport": "unknown", "fields": []}
    try:
        canon = to_canonical("claude", raw) if "type" not in raw else _opencode_to_canonical(raw)
    except ValueError:
        return {"transport": "unknown", "fields": sorted(str(k) for k in raw)}
    fields: list[str] = []
    if canon.command:
        fields.append("command")
    if canon.args:
        fields.append(f"args({len(canon.args)})")
    if canon.env:
        fields.append("env:" + ",".join(sorted(canon.env)))
    if canon.url:
        fields.append("url")
    return {"transport": canon.transport, "fields": fields}


# --- patch builders ---


def _patch_target(tool: str, home: Path) -> PatchTarget:
    return PatchTarget(
        harness_id=tool,
        cwd=home,
        scope="user",
        target_kind="capability_mcp",
        kind="mcp_server",
        file_path=config_path(tool, home),
        file_format=config_format(tool),
    )


def build_copy_patch(
    from_tool: str,
    to_tool: str,
    name: str,
    home: Path,
) -> tuple[PatchTarget, list[PatchOp], dict[str, object]]:
    raw = read_server_def(from_tool, name, home)
    if raw is None:
        msg = f"server not found in {from_tool}: {name}"
        raise KeyError(msg)
    canon = to_canonical(from_tool, raw)
    value = from_canonical(to_tool, canon)
    ops = [PatchOp(op="merge", path=f"{root_key(to_tool)}.{name}", value=value)]
    return _patch_target(to_tool, home), ops, summarize_def(raw)


def build_remove_patch(
    tool: str,
    name: str,
    home: Path,
) -> tuple[PatchTarget, list[PatchOp], dict[str, object]]:
    raw = read_server_def(tool, name, home)
    if raw is None:
        msg = f"server not found in {tool}: {name}"
        raise KeyError(msg)
    ops = [PatchOp(op="remove", path=f"{root_key(tool)}.{name}")]
    return _patch_target(tool, home), ops, summarize_def(raw)
