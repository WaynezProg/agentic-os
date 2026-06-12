"""Tests for domain model extensions (P34+)."""
import pytest
from agentic_os.models import AgentDefinition, ToolKind


def test_tool_kind_type_exists():
    """ToolKind should be a Literal type."""
    from typing import get_args
    args = get_args(ToolKind)
    assert "vibe_coding" in args
    assert "agentic_runtime" in args


def test_agent_definition_has_tool_kind():
    agent = AgentDefinition(
        id="test",
        label="Test",
        command=["test"],
        tool_kind="vibe_coding",
    )
    assert agent.tool_kind == "vibe_coding"


def test_agent_definition_tool_kind_default():
    agent = AgentDefinition(
        id="test",
        label="Test",
        command=["test"],
    )
    assert agent.tool_kind is None


def test_agent_definition_tool_kind_invalid():
    with pytest.raises(Exception):
        AgentDefinition(
            id="test",
            label="Test",
            command=["test"],
            tool_kind="invalid_kind",
        )


def test_session_create_has_workspace_path():
    from agentic_os.models import SessionCreate
    session = SessionCreate(
        agent_id="claude",
        cwd="/tmp/project",
        argv=["claude", "-p", "test"],
        artifact_dir="/tmp/art",
        stdout_log="/tmp/out",
        stderr_log="/tmp/err",
        workspace_path="/tmp/project",
    )
    assert session.workspace_path == "/tmp/project"


def test_session_create_workspace_path_optional():
    from agentic_os.models import SessionCreate
    session = SessionCreate(
        agent_id="claude",
        cwd="/tmp/project",
        argv=["claude"],
        artifact_dir="/tmp/art",
        stdout_log="/tmp/out",
        stderr_log="/tmp/err",
    )
    assert session.workspace_path is None
