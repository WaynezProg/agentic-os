from __future__ import annotations

from pathlib import Path

import tomllib

from test_api import make_client, write_registry


def test_registry_create_appears_after_reload(tmp_path: Path) -> None:
    registry = tmp_path / "agents.toml"
    write_registry(registry)
    client = make_client(tmp_path)

    response = client.post(
        "/registry/agents",
        json={
            "id": "demo",
            "label": "Demo Agent",
            "command": ["/usr/bin/printf", "{{message}}"],
            "cwd_mode": "optional",
            "health_command": ["/usr/bin/printf", "OK"],
            "version_command": ["/usr/bin/printf", "1.0.0"],
            "config_fingerprint_command": ["/usr/bin/printf", "static"],
            "config_path": "~/.demo",
            "default_provider": "demo",
            "enabled": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["applied"] is True

    listed = client.get("/agents")
    ids = {agent["id"] for agent in listed.json()["agents"]}
    assert "demo" in ids


def test_registry_invalid_instance_rejected(tmp_path: Path) -> None:
    registry = tmp_path / "agents.toml"
    write_registry(registry)
    client = make_client(tmp_path)

    response = client.post(
        "/registry/agents",
        json={
            "id": "bad",
            "label": "Bad Agent",
            "command": ["/usr/bin/printf", "{{message}}"],
            "cwd_mode": "optional",
        },
    )
    assert response.status_code == 422
    assert "validation_errors" in response.json()["detail"]


def test_registry_disable_and_rollback(tmp_path: Path) -> None:
    registry = tmp_path / "agents.toml"
    write_registry(registry)
    client = make_client(tmp_path)

    client.post(
        "/registry/agents",
        json={
            "id": "demo2",
            "label": "Demo Two",
            "command": ["/usr/bin/printf", "{{message}}"],
            "cwd_mode": "optional",
            "health_command": ["/usr/bin/printf", "OK"],
            "version_command": ["/usr/bin/printf", "1.0.0"],
            "config_fingerprint_command": ["/usr/bin/printf", "static"],
            "config_path": "~/.demo2",
            "default_provider": "demo",
            "enabled": True,
        },
    )

    disabled = client.post("/registry/agents/demo2/disable")
    assert disabled.status_code == 200
    patch_id = disabled.json()["patch_id"]

    agents = client.get("/agents").json()["agents"]
    demo = next(agent for agent in agents if agent["id"] == "demo2")
    assert demo["enabled"] is False

    rollback = client.post(f"/patches/{patch_id}/rollback")
    assert rollback.status_code == 200

    agents_after = client.get("/agents").json()["agents"]
    demo_after = next(agent for agent in agents_after if agent["id"] == "demo2")
    assert demo_after["enabled"] is True

    raw = tomllib.loads(registry.read_text(encoding="utf-8"))
    demo_row = next(row for row in raw["agents"] if row["id"] == "demo2")
    assert demo_row["enabled"] is True


def test_registry_schema_endpoint(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/registry/schema")
    assert response.status_code == 200
    assert response.json()["cwd_mode"] == ["required", "optional", "ignored"]


def test_registry_writes_only_via_engine(tmp_path: Path) -> None:
    registry = tmp_path / "agents.toml"
    write_registry(registry)
    client = make_client(tmp_path)

    client.post(
        "/registry/agents",
        json={
            "id": "tracked",
            "label": "Tracked",
            "command": ["/usr/bin/printf", "{{message}}"],
            "cwd_mode": "optional",
            "health_command": ["/usr/bin/printf", "OK"],
            "version_command": ["/usr/bin/printf", "1.0.0"],
            "config_fingerprint_command": ["/usr/bin/printf", "static"],
            "config_path": "~/.tracked",
            "default_provider": "demo",
        },
    )

    patches = client.get("/patches", params={"harness": "agentic_os"})
    kinds = {entry["target_kind"] for entry in patches.json()["patches"]}
    assert "registry" in kinds
