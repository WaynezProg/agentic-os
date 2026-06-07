from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agentic_os.import_export import bundle_has_no_secret_values
from test_api import make_client


def _seed_setup(client, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMPORT_TEST_TOKEN", "super-secret-value")

    client.post(
        "/skills/demo-skill",
        json={
            "label": "Demo Skill",
            "description": "for import/export",
            "source": "local",
            "entrypoint": "skills/demo",
            "tags": ["demo"],
            "enabled": True,
        },
    )
    client.post(
        "/mcp/demo-mcp",
        json={
            "label": "Demo MCP",
            "description": "stdio server",
            "transport": "stdio",
            "command_preview": ["npx", "-y", "@demo/mcp", "--token", "live-token"],
            "env_keys": ["IMPORT_TEST_TOKEN"],
            "enabled": True,
        },
    )
    client.post(
        "/policy/shell",
        json={
            "enabled": True,
            "readonly": False,
            "allowed_skill_ids": ["demo-skill"],
            "allowed_mcp_server_ids": ["demo-mcp"],
            "allowed_tool_names": ["*"],
            "approval_required_tool_names": [],
            "allowed_model_ids": ["*"],
            "cwd_roots": [str(repo)],
            "rate_limit_per_minute": 60,
        },
    )
    client.post(
        "/profiles",
        params={"scope": "local", "cwd": str(repo)},
        json={
            "name": "imported-profile",
            "harness_id": "shell",
            "provider": "local",
            "model": "local",
            "default_env": {"IMPORT_TEST_TOKEN": "IMPORT_TEST_TOKEN"},
            "cwd_root": str(repo),
        },
    )
    client.post(
        f"/projects/{repo}/bind-profile",
        json={"run_profile": "imported-profile"},
    )

    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "gh": {
                        "command": "npx",
                        "args": ["-y", "@github/mcp"],
                        "env": {"GITHUB_TOKEN": "IMPORT_TEST_TOKEN"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_setup_export_contains_no_secret_values(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(
        "/mcp/secret-test",
        json={
            "label": "Secret MCP",
            "command_preview": ["mcp", "--token", "SUPER_SECRET"],
            "env_keys": ["MCP_TOKEN"],
        },
    )
    response = client.get("/setup/export", params={"cwd": str(tmp_path)})
    assert response.status_code == 200
    bundle = response.json()
    assert bundle_has_no_secret_values(bundle)
    assert "SUPER_SECRET" not in json.dumps(bundle)


def test_export_redacts_secrets_and_tokenizes_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_setup(client, repo, monkeypatch)

    response = client.get("/setup/export", params={"cwd": str(repo)})
    assert response.status_code == 200
    bundle = response.json()

    raw = json.dumps(bundle)
    assert "super-secret-value" not in raw
    assert "live-token" not in raw
    assert "[REDACTED]" in raw
    assert bundle_has_no_secret_values(bundle)

    mcp = next(item for item in bundle["mcp_servers"] if item["id"] == "demo-mcp")
    assert mcp["env_keys"] == ["IMPORT_TEST_TOKEN"]

    profile = next(item for item in bundle["profiles"]["run_profiles"] if item["name"] == "imported-profile")
    assert profile["default_env"] == {"IMPORT_TEST_TOKEN": "IMPORT_TEST_TOKEN"}
    assert profile["cwd_root"] == "${PROJECT_ROOT}"

    policy = next(item for item in bundle["policies"] if item["agent_id"] == "shell")
    assert policy["cwd_roots"] == ["${PROJECT_ROOT}"]

    binding = bundle["profiles"]["project_bindings"][0]
    assert binding["project_path"] == "${PROJECT_ROOT}"
    assert bundle["catalog_surfaces"].get("claude")
    assert bundle["catalog_ops"]


def test_import_dry_run_returns_diff_without_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_root = tmp_path / "source-daemon"
    target_root = tmp_path / "target-daemon"
    source_root.mkdir()
    target_root.mkdir()
    source_client = make_client(source_root)
    target_client = make_client(target_root)
    source_repo = source_root / "repo"
    target_repo = target_root / "repo"
    source_repo.mkdir()
    target_repo.mkdir()
    _seed_setup(source_client, source_repo, monkeypatch)

    bundle = source_client.get("/setup/export", params={"cwd": str(source_repo)}).json()

    dry_run = target_client.post(
        "/setup/import",
        params={"cwd": str(target_repo), "dry_run": "true"},
        json=bundle,
    )
    assert dry_run.status_code == 200
    body = dry_run.json()
    assert body["dry_run"] is True
    assert body["applied"] is False
    assert any(item.get("action") == "upsert" for item in body["items"])
    assert all(item.get("applied") is not True for item in body["items"])

    listed = target_client.get("/skills")
    assert "demo-skill" not in {skill["id"] for skill in listed.json()["skills"]}
    assert not (target_repo / ".agentic-os" / "profiles.toml").exists()


def test_import_apply_round_trip_with_patch_and_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source-daemon"
    target_root = tmp_path / "target-daemon"
    source_root.mkdir()
    target_root.mkdir()
    source_client = make_client(source_root)
    target_client = make_client(target_root)
    source_repo = source_root / "repo"
    target_repo = target_root / "repo"
    source_repo.mkdir()
    target_repo.mkdir()
    _seed_setup(source_client, source_repo, monkeypatch)

    bundle = source_client.get("/setup/export", params={"cwd": str(source_repo)}).json()

    applied = target_client.post(
        "/setup/import",
        params={"cwd": str(target_repo), "dry_run": "false"},
        json=bundle,
    )
    assert applied.status_code == 200
    body = applied.json()
    assert body["applied"] is True

    patch_items = [item for item in body["items"] if item.get("patch_id")]
    assert patch_items
    assert all(
        item.get("audit_event_id") is not None
        for item in patch_items
        if item["domain"] in {"skill", "mcp", "policy"}
    )

    skills = target_client.get("/skills").json()["skills"]
    assert any(skill["id"] == "demo-skill" for skill in skills)

    mcp_servers = target_client.get("/mcp").json()["servers"]
    demo_mcp = next(server for server in mcp_servers if server["id"] == "demo-mcp")
    assert demo_mcp["env_keys"] == ["IMPORT_TEST_TOKEN"]
    assert "super-secret-value" not in json.dumps(demo_mcp)

    profiles = target_client.get("/profiles", params={"cwd": str(target_repo)}).json()
    profile = next(p for p in profiles["run_profiles"] if p["name"] == "imported-profile")
    assert profile["default_env"]["IMPORT_TEST_TOKEN"] == os.environ["IMPORT_TEST_TOKEN"]
    assert Path(profile["cwd_root"]).resolve() == target_repo.resolve()

    settings = target_repo / ".claude" / "settings.json"
    assert settings.exists()
    settings_data = json.loads(settings.read_text(encoding="utf-8"))
    assert "gh" in settings_data.get("mcpServers", {})


def test_setup_import_dry_run_then_apply(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/skills/importer", json={"label": "Importer"})
    export = client.get("/setup/export", params={"cwd": str(tmp_path)}).json()
    client.post("/skills/importer/disable")

    dry = client.post(
        "/setup/import",
        params={"cwd": str(tmp_path), "dry_run": "true"},
        json=export,
    )
    assert dry.status_code == 200
    body = dry.json()
    assert body["dry_run"] is True
    assert body["items"]

    applied = client.post(
        "/setup/import",
        params={"cwd": str(tmp_path), "dry_run": "false"},
        json=export,
    )
    assert applied.status_code == 200
    applied_body = applied.json()
    assert applied_body["dry_run"] is False
    assert any(item.get("patch_id") for item in applied_body["items"])
    listed = client.get("/skills").json()["skills"]
    assert any(skill["id"] == "importer" for skill in listed)


def test_setup_import_fails_on_missing_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path)
    monkeypatch.delenv("MISSING_IMPORT_ENV", raising=False)
    bundle = {
        "version": 1,
        "skills": [],
        "mcp_servers": [
            {
                "id": "needs-env",
                "label": "Needs Env",
                "transport": "stdio",
                "command_preview": ["mcp"],
                "env_keys": ["MISSING_IMPORT_ENV"],
                "enabled": True,
            }
        ],
        "policies": [],
        "registry_agents": [],
        "profiles": {"run_profiles": [], "project_bindings": []},
        "catalog_surfaces": {},
        "catalog_ops": [],
    }
    response = client.post(
        "/setup/import",
        params={"cwd": str(tmp_path), "dry_run": "false"},
        json=bundle,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "missing_env_vars"
