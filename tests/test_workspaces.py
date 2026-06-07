from __future__ import annotations

from pathlib import Path

from agentic_os.workspaces import WorkspaceStore
from test_api import make_client

GATEWAY_HEADERS = {"X-Agentic-OS-Gateway": "1"}


def test_workspace_store_tracks_active_and_recent(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    store = WorkspaceStore(tmp_path / "state.db")
    store.init()

    first = store.set_active(str(repo_a))
    second = store.set_active(str(repo_b))

    assert first.path == str(repo_a.resolve())
    assert second.path == str(repo_b.resolve())
    assert store.get_active() == str(repo_b.resolve())
    paths = [record.path for record in store.list_workspaces()]
    assert str(repo_a.resolve()) in paths
    assert str(repo_b.resolve()) in paths


def test_workspace_api_lists_and_sets_active(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    client = make_client(tmp_path)

    created = client.post("/workspaces", json={"path": str(repo), "set_active": True})
    assert created.status_code == 200

    listed = client.get("/workspaces")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["active"] == str(repo.resolve())
    assert any(item["path"] == str(repo.resolve()) for item in payload["workspaces"])


def test_workspace_write_rejects_gateway_client(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    client = make_client(tmp_path)

    response = client.post(
        "/workspaces",
        headers=GATEWAY_HEADERS,
        json={"path": str(repo), "set_active": True},
    )
    assert response.status_code == 403


def test_workspace_dashboard_reports_profile_and_sessions(tmp_path: Path, monkeypatch) -> None:
    from agentic_os import profiles as profiles_module

    repo = tmp_path / "repo"
    repo.mkdir()
    profile_dir = tmp_path / "profiles-home" / ".agentic-os"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profiles.toml").write_text(
        f"""
[run_profiles.default]
harness_id = "shell"
provider = "local"
model = "dash-model"
message_prefix = ""
default_env = {{}}

[[project_profiles]]
project_path = "{repo.resolve()}"
run_profile = "default"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        profiles_module,
        "global_profile_path",
        lambda: profile_dir / "profiles.toml",
    )
    monkeypatch.setattr(
        profiles_module,
        "local_profile_path",
        lambda _cwd: tmp_path / "missing-local" / "profiles.toml",
    )

    client = make_client(tmp_path)
    client.post("/workspaces", json={"path": str(repo), "set_active": True})
    client.post("/sessions", json={"agent_id": "shell", "cwd": str(repo), "message": "OK"})

    dashboard = client.get("/workspaces/dashboard", params={"cwd": str(repo)})
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["active_profile"] == "default"
    assert body["model"] == "dash-model"
    assert body["sessions"]["total"] >= 1
