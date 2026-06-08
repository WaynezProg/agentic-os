"""Tests for tool discovery (P34)."""
from unittest.mock import MagicMock

from agentic_os.tool_discovery import (
    find_binary,
    detect_version,
    detect_tool,
    discover_all,
)
from agentic_os.models import AgentDefinition


def test_find_binary_existing():
    """find_binary should return path for known binary."""
    result = find_binary("python3")
    assert result is not None
    assert "python" in result


def test_find_binary_missing():
    """find_binary should return None for unknown binary."""
    result = find_binary("nonexistent_binary_xyz_12345")
    assert result is None


def test_detect_version_success():
    """detect_version should return version string on success."""
    result = detect_version(["python3", "--version"])
    assert result.version is not None
    assert result.error is None


def test_detect_version_failure():
    """detect_version should return error on failure."""
    result = detect_version(["nonexistent_binary_xyz_12345", "--version"])
    assert result.version is None
    assert result.error is not None


def test_detect_tool_installed():
    """detect_tool should report installed=True when binary exists."""
    agent = AgentDefinition(
        id="test_tool",
        label="Test",
        command=["python3", "test"],
        version_command=["python3", "--version"],
        tool_kind="vibe_coding",
    )
    result = detect_tool(agent)
    assert result.agent_id == "test_tool"
    assert result.tool_kind == "vibe_coding"
    assert result.installed is True
    assert result.binary_path is not None


def test_detect_tool_not_installed():
    """detect_tool should report installed=False when binary missing."""
    agent = AgentDefinition(
        id="fake_tool",
        label="Fake",
        command=["fake_binary_xyz", "test"],
        version_command=["fake_binary_xyz", "--version"],
        tool_kind="vibe_coding",
    )
    result = detect_tool(agent)
    assert result.installed is False
    assert result.binary_path is None


def test_detect_tool_no_version_command():
    """detect_tool should handle missing version_command gracefully."""
    agent = AgentDefinition(
        id="no_version",
        label="No Version",
        command=["python3", "test"],
        version_command=None,
        tool_kind="vibe_coding",
    )
    result = detect_tool(agent)
    assert result.installed is True
    assert result.version is None


def test_discover_all_filters_enabled():
    """discover_all should only check enabled agents."""
    from agentic_os.registry import Registry

    agent_enabled = AgentDefinition(
        id="enabled_tool",
        label="Enabled",
        command=["python3", "test"],
        version_command=["python3", "--version"],
        enabled=True,
        tool_kind="vibe_coding",
    )
    agent_disabled = AgentDefinition(
        id="disabled_tool",
        label="Disabled",
        command=["python3", "test"],
        enabled=False,
        tool_kind="vibe_coding",
    )

    mock_registry = MagicMock(spec=Registry)
    mock_registry.list_agents.return_value = [agent_enabled, agent_disabled]

    results = discover_all(mock_registry)
    ids = [r.agent_id for r in results]
    assert "enabled_tool" in ids
    assert "disabled_tool" not in ids
