from agentic_os.patch_engine import PatchOp
from agentic_os.surface_ops import compile_semantic_ops


def test_enable_mcp_server_claude() -> None:
    ops = compile_semantic_ops(
        "claude",
        [
            {
                "op": "enable_mcp_server",
                "name": "github",
                "scope": "project",
                "config": {"command": "npx", "args": ["-y", "mcp"]},
            }
        ],
    )
    assert ops == [
        PatchOp(
            op="merge",
            path="mcpServers.github",
            value={"command": "npx", "args": ["-y", "mcp"]},
        )
    ]


def test_disable_mcp_server_codex() -> None:
    ops = compile_semantic_ops(
        "codex",
        [
            {
                "op": "disable_mcp_server",
                "name": "github",
                "scope": "project",
            }
        ],
    )
    assert ops == [PatchOp(op="remove", path="mcp_servers.github")]
