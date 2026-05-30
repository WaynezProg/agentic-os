"""Tests for the workflow surface catalog scanner."""

from __future__ import annotations

import json
from pathlib import Path

from agentic_os.catalog import SUPPORTED_HARNESSES, SurfaceRecord, diff, merge, scan


def _write_claude_settings(base: Path, data: dict) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "settings.json").write_text(json.dumps(data), encoding="utf-8")
    return base


def _write_command(base: Path, name: str, content: str = "") -> Path:
    cmd_dir = base / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    (cmd_dir / f"{name}.md").write_text(content, encoding="utf-8")
    return cmd_dir


def _write_skill(base: Path, name: str, content: str = "") -> Path:
    skill_dir = base / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


def _write_subagent(base: Path, name: str, content: str = "") -> Path:
    agents_dir = base / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{name}.md").write_text(content, encoding="utf-8")
    return agents_dir


def test_supported_harnesses_includes_six() -> None:
    assert set(SUPPORTED_HARNESSES) == {
        "claude",
        "codex",
        "opencode",
        "qwen",
        "openclaw",
        "hermes",
    }


def test_scan_openclaw_toml_config(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    oc = home / ".openclaw"
    oc.mkdir(parents=True)
    (oc / "config.toml").write_text('[agent]\nname = "main"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    records = scan("openclaw", str(tmp_path), home_dir=home)
    assert len(records) >= 1
    assert any(record.type == "permission" for record in records)


def test_scan_empty_cwd(tmp_path: Path) -> None:
    """Scanning a directory with no harness dirs returns empty."""
    records = scan("claude", cwd=str(tmp_path), home_dir=tmp_path)
    assert records == []


def test_scan_unsupported_harness() -> None:
    """Scanning an unsupported harness returns empty."""
    records = scan("unknown")
    assert records == []


def test_scan_hooks_from_settings(tmp_path: Path) -> None:
    """Hooks in settings.json are detected."""
    home = tmp_path / "home"
    _write_claude_settings(
        home / ".claude",
        {
            "hooks": {
                "PreToolUse": {"type": "regex", "regex": ".*"},
                "PostToolUse": {"type": "exact", "tool": "Bash"},
            }
        },
    )
    records = scan("claude", cwd=str(tmp_path / "project"), home_dir=home)
    hook_records = [r for r in records if r.type == "hook"]
    assert len(hook_records) == 2
    names = {r.name for r in hook_records}
    assert "PreToolUse" in names
    assert "PostToolUse" in names


def test_scan_mcp_servers_from_settings(tmp_path: Path) -> None:
    """MCP servers in settings.json are detected."""
    home = tmp_path / "home"
    _write_claude_settings(
        home / ".claude",
        {
            "mcpServers": {
                "filesystem": {"command": ["mcp-server"]},
                "web": {"url": "http://localhost:8080"},
            }
        },
    )
    records = scan("claude", cwd=str(tmp_path / "project"), home_dir=home)
    mcp_records = [r for r in records if r.type == "mcp_server"]
    assert len(mcp_records) == 2


def test_scan_permissions_from_settings(tmp_path: Path) -> None:
    """Permissions in settings.json are detected."""
    home = tmp_path / "home"
    _write_claude_settings(
        home / ".claude",
        {
            "permissions": {
                "allow_read": {"action": "allow", "pattern": "*.txt"},
            }
        },
    )
    records = scan("claude", cwd=str(tmp_path / "project"), home_dir=home)
    perm_records = [r for r in records if r.type == "permission"]
    assert len(perm_records) == 1
    assert perm_records[0].name == "allow_read"


def test_scan_subagents_from_settings(tmp_path: Path) -> None:
    """CustomAgents in settings.json are detected."""
    home = tmp_path / "home"
    _write_claude_settings(
        home / ".claude",
        {
            "customAgents": {
                "explorer": {"writePermission": True},
                "reviewer": {"writePermission": False},
            }
        },
    )
    records = scan("claude", cwd=str(tmp_path / "project"), home_dir=home)
    agent_records = [r for r in records if r.type == "subagent"]
    assert len(agent_records) == 2


def test_scan_commands_directory(tmp_path: Path) -> None:
    """Command files in commands/ directory are detected."""
    home = tmp_path / "home"
    _write_command(home / ".claude", "graphify", "# Generate a knowledge graph\n")
    records = scan("claude", cwd=str(tmp_path / "project"), home_dir=home)
    cmd_records = [r for r in records if r.type == "command"]
    assert len(cmd_records) == 1
    assert cmd_records[0].name == "graphify"
    assert cmd_records[0].metadata["description"] == "Generate a knowledge graph"


def test_scan_skills_directory(tmp_path: Path) -> None:
    """Skill directories with SKILL.md are detected."""
    home = tmp_path / "home"
    _write_skill(
        home / ".claude", "graphify", "---\n---\n# Graphify\nAny input to knowledge graph\n"
    )
    records = scan("claude", cwd=str(tmp_path / "project"), home_dir=home)
    skill_records = [r for r in records if r.type == "skill"]
    assert len(skill_records) == 1
    assert skill_records[0].name == "graphify"


def test_scan_agents_directory(tmp_path: Path) -> None:
    """Agent files in agents/ directory are detected."""
    _write_subagent(tmp_path / ".claude", "explorer", "# explorer agent\n")
    records = scan("claude", cwd=str(tmp_path))
    agent_records = [r for r in records if r.type == "subagent"]
    assert len(agent_records) == 1
    assert agent_records[0].name == "explorer"


def test_scan_multiple_scopes(tmp_path: Path) -> None:
    """Scanning user, project, and local scopes returns records from all."""
    _write_claude_settings(tmp_path / "user-claude", {"hooks": {"PreToolUse": {}}})
    _write_claude_settings(tmp_path / "project-claude", {"hooks": {"PostToolUse": {}}})

    records = scan("claude", cwd=str(tmp_path))
    hook_records = [r for r in records if r.type == "hook"]
    # User scope is always scanned (home directory)
    assert len(hook_records) >= 1


def test_merge_no_conflicts() -> None:
    """Merge with no overlapping surfaces returns all records."""
    records = [
        SurfaceRecord("hook:a@user", "hook", "a", "user", "claude", "/a", True),
        SurfaceRecord("hook:b@user", "hook", "b", "user", "claude", "/b", True),
    ]
    result = merge(records)
    assert len(result) == 2


def test_merge_local_overrides_user() -> None:
    """Local scope overrides user scope for same surface."""
    records = [
        SurfaceRecord("hook:a@user", "hook", "a", "user", "claude", "/user/a", True),
        SurfaceRecord("hook:a@local", "hook", "a", "local", "claude", "/local/a", True),
    ]
    result = merge(records)
    winners = [r for r in result if r.scope == "local" and r.overrides]
    overridden = [r for r in result if r.scope == "user" and r.overridden_by]
    assert len(winners) == 1
    assert len(overridden) == 1
    assert overridden[0].overridden_by == "local"


def test_diff_added_and_removed() -> None:
    """Diff detects added and removed surfaces."""
    a = [SurfaceRecord("hook:a@user", "hook", "a", "user", "claude", "/a", True)]
    b = [SurfaceRecord("hook:b@user", "hook", "b", "user", "claude", "/b", True)]
    result = diff(a, b)
    assert len(result["added"]) == 1
    assert result["added"][0]["name"] == "b"
    assert len(result["removed"]) == 1
    assert result["removed"][0]["name"] == "a"


def test_diff_no_changes() -> None:
    """Diff returns empty when surfaces are identical."""
    records = [SurfaceRecord("hook:a@user", "hook", "a", "user", "claude", "/a", True)]
    result = diff(records, records)
    assert result["added"] == []
    assert result["removed"] == []
    assert result["modified"] == []


def test_command_description_from_heading() -> None:
    """Command description is extracted from heading."""
    tmp = Path("/tmp/test_catalog_heading")
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / "graphify.md").write_text(
            "# Generate a knowledge graph\nDetails\n", encoding="utf-8"
        )
        from agentic_os.catalog import _extract_command_description

        desc = _extract_command_description(tmp / "graphify.md")
        assert desc == "Generate a knowledge graph"
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def test_skill_description_from_skill_md() -> None:
    """Skill description is extracted from SKILL.md heading after frontmatter."""
    tmp = Path("/tmp/test_skill_desc")
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / "SKILL.md").write_text(
            "---\nname: graphify\n---\n# Graphify\nAny input to knowledge graph\n",
            encoding="utf-8",
        )
        from agentic_os.catalog import _extract_skill_description

        desc = _extract_skill_description(tmp / "SKILL.md")
        assert desc == "Graphify"
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)
