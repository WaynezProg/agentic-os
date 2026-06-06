from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentic_os.patch_engine import PatchOp

_MCP_PATH = {
    "claude": "mcpServers",
    "cursor": "mcpServers",
    "opencode": "mcpServers",
    "qwen": "mcpServers",
    "codex": "mcp_servers",
    "openclaw": "mcp_servers",
    "hermes": "mcp_servers",
}


@dataclass(frozen=True)
class StandaloneFileTarget:
    kind: str
    scope: str
    name: str
    content: str


@dataclass(frozen=True)
class CompiledSurfacePatch:
    patch_ops: list[PatchOp]
    standalone_files: list[StandaloneFileTarget]


def compile_semantic_ops(harness: str, raw_ops: list[dict[str, Any]]) -> CompiledSurfacePatch:
    patch_ops: list[PatchOp] = []
    standalone_files: list[StandaloneFileTarget] = []
    for raw in raw_ops:
        op = raw.get("op")
        if op == "enable_mcp_server":
            prefix = _MCP_PATH[harness]
            name = raw["name"]
            patch_ops.append(
                PatchOp(op="merge", path=f"{prefix}.{name}", value=raw["config"])
            )
        elif op == "disable_mcp_server":
            prefix = _MCP_PATH[harness]
            patch_ops.append(PatchOp(op="remove", path=f"{prefix}.{raw['name']}"))
        elif op == "upsert_hook":
            patch_ops.extend(_compile_hook(harness, raw))
        elif op == "upsert_skill":
            standalone_files.append(
                StandaloneFileTarget(
                    kind="skill",
                    scope=str(raw["scope"]),
                    name=str(raw["name"]),
                    content=str(raw["content"]),
                )
            )
        elif op == "upsert_command":
            standalone_files.append(
                StandaloneFileTarget(
                    kind="command",
                    scope=str(raw["scope"]),
                    name=str(raw["name"]),
                    content=str(raw["content"]),
                )
            )
        else:
            msg = f"unsupported semantic op: {op}"
            raise ValueError(msg)
    return CompiledSurfacePatch(patch_ops=patch_ops, standalone_files=standalone_files)


def _compile_hook(harness: str, raw: dict[str, Any]) -> list[PatchOp]:
    event = raw["event"]
    entry: dict[str, Any] = {}
    if raw.get("matcher") is not None:
        entry["matcher"] = raw["matcher"]
    if raw.get("command") is not None:
        entry["command"] = raw["command"]
    # hooks.{event} is a list; merge appends when the target list already exists.
    return [PatchOp(op="merge", path=f"hooks.{event}", value=[entry])]
