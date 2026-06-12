"""Tool discovery: detect installed tools and their versions (P34).

Scans well-known paths and runs `which` to detect tool installation.
Results are cached in-memory for 5 minutes to avoid repeated subprocess calls.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from agentic_os.models import AgentDefinition


@dataclass(frozen=True)
class ToolDiscoveryResult:
    agent_id: str
    tool_kind: str | None
    installed: bool
    binary_path: str | None
    version: str | None
    version_error: str | None


@dataclass(frozen=True)
class _VersionResult:
    version: str | None
    error: str | None


# Module-level cache
_cache: dict[str, tuple[float, ToolDiscoveryResult]] = {}
_CACHE_TTL = 300  # 5 minutes


def _cache_key(agent_id: str) -> str:
    return f"discovery:{agent_id}"


def invalidate_cache() -> None:
    """Clear the discovery cache. Call after tool install/uninstall."""
    _cache.clear()


def find_binary(name: str) -> str | None:
    """Find binary path using shutil.which. Returns None if not found."""
    return shutil.which(name)


def detect_version(command: list[str] | None) -> _VersionResult:
    """Run version command and parse output. Returns (version, error)."""
    if not command:
        return _VersionResult(version=None, error=None)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            output = (result.stdout or result.stderr).strip()
            version = output.split("\n")[0] if output else None
            return _VersionResult(version=version, error=None)
        else:
            error = (result.stderr or result.stdout).strip() or "non-zero exit"
            return _VersionResult(version=None, error=error[:200])
    except subprocess.TimeoutExpired:
        return _VersionResult(version=None, error="timeout after 10s")
    except FileNotFoundError:
        return _VersionResult(version=None, error="binary not found")
    except OSError as e:
        return _VersionResult(version=None, error=str(e)[:200])


def detect_tool(agent: AgentDefinition) -> ToolDiscoveryResult:
    """Detect a single tool's installation status and version."""
    binary_name = agent.command[0] if agent.command else ""
    binary_path = find_binary(binary_name) if binary_name else None
    installed = binary_path is not None

    version = None
    version_error = None
    if installed and agent.version_command:
        vresult = detect_version(agent.version_command)
        version = vresult.version
        version_error = vresult.error

    return ToolDiscoveryResult(
        agent_id=agent.id,
        tool_kind=agent.tool_kind,
        installed=installed,
        binary_path=binary_path,
        version=version,
        version_error=version_error,
    )


def discover_all(registry: Any) -> list[ToolDiscoveryResult]:
    """Discover all enabled agents in registry. Uses 5-min cache."""
    now = time.monotonic()
    results: list[ToolDiscoveryResult] = []

    for agent in registry.list_agents():
        if not agent.enabled:
            continue

        key = _cache_key(agent.id)
        cached = _cache.get(key)
        if cached and (now - cached[0]) < _CACHE_TTL:
            results.append(cached[1])
            continue

        result = detect_tool(agent)
        _cache[key] = (now, result)
        results.append(result)

    return sorted(results, key=lambda r: r.agent_id)
