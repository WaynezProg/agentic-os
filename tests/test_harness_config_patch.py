"""Tests for harness-native config patch (P10b)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from agentic_os.api import create_app
from agentic_os.harness_config import infer_patch_kind, resolve_write_path


def make_client(tmp_path: Path) -> TestClient:
    registry = tmp_path / "agents.toml"
    registry.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/usr/bin/printf", "%s", "{{message}}"]
cwd_mode = "optional"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )
    return TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))


def test_resolve_write_path_creates_parent_dirs(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    path, fmt = resolve_write_path("claude", "project", repo)
    assert path == repo / ".claude" / "settings.json"
    assert fmt == "json"
    assert path.parent.is_dir()


def test_resolve_write_path_cursor_file_name(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    path, fmt = resolve_write_path("cursor", "project", repo, file_name="mcp.json")
    assert path == repo / ".cursor" / "mcp.json"
    assert fmt == "json"
    assert infer_patch_kind("cursor", path) == "mcp_server"


def test_harness_config_patch_preserves_unknown_keys(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"model": "x", "extra": 1}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    client = make_client(tmp_path)
    response = client.post(
        "/harness-config/claude/patch",
        params={"cwd": str(repo), "scope": "project"},
        json={"ops": [{"op": "merge", "path": "mcpServers.gh", "value": {"command": "npx"}}]},
    )
    assert response.status_code == 200
    assert response.json()["applied"] is True
    assert response.json()["change_id"]
    assert response.json()["status"] == "verified"
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["model"] == "x"
    assert data["extra"] == 1
    assert data["mcpServers"]["gh"]["command"] == "npx"


def test_harness_config_patch_dry_run(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"model": "x"}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    client = make_client(tmp_path)
    response = client.post(
        "/harness-config/claude/patch",
        params={"cwd": str(repo), "scope": "project", "dry_run": "true"},
        json={"ops": [{"op": "merge", "path": "model", "value": "y"}]},
    )
    assert response.status_code == 200
    assert response.json()["applied"] is False
    assert response.json()["change_id"]
    assert response.json()["status"] == "previewed"
    assert json.loads(settings.read_text(encoding="utf-8"))["model"] == "x"
