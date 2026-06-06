from agentic_os.patch_engine import PatchOp
from agentic_os.surface_ops import StandaloneFileTarget, compile_semantic_ops


def test_enable_mcp_server_claude() -> None:
    compiled = compile_semantic_ops(
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
    assert compiled.standalone_files == []
    assert compiled.patch_ops == [
        PatchOp(
            op="merge",
            path="mcpServers.github",
            value={"command": "npx", "args": ["-y", "mcp"]},
        )
    ]


def test_disable_mcp_server_codex() -> None:
    compiled = compile_semantic_ops(
        "codex",
        [
            {
                "op": "disable_mcp_server",
                "name": "github",
                "scope": "project",
            }
        ],
    )
    assert compiled.standalone_files == []
    assert compiled.patch_ops == [PatchOp(op="remove", path="mcp_servers.github")]


def test_upsert_skill_compiles_to_standalone_target() -> None:
    compiled = compile_semantic_ops(
        "claude",
        [
            {
                "op": "upsert_skill",
                "scope": "project",
                "name": "my-skill",
                "content": "# My Skill\n",
            }
        ],
    )
    assert compiled.patch_ops == []
    assert compiled.standalone_files == [
        StandaloneFileTarget(
            kind="skill",
            scope="project",
            name="my-skill",
            content="# My Skill\n",
        )
    ]


def test_upsert_command_compiles_to_standalone_target() -> None:
    compiled = compile_semantic_ops(
        "claude",
        [
            {
                "op": "upsert_command",
                "scope": "project",
                "name": "review",
                "content": "# Review\n",
            }
        ],
    )
    assert compiled.patch_ops == []
    assert compiled.standalone_files == [
        StandaloneFileTarget(
            kind="command",
            scope="project",
            name="review",
            content="# Review\n",
        )
    ]
