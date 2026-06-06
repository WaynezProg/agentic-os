from __future__ import annotations

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


def compile_semantic_ops(harness: str, raw_ops: list[dict[str, Any]]) -> list[PatchOp]:
    compiled: list[PatchOp] = []
    for raw in raw_ops:
        op = raw.get("op")
        if op == "enable_mcp_server":
            prefix = _MCP_PATH[harness]
            name = raw["name"]
            compiled.append(
                PatchOp(op="merge", path=f"{prefix}.{name}", value=raw["config"])
            )
        elif op == "disable_mcp_server":
            prefix = _MCP_PATH[harness]
            compiled.append(PatchOp(op="remove", path=f"{prefix}.{raw['name']}"))
        elif op == "upsert_hook":
            compiled.extend(_compile_hook(harness, raw))
        else:
            msg = f"unsupported semantic op: {op}"
            raise ValueError(msg)
    return compiled


def _compile_hook(harness: str, raw: dict[str, Any]) -> list[PatchOp]:
    event = raw["event"]
    entry: dict[str, Any] = {}
    if raw.get("matcher") is not None:
        entry["matcher"] = raw["matcher"]
    if raw.get("command") is not None:
        entry["command"] = raw["command"]
    if harness == "cursor":
        # cursor hooks.json: hooks.EventName is a list; append entry
        return [PatchOp(op="merge", path=f"hooks.{event}", value=[entry])]
    return [PatchOp(op="merge", path=f"hooks.{event}", value=[entry])]
