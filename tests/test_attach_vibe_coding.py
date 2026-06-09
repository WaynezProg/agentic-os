"""Tests for vibe coding agent attach support (P35 Task 8)."""
import tempfile
from pathlib import Path

from agentic_os.attach import (
    build_attach_command,
    evaluate_attach,
    parse_external_session_id,
    _SUPPORTED,
)
from agentic_os.models import AgentDefinition, SessionRecord, SessionStatus


def test_vibe_coding_in_supported():
    """Vibe coding agents should be in _SUPPORTED."""
    assert "claude" in _SUPPORTED
    assert "codex" in _SUPPORTED
    assert "cursor" in _SUPPORTED


def test_parse_claude_session_id_from_jsonl():
    """Should parse session_id from Claude Code JSONL output."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"type": "init", "session_id": "abc123"}\n')
        f.write('{"type": "message", "content": "hello"}\n')
        f.flush()
        log_path = Path(f.name)

    session_id = parse_external_session_id("claude", log_path)
    assert session_id == "abc123"

    log_path.unlink()


def test_parse_codex_session_id_from_jsonl():
    """Should parse session_id from Codex JSONL output."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"session_id": "codex-xyz-789"}\n')
        f.write('{"role": "assistant", "content": "working"}\n')
        f.flush()
        log_path = Path(f.name)

    session_id = parse_external_session_id("codex", log_path)
    assert session_id == "codex-xyz-789"

    log_path.unlink()


def test_parse_session_id_not_found():
    """Should return None when no session_id in log."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"type": "message", "content": "no session id here"}\n')
        f.flush()
        log_path = Path(f.name)

    session_id = parse_external_session_id("claude", log_path)
    assert session_id is None

    log_path.unlink()


def test_build_attach_command_claude():
    """Should build attach command for Claude."""
    agent = AgentDefinition(
        id="claude",
        label="Claude Code",
        command=["claude"],
        attach_command=["claude", "--resume"],
        tool_kind="vibe_coding",
    )
    session = SessionRecord(
        id="sess-1",
        agent_id="claude",
        cwd="/tmp",
        argv=["claude"],
        artifact_dir="/tmp/art",
        stdout_log="/tmp/out.jsonl",
        stderr_log="/tmp/err.jsonl",
        status=SessionStatus.SUCCEEDED,
        updated_at="2026-01-01T00:00:00Z",
        external_session_id="abc123",
    )

    cmd = build_attach_command(agent, session)
    assert cmd == ["claude", "--resume", "abc123"]


def test_build_attach_command_codex():
    """Should build attach command for Codex."""
    agent = AgentDefinition(
        id="codex",
        label="Codex",
        command=["codex"],
        attach_command=["codex", "resume"],
        tool_kind="vibe_coding",
    )
    session = SessionRecord(
        id="sess-2",
        agent_id="codex",
        cwd="/tmp",
        argv=["codex"],
        artifact_dir="/tmp/art",
        stdout_log="/tmp/out.jsonl",
        stderr_log="/tmp/err.jsonl",
        status=SessionStatus.SUCCEEDED,
        updated_at="2026-01-01T00:00:00Z",
        external_session_id="codex-xyz",
    )

    cmd = build_attach_command(agent, session)
    assert cmd == ["codex", "resume", "codex-xyz"]


def test_build_attach_command_no_external_id():
    """Should return base command when no external_session_id."""
    agent = AgentDefinition(
        id="claude",
        label="Claude Code",
        command=["claude"],
        attach_command=["claude", "--resume"],
        tool_kind="vibe_coding",
    )
    session = SessionRecord(
        id="sess-3",
        agent_id="claude",
        cwd="/tmp",
        argv=["claude"],
        artifact_dir="/tmp/art",
        stdout_log="/tmp/out.jsonl",
        stderr_log="/tmp/err.jsonl",
        status=SessionStatus.SUCCEEDED,
        updated_at="2026-01-01T00:00:00Z",
        external_session_id=None,
    )

    cmd = build_attach_command(agent, session)
    assert cmd == ["claude", "--resume"]


def test_evaluate_attach_claude_allowed():
    """Should allow attach for Claude when external_session_id present."""
    agent = AgentDefinition(
        id="claude",
        label="Claude Code",
        command=["claude"],
        attach_command=["claude", "--resume"],
        tool_kind="vibe_coding",
    )
    session = SessionRecord(
        id="sess-4",
        agent_id="claude",
        cwd="/tmp",
        argv=["claude"],
        artifact_dir="/tmp/art",
        stdout_log="/tmp/out.jsonl",
        stderr_log="/tmp/err.jsonl",
        status=SessionStatus.SUCCEEDED,
        updated_at="2026-01-01T00:00:00Z",
        external_session_id="abc123",
        attach_status="available",
    )

    decision, reason = evaluate_attach(agent, session)
    assert decision == "allow"
    assert "permitted" in reason.lower()


def test_evaluate_attach_denied_without_external_id():
    """Should deny attach when external_session_id missing."""
    agent = AgentDefinition(
        id="claude",
        label="Claude Code",
        command=["claude"],
        attach_command=["claude", "--resume"],
        tool_kind="vibe_coding",
    )
    session = SessionRecord(
        id="sess-5",
        agent_id="claude",
        cwd="/tmp",
        argv=["claude"],
        artifact_dir="/tmp/art",
        stdout_log="/tmp/out.jsonl",
        stderr_log="/tmp/err.jsonl",
        status=SessionStatus.SUCCEEDED,
        updated_at="2026-01-01T00:00:00Z",
        external_session_id=None,
        attach_status="none",
    )

    decision, reason = evaluate_attach(agent, session)
    assert decision == "deny"
    assert "external_session_id" in reason.lower()
