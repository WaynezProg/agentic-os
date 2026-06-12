"""Tests for vibe coding agent attach support (P35 Task 8)."""
import tempfile
import textwrap
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


# ─── P36 discover / bind ─────────────────────────────────────────────


def test_discover_finds_external_claude_session_in_workspace(tmp_path: Path) -> None:
    """discover should return Claude sessions found in workspace log dirs."""
    from agentic_os.attach import discover_external_sessions

    log_dir = tmp_path / ".claude" / "projects" / "demo"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "abc-123.jsonl"
    log_file.write_text(
        '{"type":"init","session_id":"abc-123","cwd":"' + str(tmp_path) + '"}\n{"type":"msg"}\n',
        encoding="utf-8",
    )

    claude_agent = AgentDefinition(
        id="claude",
        label="Claude Code",
        command=["claude"],
        cwd_mode="required",
        stop_policy="process_group",
        log_paths=[str(tmp_path / ".claude" / "projects")],
        tool_kind="vibe_coding",
    )

    results = discover_external_sessions(
        workspace_path=str(tmp_path),
        agents=[claude_agent],
    )

    assert len(results) == 1
    assert results[0].agent_id == "claude"
    assert results[0].external_session_id == "abc-123"
    assert results[0].log_path == str(log_file)


def test_discover_returns_empty_when_no_sessions(tmp_path: Path) -> None:
    from agentic_os.attach import discover_external_sessions

    claude_agent = AgentDefinition(
        id="claude",
        label="Claude Code",
        command=["claude"],
        cwd_mode="required",
        stop_policy="process_group",
        log_paths=[str(tmp_path / "missing")],
        tool_kind="vibe_coding",
    )

    results = discover_external_sessions(
        workspace_path=str(tmp_path),
        agents=[claude_agent],
    )

    assert results == []


def test_discover_ignores_unsupported_agents(tmp_path: Path) -> None:
    from agentic_os.attach import discover_external_sessions

    # shell is not in _SUPPORTED; even with sessions, should be skipped.
    log_dir = tmp_path / "shell-logs"
    log_dir.mkdir()
    (log_dir / "x.jsonl").write_text('{"sessionId":"x1"}\n', encoding="utf-8")

    shell_agent = AgentDefinition(
        id="shell",
        label="Shell",
        command=["/bin/echo"],
        cwd_mode="optional",
        stop_policy="process_group",
        log_paths=[str(log_dir)],
        tool_kind=None,
    )

    results = discover_external_sessions(
        workspace_path=str(tmp_path),
        agents=[shell_agent],
    )

    assert results == []


def test_discover_does_not_read_secrets(tmp_path: Path) -> None:
    """discover must not include session log contents (no API keys leaked)."""
    from agentic_os.attach import discover_external_sessions

    log_dir = tmp_path / ".codex"
    log_dir.mkdir()
    log_file = log_dir / "s1.jsonl"
    log_file.write_text(
        '{"sessionId":"s1","cwd":"' + str(tmp_path) + '","env":{"OPENAI_API_KEY":"sk-REDACTED"}}\n',
        encoding="utf-8",
    )

    codex_agent = AgentDefinition(
        id="codex",
        label="Codex",
        command=["codex"],
        cwd_mode="required",
        stop_policy="process_group",
        log_paths=[str(log_dir)],
        tool_kind="vibe_coding",
    )

    results = discover_external_sessions(
        workspace_path=str(tmp_path),
        agents=[codex_agent],
    )

    assert len(results) == 1
    # None of the result fields should contain the secret value.
    dumped = str(results[0].__dict__)
    assert "sk-REDACTED" not in dumped
    assert "OPENAI_API_KEY" not in dumped


# ─── P36 bind (API-level) ────────────────────────────────────────────


def test_api_discover_endpoint_returns_external_sessions(tmp_path: Path) -> None:
    """POST /sessions/discover should return matches with external_session_id + agent_id."""
    from fastapi.testclient import TestClient

    from agentic_os.api import create_app

    log_dir = tmp_path / ".claude" / "projects" / "demo"
    log_dir.mkdir(parents=True)
    (log_dir / "abc.jsonl").write_text(
        '{"type":"init","session_id":"abc-xyz","cwd":"' + str(tmp_path) + '"}\n',
        encoding="utf-8",
    )

    registry = tmp_path / "agents.toml"
    registry.write_text(
        textwrap.dedent(
            f"""\
            [[agents]]
            id = "claude"
            label = "Claude Code"
            command = ["claude"]
            cwd_mode = "required"
            stop_policy = "process_group"
            tool_kind = "vibe_coding"
            log_paths = ["{log_dir}"]
            """
        ),
        encoding="utf-8",
    )

    client = TestClient(
        create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry)
    )

    response = client.post(
        "/sessions/discover",
        json={"workspace_path": str(tmp_path)},
    )

    assert response.status_code == 200
    discovered = response.json()["discovered"]
    assert len(discovered) == 1
    assert discovered[0]["agent_id"] == "claude"
    assert discovered[0]["external_session_id"] == "abc-xyz"


def test_api_bind_creates_session_with_external_id(tmp_path: Path) -> None:
    """POST /sessions/bind should create a session record bound to external session."""
    from fastapi.testclient import TestClient

    from agentic_os.api import create_app

    log_root = tmp_path / "claude-logs"
    log_root.mkdir()
    log_file = log_root / "claude.jsonl"
    log_file.write_text('{"sessionId":"ext-abc-123"}\n', encoding="utf-8")
    registry = tmp_path / "agents.toml"
    registry.write_text(
        textwrap.dedent(
            f"""\
            [[agents]]
            id = "claude"
            label = "Claude Code"
            command = ["claude"]
            cwd_mode = "required"
            stop_policy = "process_group"
            tool_kind = "vibe_coding"
            log_paths = ["{log_root}"]
            """
        ),
        encoding="utf-8",
    )

    client = TestClient(
        create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry)
    )

    response = client.post(
        "/sessions/bind",
        json={
            "agent_id": "claude",
            "external_session_id": "ext-abc-123",
            "workspace_path": str(tmp_path),
            "log_path": str(log_file),
        },
    )

    assert response.status_code == 200
    session = response.json()
    assert session["external_session_id"] == "ext-abc-123"
    assert session["attachable"] is True
    assert session["attach_status"] == "available"

    # Should appear in /sessions list.
    listed = client.get("/sessions").json()["sessions"]
    assert any(s["id"] == session["id"] for s in listed)


def test_api_attach_preview_vibe_coding(tmp_path: Path) -> None:
    """POST /sessions/{id}/attach mode=preview returns command without executing."""
    from fastapi.testclient import TestClient

    from agentic_os.api import create_app

    log_root = tmp_path / "claude-logs"
    log_root.mkdir()
    log_file = log_root / "claude.jsonl"
    log_file.write_text('{"sessionId":"ext-preview-1"}\n', encoding="utf-8")
    registry = tmp_path / "agents.toml"
    registry.write_text(
        textwrap.dedent(
            f"""\
            [[agents]]
            id = "claude"
            label = "Claude Code"
            command = ["claude"]
            cwd_mode = "required"
            stop_policy = "process_group"
            tool_kind = "vibe_coding"
            attach_command = ["claude", "--resume"]
            log_paths = ["{log_root}"]
            """
        ),
        encoding="utf-8",
    )

    client = TestClient(
        create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry)
    )

    bind = client.post(
        "/sessions/bind",
        json={
            "agent_id": "claude",
            "external_session_id": "ext-preview-1",
            "workspace_path": str(tmp_path),
            "log_path": str(log_file),
        },
    )
    assert bind.status_code == 200
    session_id = bind.json()["id"]

    response = client.post(
        f"/sessions/{session_id}/attach", json={"mode": "preview"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "allow"
    assert payload["attach_command"] == ["claude", "--resume", "ext-preview-1"]


def test_discover_excludes_other_workspaces_and_unscoped_sessions(tmp_path: Path) -> None:
    """workspace_path must actually scope results (codex review P1)."""
    from agentic_os.attach import discover_external_sessions

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "mine.jsonl").write_text(
        '{"session_id":"mine-1","cwd":"' + str(tmp_path / "ws") + '"}\n', encoding="utf-8"
    )
    (log_dir / "other.jsonl").write_text(
        '{"session_id":"other-1","cwd":"/somewhere/else"}\n', encoding="utf-8"
    )
    (log_dir / "nocwd.jsonl").write_text('{"session_id":"nocwd-1"}\n', encoding="utf-8")
    (tmp_path / "ws").mkdir()

    agent = AgentDefinition(
        id="claude",
        label="Claude Code",
        command=["claude"],
        cwd_mode="required",
        stop_policy="process_group",
        log_paths=[str(log_dir)],
        tool_kind="vibe_coding",
    )

    results = discover_external_sessions(workspace_path=str(tmp_path / "ws"), agents=[agent])
    assert [r.external_session_id for r in results] == ["mine-1"]


def test_api_bind_rejects_log_path_outside_agent_roots(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from agentic_os.api import create_app

    log_root = tmp_path / "claude-logs"
    log_root.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    registry = tmp_path / "agents.toml"
    registry.write_text(
        textwrap.dedent(
            f"""\
            [[agents]]
            id = "claude"
            label = "Claude Code"
            command = ["claude"]
            cwd_mode = "required"
            stop_policy = "process_group"
            tool_kind = "vibe_coding"
            log_paths = ["{log_root}"]
            """
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    response = client.post(
        "/sessions/bind",
        json={
            "agent_id": "claude",
            "external_session_id": "ext-1",
            "workspace_path": str(tmp_path),
            "log_path": str(outside),
        },
    )
    assert response.status_code == 400

    not_jsonl = log_root / "x.txt"
    not_jsonl.write_text("hi", encoding="utf-8")
    response = client.post(
        "/sessions/bind",
        json={
            "agent_id": "claude",
            "external_session_id": "ext-1",
            "workspace_path": str(tmp_path),
            "log_path": str(not_jsonl),
        },
    )
    assert response.status_code == 400

    missing_ws = client.post(
        "/sessions/bind",
        json={
            "agent_id": "claude",
            "external_session_id": "ext-1",
            "workspace_path": str(tmp_path / "nope"),
            "log_path": str(log_root / "claude.jsonl"),
        },
    )
    assert missing_ws.status_code == 400
