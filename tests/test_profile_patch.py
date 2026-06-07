from __future__ import annotations

from pathlib import Path

import tomllib

from test_api import make_client


def test_delete_profile_removes_entry(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    created = client.post(
        "/profiles",
        params={"scope": "local", "cwd": str(repo)},
        json={
            "name": "dev",
            "harness_id": "cursor",
            "provider": "cursor",
            "model": "default",
        },
    )
    assert created.status_code == 201

    deleted = client.delete(
        "/profiles/dev",
        params={"scope": "local", "cwd": str(repo)},
    )
    assert deleted.status_code == 200
    assert deleted.json()["applied"] is True
    patch_id = deleted.json()["patch_id"]

    listed = client.get("/profiles", params={"cwd": str(repo)})
    names = {item["name"] for item in listed.json()["run_profiles"]}
    assert "dev" not in names

    patches = client.get("/patches", params={"harness": "agentic_os"})
    patch_ids = {entry["patch_id"] for entry in patches.json()["patches"]}
    assert patch_id in patch_ids


def test_delete_bound_profile_returns_409(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    client.post(
        "/profiles",
        params={"scope": "local", "cwd": str(repo)},
        json={
            "name": "bound",
            "harness_id": "shell",
            "provider": "local",
            "model": "local",
        },
    )
    bind = client.post(
        f"/projects/{repo}/bind-profile",
        json={"run_profile": "bound"},
    )
    assert bind.status_code == 200

    blocked = client.delete(
        "/profiles/bound",
        params={"scope": "local", "cwd": str(repo)},
    )
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["error"] == "bound"
    assert str(repo.resolve()) in detail["projects"]


def test_delete_profile_cascade_clears_bindings(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    client.post(
        "/profiles",
        params={"scope": "local", "cwd": str(repo)},
        json={
            "name": "gone",
            "harness_id": "shell",
            "provider": "local",
            "model": "local",
        },
    )
    client.post(f"/projects/{repo}/bind-profile", json={"run_profile": "gone"})

    deleted = client.delete(
        "/profiles/gone",
        params={"scope": "local", "cwd": str(repo), "cascade": "true"},
    )
    assert deleted.status_code == 200

    listed = client.get("/profiles", params={"cwd": str(repo)})
    body = listed.json()
    assert "gone" not in {item["name"] for item in body["run_profiles"]}
    assert body["project_bindings"] == []


def test_profile_delete_rollback_restores_bundle(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    client.post(
        "/profiles",
        params={"scope": "local", "cwd": str(repo)},
        json={
            "name": "rollback-me",
            "harness_id": "cursor",
            "provider": "cursor",
            "model": "default",
        },
    )
    deleted = client.delete(
        "/profiles/rollback-me",
        params={"scope": "local", "cwd": str(repo)},
    )
    patch_id = deleted.json()["patch_id"]

    rollback = client.post(f"/patches/{patch_id}/rollback")
    assert rollback.status_code == 200

    listed = client.get("/profiles", params={"cwd": str(repo)})
    names = {item["name"] for item in listed.json()["run_profiles"]}
    assert "rollback-me" in names


def test_profile_upsert_writes_via_engine(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    client.post(
        "/profiles",
        params={"scope": "local", "cwd": str(repo)},
        json={
            "name": "engine",
            "harness_id": "shell",
            "provider": "local",
            "model": "local",
            "default_env": {"MY_TOKEN": "should-not-appear"},
        },
    )

    preview = client.post(
        "/profiles",
        params={"scope": "local", "cwd": str(repo), "dry_run": "true"},
        json={
            "name": "engine",
            "harness_id": "shell",
            "provider": "openai",
            "model": "gpt-4",
            "default_env": {"MY_TOKEN": "should-not-appear"},
        },
    )
    assert preview.status_code == 201
    assert preview.json()["applied"] is False
    assert preview.json()["base_mtime"] is not None

    profile_path = repo / ".agentic-os" / "profiles.toml"
    parsed = tomllib.loads(profile_path.read_text(encoding="utf-8"))
    assert parsed["run_profiles"]["engine"]["harness_id"] == "shell"
    assert parsed["run_profiles"]["engine"]["default_env"] == {"MY_TOKEN": "should-not-appear"}


def test_profile_scope_diff(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    client.post(
        "/profiles",
        params={"scope": "local", "cwd": str(repo)},
        json={
            "name": "local-only",
            "harness_id": "shell",
            "provider": "local",
            "model": "local",
        },
    )

    diff = client.get(
        "/profiles/local-only/diff",
        params={"scope": "local", "other_scope": "global", "cwd": str(repo)},
    )
    assert diff.status_code == 200
    body = diff.json()
    assert body["name"] == "local-only"
    assert body["before"]["harness_id"] == "shell"
    assert body["after"] is None
