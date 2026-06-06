"""Tests for path-directed config patch operations."""

from __future__ import annotations

from agentic_os.patch_engine import PatchEngine, PatchOp


def test_merge_nested_path_preserves_unknown_keys() -> None:
    """merge at nested path keeps sibling keys and top-level fields."""
    doc = {"model": "sonnet", "mcpServers": {"existing": {"command": "keep"}}}
    ops = [PatchOp(op="merge", path="mcpServers.github", value={"command": "npx"})]
    result = PatchEngine.apply(doc, ops)
    assert result["model"] == "sonnet"
    assert result["mcpServers"]["existing"]["command"] == "keep"
    assert result["mcpServers"]["github"]["command"] == "npx"


def test_remove_key() -> None:
    """remove deletes nested key while preserving unrelated fields."""
    doc = {"hooks": {"PreToolUse": [{"command": "x"}]}, "model": "x"}
    ops = [PatchOp(op="remove", path="hooks.PreToolUse")]
    result = PatchEngine.apply(doc, ops)
    assert "hooks" not in result or "PreToolUse" not in result["hooks"]
    assert result["model"] == "x"
