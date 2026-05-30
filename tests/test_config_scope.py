"""Tests for the configuration scope mapper."""

from __future__ import annotations

import json
from pathlib import Path

from agentic_os.config_scope import diff, effective, explain, read_config


def _write_config(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"[{key}]")
            for k, v in value.items():
                lines.append(f'{k} = "{v}"')
        elif isinstance(value, list):
            items = ", ".join(json.dumps(x) for x in value)
            lines.append(f"{key} = [{items}]")
        elif isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
        else:
            lines.append(f'{key} = "{value}"')
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_read_config_missing() -> None:
    """read_config returns empty dict for missing file."""
    assert read_config(Path("/nonexistent/config.toml")) == {}


def test_effective_empty_cwd(tmp_path: Path) -> None:
    """effective returns empty view when no config files exist."""
    view = effective("test", cwd=str(tmp_path))
    assert view.harness_id == "test"
    assert view.entries == []


def test_effective_user_scope(tmp_path: Path) -> None:
    """effective reads user scope config."""
    home = tmp_path / "home"
    _write_config(home / ".agentic-os" / "config.toml", {"theme": "dark"})
    project = tmp_path / "project"
    view = effective("test", cwd=str(project), home_dir=home)
    entries = [e for e in view.entries if e.key == "theme"]
    assert len(entries) == 1
    assert entries[0].scope == "user"
    assert entries[0].value == "dark"


def test_effective_project_overrides_user(tmp_path: Path) -> None:
    """effective: project scope overrides user for same key."""
    home = tmp_path / "home"
    project = tmp_path / "project"

    _write_config(home / ".agentic-os" / "config.toml", {"theme": "dark"})
    _write_config(project / ".agentic-os" / "config.toml", {"theme": "light"})

    view = effective("test", cwd=str(project), home_dir=home)
    entries = [e for e in view.entries if e.key == "theme"]
    assert len(entries) == 1
    assert entries[0].scope == "project"
    assert entries[0].value == "light"


def test_effective_local_overrides_project(tmp_path: Path) -> None:
    """effective: local scope overrides project for same key."""
    project = tmp_path / "project"
    _write_config(project / ".agentic-os" / "config.toml", {"theme": "light"})
    _write_config(project / ".agentic-os.local" / "config.toml", {"theme": "auto"})

    view = effective("test", cwd=str(project))
    entries = [e for e in view.entries if e.key == "theme"]
    assert len(entries) == 1
    assert entries[0].scope == "local"
    assert entries[0].value == "auto"


def test_diff_added_removed(tmp_path: Path) -> None:
    """diff detects added and removed keys between scopes."""
    project = tmp_path / "project"
    _write_config(project / ".agentic-os" / "config.toml", {"key_a": "a", "key_b": "b"})
    _write_config(project / ".agentic-os.local" / "config.toml", {"key_b": "b2", "key_c": "c"})

    result = diff("test", cwd=str(project), scope_a="project", scope_b="local")
    added_keys = {item["key"] for item in result["added"]}
    assert "key_c" in added_keys
    removed_keys = {item["key"] for item in result["removed"]}
    assert "key_a" in removed_keys


def test_diff_no_changes() -> None:
    """diff returns empty when scopes have same content."""
    result = diff("test", cwd=None, scope_a="user", scope_b="user")
    assert result["added"] == []
    assert result["removed"] == []
    assert result["modified"] == []


def test_explain_returns_entries(tmp_path: Path) -> None:
    """explain returns entries with source info."""
    project = tmp_path / "project"
    _write_config(project / ".agentic-os" / "config.toml", {"key": "value"})
    entries = explain("test", cwd=str(project))
    assert isinstance(entries, list)
    for entry in entries:
        assert "key" in entry
        assert "scope" in entry
        assert "source" in entry
