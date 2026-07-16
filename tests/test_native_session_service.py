from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from agentic_os.models import AgentDefinition
from agentic_os.native_session_service import NativeSessionService

NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)


def _write_claude_session(
    root: Path,
    *,
    session_id: str,
    workspace: str = "/Users/w/proj",
    hours_ago: float = 0.01,
) -> Path:
    project_dir = root / "-Users-w-proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{session_id}.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": session_id,
                "cwd": workspace,
                "timestamp": "2026-06-12T10:00:00Z",
                "message": {"role": "user", "content": f"work on {session_id}"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    timestamp = NOW.timestamp() - hours_ago * 3600
    os.utime(path, (timestamp, timestamp))
    return path


def test_workspace_filter_preserves_radar_identity(tmp_path: Path) -> None:
    claude_root = tmp_path / "claude"
    _write_claude_session(claude_root, session_id="abc-123")
    service = NativeSessionService(
        roots={"claude": claude_root, "codex": tmp_path / "codex"}
    )

    radar = service.scan(within_hours=72, limit=20, now=NOW)
    project = service.scan(
        workspace="/Users/w/proj",
        within_hours=72,
        limit=20,
        now=NOW,
    )

    assert [item.identity for item in radar.sessions] == [
        item.identity for item in project.sessions
    ]
    assert project.sessions[0].environment_id == "claude"


def test_scan_enforces_one_global_file_budget(tmp_path: Path) -> None:
    claude_root = tmp_path / "claude"
    for index in range(40):
        _write_claude_session(claude_root, session_id=f"session-{index:03d}")

    scan = NativeSessionService(
        roots={"claude": claude_root, "codex": tmp_path / "codex"},
        max_files=25,
    ).scan(within_hours=72, limit=100, now=NOW)

    assert scan.files_examined == 25
    assert len(scan.sessions) <= 25


def test_registered_log_discovery_is_normalized_by_same_service(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log_root = tmp_path / "logs"
    log_root.mkdir()
    log_path = log_root / "external.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "session_id": "external-1",
                "cwd": str(workspace),
                "timestamp": "2026-06-12T10:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    agent = AgentDefinition(
        id="claude",
        label="Claude Code",
        command=["claude"],
        log_paths=[str(log_root)],
        tool_kind="vibe_coding",
    )
    service = NativeSessionService(
        roots={"claude": tmp_path / "native", "codex": tmp_path / "codex"},
        agents_provider=lambda: [agent],
    )

    scan = service.scan(workspace=str(workspace), include_registered=True, now=NOW)

    assert [(item.identity, item.log_path) for item in scan.sessions] == [
        ("claude:external-1", str(log_path))
    ]


def test_known_log_path_requires_matching_environment_root(tmp_path: Path) -> None:
    claude_root = tmp_path / "claude"
    log_path = _write_claude_session(claude_root, session_id="abc-123")
    service = NativeSessionService(
        roots={"claude": claude_root, "codex": tmp_path / "codex"}
    )

    assert service.is_known_log_path("claude", log_path) is True
    assert service.is_known_log_path("codex", log_path) is False
