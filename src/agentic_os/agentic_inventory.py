"""Agentic runtime inventory (P37). Read-only; never modifies external tool state."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SurfaceSummary:
    """A single skill/tool/flow entry."""

    identifier: str
    enabled: bool | None = None
    detail: str | None = None


@dataclass(frozen=True)
class McpSurfaceSummary:
    """A single MCP server entry."""

    identifier: str
    status: str | None = None


@dataclass(frozen=True)
class AgenticInventoryResult:
    """Inventory for one agentic runtime agent."""

    agent_id: str
    tool_kind: str
    skills: list[SurfaceSummary] = field(default_factory=list)
    mcp_servers: list[McpSurfaceSummary] = field(default_factory=list)
    tools: list[SurfaceSummary] = field(default_factory=list)
    flows: list[SurfaceSummary] = field(default_factory=list)
    error: str | None = None


def build_agentic_inventory(
    *, agent_id: str, config_path: str | None
) -> AgenticInventoryResult:
    """Dispatch to the per-agent reader. Always returns a result, never raises."""
    try:
        path = Path(config_path).expanduser() if config_path else None
        if path is None or not path.exists() or not path.is_dir():
            return AgenticInventoryResult(agent_id=agent_id, tool_kind="agentic_runtime")
        if agent_id == "openclaw":
            return _read_openclaw_inventory(path)
        if agent_id == "hermes":
            return _read_hermes_inventory(path)
        if agent_id == "n8n":
            return _read_n8n_inventory(path)
        return AgenticInventoryResult(agent_id=agent_id, tool_kind="agentic_runtime")
    except Exception as exc:  # never let one agent break the list
        return AgenticInventoryResult(
            agent_id=agent_id, tool_kind="agentic_runtime", error=str(exc)
        )


def _safe_load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _read_openclaw_inventory(path: Path) -> AgenticInventoryResult:
    skills: list[SurfaceSummary] = []
    skills_dir = path / "skills.d"
    if skills_dir.exists() and skills_dir.is_dir():
        for f in sorted(skills_dir.glob("*.toml")):
            data = _safe_load_toml(f)
            skill = data.get("skill", {})
            sid = skill.get("id") or f.stem
            skills.append(
                SurfaceSummary(
                    identifier=sid,
                    enabled=skill.get("enabled"),
                    detail=skill.get("description"),
                )
            )

    mcp: list[McpSurfaceSummary] = []
    mcp_path = path / "mcp.toml"
    if mcp_path.exists():
        data = _safe_load_toml(mcp_path)
        for server in data.get("servers", []):
            mcp.append(
                McpSurfaceSummary(
                    identifier=server.get("id", "<unknown>"),
                    status=server.get("status"),
                )
            )

    return AgenticInventoryResult(
        agent_id="openclaw",
        tool_kind="agentic_runtime",
        skills=skills,
        mcp_servers=mcp,
    )


def _read_hermes_inventory(path: Path) -> AgenticInventoryResult:
    skills: list[SurfaceSummary] = []
    skills_path = path / "skills.toml"
    if skills_path.exists():
        data = _safe_load_toml(skills_path)
        for skill in data.get("skill", []):
            skills.append(
                SurfaceSummary(
                    identifier=skill.get("id", "<unknown>"),
                    enabled=skill.get("enabled"),
                )
            )

    tools: list[SurfaceSummary] = []
    tools_path = path / "tools.toml"
    if tools_path.exists():
        data = _safe_load_toml(tools_path)
        for tool in data.get("tool", []):
            tools.append(
                SurfaceSummary(
                    identifier=tool.get("id", "<unknown>"),
                    detail=tool.get("type"),
                )
            )

    mcp: list[McpSurfaceSummary] = []
    mcp_path = path / "mcp.toml"
    if mcp_path.exists():
        data = _safe_load_toml(mcp_path)
        for server in data.get("server", []):
            mcp.append(
                McpSurfaceSummary(
                    identifier=server.get("id", "<unknown>"),
                    status=server.get("status"),
                )
            )

    return AgenticInventoryResult(
        agent_id="hermes",
        tool_kind="agentic_runtime",
        skills=skills,
        mcp_servers=mcp,
        tools=tools,
    )


def _read_n8n_inventory(path: Path) -> AgenticInventoryResult:
    import json

    flows: list[SurfaceSummary] = []
    wf_dir = path / "workflows"
    if wf_dir.exists() and wf_dir.is_dir():
        for wf in sorted(wf_dir.glob("*.json")):
            try:
                data = json.loads(wf.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            name = data.get("name") or wf.stem
            flows.append(
                SurfaceSummary(
                    identifier=name,
                    enabled=data.get("active"),
                )
            )

    return AgenticInventoryResult(
        agent_id="n8n",
        tool_kind="agentic_runtime",
        flows=flows,
    )


def inventory_result_dict(result: AgenticInventoryResult) -> dict[str, object]:
    """Serialize one inventory result for API responses."""
    return {
        "agent_id": result.agent_id,
        "tool_kind": result.tool_kind,
        "skills": [
            {
                "identifier": item.identifier,
                "enabled": item.enabled,
                "detail": item.detail,
            }
            for item in result.skills
        ],
        "mcp_servers": [
            {
                "identifier": item.identifier,
                "status": item.status,
            }
            for item in result.mcp_servers
        ],
        "tools": [
            {
                "identifier": item.identifier,
                "enabled": item.enabled,
                "detail": item.detail,
            }
            for item in result.tools
        ],
        "flows": [
            {
                "identifier": item.identifier,
                "enabled": item.enabled,
                "detail": item.detail,
            }
            for item in result.flows
        ],
        "error": result.error,
    }


def build_all_agentic_inventory(agents: list) -> list[AgenticInventoryResult]:
    """Build inventory for every enabled agentic_runtime agent in the registry."""
    results: list[AgenticInventoryResult] = []
    for agent in agents:
        if not agent.enabled or agent.tool_kind != "agentic_runtime":
            continue
        results.append(
            build_agentic_inventory(agent_id=agent.id, config_path=agent.config_path)
        )
    return results
