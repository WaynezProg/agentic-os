"""Tests for the P39 live session radar scanners."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentic_os.live_sessions import (
    build_open_terminal_command,
    scan_claude_sessions,
    scan_codex_sessions,
    scan_live_sessions,
)

NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)


def _touch(path: Path, *, hours_ago: float) -> None:
    ts = NOW.timestamp() - hours_ago * 3600
    os.utime(path, (ts, ts))


def _write_claude_session(
    root: Path,
    *,
    project: str = "-Users-w-proj",
    session_id: str = "abc-123",
    cwd: str | None = "/Users/w/proj",
    title: str = "fix the bug",
    hours_ago: float = 0.01,
    extra_lines: list[str] | None = None,
) -> Path:
    project_dir = root / project
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{session_id}.jsonl"
    user_obj: dict[str, object] = {
        "type": "user",
        "sessionId": session_id,
        "timestamp": "2026-06-12T10:00:00Z",
        "message": {"role": "user", "content": title},
    }
    if cwd is not None:
        user_obj["cwd"] = cwd
    lines = [json.dumps(user_obj)]
    if extra_lines:
        lines = extra_lines + lines
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _touch(path, hours_ago=hours_ago)
    return path


def _write_codex_session(
    root: Path,
    *,
    session_id: str = "019e-codex-1",
    cwd: str = "/Users/w/proj",
    title: str = "refactor pipeline",
    hours_ago: float = 0.01,
) -> Path:
    day_dir = root / "2026" / "06" / "12"
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"rollout-2026-06-12T10-00-00-{session_id}.jsonl"
    lines = [
        json.dumps(
            {
                "timestamp": "2026-06-12T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "timestamp": "2026-06-12T10:00:00Z",
                    "cwd": cwd,
                    "originator": "Codex Desktop",
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-06-12T10:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<user_instructions>blob</user_instructions>",
                        }
                    ],
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-06-12T10:00:02Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": title},
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _touch(path, hours_ago=hours_ago)
    return path


def test_scan_claude_basic(tmp_path: Path) -> None:
    _write_claude_session(tmp_path, hours_ago=0.01)
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.tool == "claude"
    assert s.session_id == "abc-123"
    assert s.workspace == "/Users/w/proj"
    assert s.title == "fix the bug"
    assert s.active is True
    assert s.resume_command == "cd /Users/w/proj && claude --resume abc-123"


def test_scan_claude_old_file_skipped(tmp_path: Path) -> None:
    _write_claude_session(tmp_path, hours_ago=100)
    assert scan_claude_sessions(tmp_path, within_hours=72, now=NOW) == []


def test_scan_claude_idle_not_active(tmp_path: Path) -> None:
    _write_claude_session(tmp_path, hours_ago=1)
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert sessions[0].active is False


def test_scan_claude_workspace_fallback_to_dir_name(tmp_path: Path) -> None:
    _write_claude_session(tmp_path, project="-Users-w-other", cwd=None)
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert sessions[0].workspace == "/Users/w/other"


def test_claude_title_prefers_summary(tmp_path: Path) -> None:
    summary = json.dumps({"type": "summary", "summary": "Radar design session"})
    _write_claude_session(tmp_path, extra_lines=[summary])
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert sessions[0].title == "Radar design session"


def test_claude_title_uses_queue_operation_content(tmp_path: Path) -> None:
    queued = json.dumps(
        {
            "type": "queue-operation",
            "operation": "enqueue",
            "sessionId": "abc-123",
            "content": "queued prompt wins over user line",
        }
    )
    _write_claude_session(tmp_path, extra_lines=[queued])
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert sessions[0].title == "queued prompt wins over user line"


def test_claude_title_skips_command_and_caveat_messages(tmp_path: Path) -> None:
    project_dir = tmp_path / "-Users-w-proj"
    project_dir.mkdir(parents=True)
    path = project_dir / "xyz-1.jsonl"
    lines = [
        json.dumps(
            {
                "type": "user",
                "sessionId": "xyz-1",
                "cwd": "/Users/w/proj",
                "message": {
                    "role": "user",
                    "content": "<command-name>/foo</command-name>",
                },
            }
        ),
        json.dumps(
            {
                "type": "user",
                "sessionId": "xyz-1",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "real prompt"}],
                },
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _touch(path, hours_ago=0.01)
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert sessions[0].title == "real prompt"


def test_scan_claude_skips_agent_sidechain_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "-Users-w-proj"
    project_dir.mkdir(parents=True)
    path = project_dir / "agent-123.jsonl"
    path.write_text(
        json.dumps({"type": "user", "sessionId": "agent-123", "cwd": "/Users/w/proj"}) + "\n",
        encoding="utf-8",
    )
    _touch(path, hours_ago=0.01)
    assert scan_claude_sessions(tmp_path, within_hours=72, now=NOW) == []


def test_scan_claude_ignores_subagent_subdirectories(tmp_path: Path) -> None:
    subagents = tmp_path / "-Users-w-proj" / "abc-123" / "subagents"
    subagents.mkdir(parents=True)
    side = subagents / "agent-deadbeef.jsonl"
    side.write_text(
        json.dumps({"type": "user", "sessionId": "abc-123", "cwd": "/Users/w/proj"}) + "\n",
        encoding="utf-8",
    )
    _touch(side, hours_ago=0.01)
    assert scan_claude_sessions(tmp_path, within_hours=72, now=NOW) == []


def test_scan_claude_garbage_does_not_crash(tmp_path: Path) -> None:
    project_dir = tmp_path / "-Users-w-proj"
    project_dir.mkdir(parents=True)
    bad = project_dir / "bad-1.jsonl"
    bad.write_bytes(b"\xff\xfenot json\n{broken\n")
    _touch(bad, hours_ago=0.01)
    assert scan_claude_sessions(tmp_path, within_hours=72, now=NOW) == []


def test_scan_claude_reads_only_head_of_huge_file(tmp_path: Path) -> None:
    path = _write_claude_session(tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        junk = json.dumps({"type": "assistant", "noise": "x" * 1000})
        for _ in range(5000):
            fh.write(junk + "\n")
    _touch(path, hours_ago=0.01)
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert sessions[0].session_id == "abc-123"


def test_scan_codex_basic(tmp_path: Path) -> None:
    _write_codex_session(tmp_path)
    sessions = scan_codex_sessions(tmp_path, within_hours=72, now=NOW)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.tool == "codex"
    assert s.session_id == "019e-codex-1"
    assert s.workspace == "/Users/w/proj"
    assert s.title == "refactor pipeline"
    assert s.source == "Codex Desktop"
    assert s.resume_command == "cd /Users/w/proj && codex resume 019e-codex-1"


def test_scan_codex_old_pruned(tmp_path: Path) -> None:
    _write_codex_session(tmp_path, hours_ago=100)
    assert scan_codex_sessions(tmp_path, within_hours=72, now=NOW) == []


def test_resume_command_quotes_workspace_with_spaces(tmp_path: Path) -> None:
    _write_claude_session(tmp_path, cwd="/Users/w/my proj")
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert "'/Users/w/my proj'" in sessions[0].resume_command


def test_scan_live_sessions_merges_sorts_limits(tmp_path: Path) -> None:
    claude_root = tmp_path / "claude"
    codex_root = tmp_path / "codex"
    _write_claude_session(claude_root, hours_ago=2)
    _write_codex_session(codex_root, hours_ago=1)
    sessions, errors = scan_live_sessions(
        {"claude": claude_root, "codex": codex_root},
        within_hours=72,
        limit=1,
        now=NOW,
    )
    assert errors == []
    assert len(sessions) == 1
    assert sessions[0].tool == "codex"  # newer first


def test_scan_live_sessions_missing_roots_ok(tmp_path: Path) -> None:
    sessions, errors = scan_live_sessions(
        {"claude": tmp_path / "nope", "codex": tmp_path / "nope2"},
        within_hours=72,
        now=NOW,
    )
    assert sessions == []
    assert errors == []


def test_build_open_terminal_command_valid(tmp_path: Path) -> None:
    argv = build_open_terminal_command("claude", "abc-123", str(tmp_path))
    assert argv[0] == "osascript"
    script = argv[2]
    assert "claude --resume abc-123" in script
    assert str(tmp_path) in script


def test_build_open_terminal_rejects_bad_tool(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_open_terminal_command("rm-rf", "abc-123", str(tmp_path))


def test_build_open_terminal_rejects_bad_session_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_open_terminal_command("claude", 'abc"; rm -rf /', str(tmp_path))


def test_build_open_terminal_rejects_missing_workspace(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_open_terminal_command("claude", "abc-123", str(tmp_path / "missing"))


def test_scan_claude_skips_hidden_dir_workspaces(tmp_path: Path) -> None:
    _write_claude_session(
        tmp_path,
        project="-Users-w--claude-mem-observer-sessions",
        cwd="/Users/w/.claude-mem/observer-sessions",
    )
    assert scan_claude_sessions(tmp_path, within_hours=72, now=NOW) == []


def test_scan_codex_skips_hidden_dir_workspaces(tmp_path: Path) -> None:
    _write_codex_session(tmp_path, cwd="/Users/w/.hidden/infra")
    assert scan_codex_sessions(tmp_path, within_hours=72, now=NOW) == []


def test_decode_claude_project_dir_double_dash_is_hidden_dir(tmp_path: Path) -> None:
    # "/Users/w/.claude-mem/observer-sessions" encodes to
    # "-Users-w--claude-mem-observer-sessions"; without a cwd key the
    # fallback decode must still mark it hidden and exclude it.
    project_dir = tmp_path / "-Users-w--claude-mem-observer-sessions"
    project_dir.mkdir(parents=True)
    path = project_dir / "obs-1.jsonl"
    path.write_text(
        json.dumps({"type": "user", "sessionId": "obs-1"}) + "\n",
        encoding="utf-8",
    )
    _touch(path, hours_ago=0.01)
    assert scan_claude_sessions(tmp_path, within_hours=72, now=NOW) == []


def test_scan_codex_finds_title_after_giant_session_meta(tmp_path: Path) -> None:
    day_dir = tmp_path / "2026" / "06" / "12"
    day_dir.mkdir(parents=True)
    path = day_dir / "rollout-2026-06-12T10-00-00-big-meta-1.jsonl"
    lines = [
        json.dumps(
            {
                "timestamp": "2026-06-12T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "big-meta-1",
                    "cwd": "/Users/w/proj",
                    "originator": "vscode",
                    "base_instructions": {"text": "x" * 120_000},
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-06-12T10:00:02Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "the real prompt"},
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _touch(path, hours_ago=0.01)
    sessions = scan_codex_sessions(tmp_path, within_hours=72, now=NOW)
    assert len(sessions) == 1
    assert sessions[0].title == "the real prompt"


def test_codex_title_skips_agents_md_injection(tmp_path: Path) -> None:
    day_dir = tmp_path / "2026" / "06" / "12"
    day_dir.mkdir(parents=True)
    path = day_dir / "rollout-2026-06-12T10-00-00-inj-1.jsonl"
    lines = [
        json.dumps(
            {
                "type": "session_meta",
                "payload": {"id": "inj-1", "cwd": "/Users/w/proj"},
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "# AGENTS.md instructions for /Users/w/proj\nblah",
                        }
                    ],
                },
            }
        ),
        json.dumps(
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "actual ask"},
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _touch(path, hours_ago=0.01)
    sessions = scan_codex_sessions(tmp_path, within_hours=72, now=NOW)
    assert sessions[0].title == "actual ask"
