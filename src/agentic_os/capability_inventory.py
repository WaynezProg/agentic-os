"""Read-only inventory of real tool capabilities (P40).

Reads skills / MCP server names / plugins / memory-file metadata from
each vibe coding tool's actual config locations. Secrets invariant:
only NAMES leave this module — never commands, env values, or URLs.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_MAX_CONFIG_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class MemoryFileInfo:
    path: str
    size_bytes: int
    modified_at: str


@dataclass(frozen=True)
class ToolCapabilities:
    tool: str
    present: bool
    skills: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    memory_files: list[MemoryFileInfo] = field(default_factory=list)
    error: str | None = None


def capabilities_dict(caps: ToolCapabilities) -> dict[str, object]:
    return asdict(caps)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _guard_size(path: Path) -> None:
    size = path.stat().st_size
    if size > _MAX_CONFIG_BYTES:
        raise ValueError(f"config too large: {path.name} is {size} bytes")


def _load_json(path: Path) -> dict[str, object]:
    _guard_size(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_toml(path: Path) -> dict[str, object]:
    _guard_size(path)
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _dict_keys(payload: dict[str, object], key: str) -> list[str]:
    value = payload.get(key)
    if isinstance(value, dict):
        return sorted(str(name) for name in value)
    return []


def _list_dir_names(root: Path, *, dirs_only: bool = True) -> list[str]:
    if not root.is_dir():
        return []
    names: list[str] = []
    for entry in sorted(root.iterdir()):
        if entry.name.startswith("."):
            continue
        # Symlinked entries count: tools commonly symlink shared skills.
        if dirs_only and not entry.is_dir():
            continue
        names.append(entry.name)
    return names


def _list_file_stems(root: Path, suffix: str) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.stem for p in root.glob(f"*{suffix}") if p.is_file())


def _list_entries(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if not entry.name.startswith("."))


def _memory_file(path: Path) -> list[MemoryFileInfo]:
    # stat() follows symlinks (codex AGENTS.md links to a shared file);
    # the declared path is reported, the resolved target is measured.
    if not path.exists():
        return []
    try:
        stat = path.stat()
    except OSError:
        return []
    return [
        MemoryFileInfo(
            path=str(path),
            size_bytes=stat.st_size,
            modified_at=_iso(stat.st_mtime),
        )
    ]


def _read_claude(home: Path) -> ToolCapabilities:
    base = home / ".claude"
    if not base.is_dir():
        return ToolCapabilities(tool="claude", present=False)
    error: str | None = None
    mcp_servers: list[str] = []
    config = home / ".claude.json"
    if config.is_file():
        try:
            mcp_servers = _dict_keys(_load_json(config), "mcpServers")
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            error = str(exc)
    return ToolCapabilities(
        tool="claude",
        present=True,
        skills=_list_dir_names(base / "skills"),
        mcp_servers=mcp_servers,
        plugins=_list_dir_names(base / "plugins" / "cache"),
        memory_files=_memory_file(base / "CLAUDE.md"),
        error=error,
    )


def _read_codex(home: Path) -> ToolCapabilities:
    base = home / ".codex"
    if not base.is_dir():
        return ToolCapabilities(tool="codex", present=False)
    error: str | None = None
    mcp_servers: list[str] = []
    config = base / "config.toml"
    if config.is_file():
        try:
            mcp_servers = _dict_keys(_load_toml(config), "mcp_servers")
        except (ValueError, OSError, tomllib.TOMLDecodeError) as exc:
            error = str(exc)
    return ToolCapabilities(
        tool="codex",
        present=True,
        skills=_list_file_stems(base / "prompts", ".md"),
        mcp_servers=mcp_servers,
        memory_files=_memory_file(base / "AGENTS.md"),
        error=error,
    )


def _read_gemini(home: Path) -> ToolCapabilities:
    base = home / ".gemini"
    if not base.is_dir():
        return ToolCapabilities(tool="gemini", present=False)
    error: str | None = None
    mcp_servers: list[str] = []
    config = base / "settings.json"
    if config.is_file():
        try:
            mcp_servers = _dict_keys(_load_json(config), "mcpServers")
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            error = str(exc)
    return ToolCapabilities(
        tool="gemini",
        present=True,
        mcp_servers=mcp_servers,
        plugins=_list_dir_names(base / "extensions"),
        memory_files=_memory_file(base / "GEMINI.md"),
        error=error,
    )


def _read_qwen(home: Path) -> ToolCapabilities:
    base = home / ".qwen"
    if not base.is_dir():
        return ToolCapabilities(tool="qwen", present=False)
    error: str | None = None
    mcp_servers: list[str] = []
    config = base / "settings.json"
    if config.is_file():
        try:
            mcp_servers = _dict_keys(_load_json(config), "mcpServers")
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            error = str(exc)
    return ToolCapabilities(
        tool="qwen",
        present=True,
        skills=_list_dir_names(base / "skills"),
        mcp_servers=mcp_servers,
        memory_files=_memory_file(base / "QWEN.md"),
        error=error,
    )


def _read_opencode(home: Path) -> ToolCapabilities:
    base = home / ".config" / "opencode"
    if not base.is_dir():
        return ToolCapabilities(tool="opencode", present=False)
    error: str | None = None
    mcp_servers: list[str] = []
    config = base / "opencode.json"
    if config.is_file():
        try:
            mcp_servers = _dict_keys(_load_json(config), "mcp")
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            error = str(exc)
    return ToolCapabilities(
        tool="opencode",
        present=True,
        skills=_list_dir_names(base / "skills"),
        mcp_servers=mcp_servers,
        plugins=_list_entries(base / "plugins"),
        memory_files=_memory_file(base / "AGENTS.md"),
        error=error,
    )


def _read_cursor(home: Path) -> ToolCapabilities:
    base = home / ".cursor"
    if not base.is_dir():
        return ToolCapabilities(tool="cursor", present=False)
    error: str | None = None
    mcp_servers: list[str] = []
    config = base / "mcp.json"
    if config.is_file():
        try:
            mcp_servers = _dict_keys(_load_json(config), "mcpServers")
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            error = str(exc)
    return ToolCapabilities(
        tool="cursor",
        present=True,
        mcp_servers=mcp_servers,
        error=error,
    )


_READERS = {
    "claude": _read_claude,
    "codex": _read_codex,
    "gemini": _read_gemini,
    "qwen": _read_qwen,
    "opencode": _read_opencode,
    "cursor": _read_cursor,
}


def read_tool_capabilities(tool: str, home: Path | None = None) -> ToolCapabilities:
    reader = _READERS.get(tool)
    if reader is None:
        return ToolCapabilities(tool=tool, present=False, error=f"unknown tool: {tool}")
    resolved_home = home or Path.home()
    try:
        return reader(resolved_home)
    except Exception as exc:  # one broken config must not break the inventory
        return ToolCapabilities(tool=tool, present=True, error=str(exc))


def read_all_capabilities(home: Path | None = None) -> list[ToolCapabilities]:
    return [read_tool_capabilities(tool, home) for tool in _READERS]
