"""Tests for harness-native configuration bridge."""

from __future__ import annotations

import json
from pathlib import Path

from agentic_os.harness_config import diff, effective, explain


def test_claude_effective_project_overrides_user(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    claude_home = home / ".claude"
    claude_home.mkdir(parents=True)
    (claude_home / "settings.json").write_text('{"model": "user-model"}', encoding="utf-8")
    project = tmp_path / "repo"
    project.mkdir()
    pc = project / ".claude"
    pc.mkdir()
    (pc / "settings.json").write_text('{"model": "project-model"}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    view = effective("claude", str(project), home_dir=home)
    models = [e.value for e in view.entries if e.key == "model"]
    assert models == ["project-model"]


def test_effective_redacts_secrets(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    claude_home = home / ".claude"
    claude_home.mkdir(parents=True)
    (claude_home / "settings.json").write_text(
        '{"api_key": "sk-secret-value"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    view = effective("claude", str(tmp_path), home_dir=home)
    raw = json.dumps([e.value for e in view.entries])
    assert "sk-secret-value" not in raw
    assert "REDACTED" in raw


def test_openclaw_effective_reads_toml(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    oc = home / ".openclaw"
    oc.mkdir(parents=True)
    (oc / "config.toml").write_text('[agent]\nname = "main"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    view = effective("openclaw", str(tmp_path), home_dir=home)
    assert "agent" in [e.key for e in view.entries]


def test_explain_returns_entries(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    claude_home = home / ".claude"
    claude_home.mkdir(parents=True)
    (claude_home / "settings.json").write_text('{"theme": "dark"}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    entries = explain("claude", str(tmp_path), home_dir=home)
    assert any(entry["key"] == "theme" for entry in entries)


def test_diff_added_removed(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text('{"only_user": true}', encoding="utf-8")
    pc = project / ".claude"
    pc.mkdir()
    (pc / "settings.json").write_text('{"only_project": true}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    result = diff("claude", str(project), scope_a="user", scope_b="project", home_dir=home)
    assert any(item["key"] == "only_project" for item in result["added"])
    assert any(item["key"] == "only_user" for item in result["removed"])
