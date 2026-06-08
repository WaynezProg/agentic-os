from __future__ import annotations

from pathlib import Path

import tomllib

from fastapi.testclient import TestClient

from agentic_os.api import create_app
from agentic_os.registry import Registry, apply_profile_launch, render_command
from agentic_os.models import AgentDefinition
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


def test_registry_rollback_reloads_with_noncanonical_registry_path(tmp_path: Path) -> None:
    # Regression: the in-memory Registry must reload after a /patches rollback even
    # when --registry was given as a non-canonical path (symlinked or relative). The
    # rollback guard compared the stored (unresolved) target_path against a resolved
    # registry_path, so reload silently never fired and list_agents stayed stale while
    # agents.toml on disk was correctly restored. pytest tmp_path is already canonical
    # on macOS, which masked it — force a symlinked path so the mismatch is real.
    real = tmp_path / "real"
    real.mkdir()
    registry = real / "agents.toml"
    write_registry(registry)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    registry_via_link = link / "agents.toml"
    client = TestClient(
        create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry_via_link)
    )

    client.post(
        "/registry/agents",
        json={
            "id": "demo3",
            "label": "Demo Three",
            "command": ["/usr/bin/printf", "{{message}}"],
            "cwd_mode": "optional",
            "health_command": ["/usr/bin/printf", "OK"],
            "version_command": ["/usr/bin/printf", "1.0.0"],
            "config_fingerprint_command": ["/usr/bin/printf", "static"],
            "config_path": "~/.demo3",
            "default_provider": "demo",
            "enabled": True,
        },
    )
    patch_id = client.post("/registry/agents/demo3/disable").json()["patch_id"]
    disabled = next(a for a in client.get("/agents").json()["agents"] if a["id"] == "demo3")
    assert disabled["enabled"] is False

    assert client.post(f"/patches/{patch_id}/rollback").status_code == 200

    after = next(a for a in client.get("/agents").json()["agents"] if a["id"] == "demo3")
    assert after["enabled"] is True  # list_agents must reflect the reloaded registry


def test_registry_schema_endpoint(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/registry/schema")
    assert response.status_code == 200
    assert response.json()["cwd_mode"] == ["required", "optional", "ignored"]


def test_render_command_substitutes_model_and_provider_when_present() -> None:
    argv = render_command(
        ["/usr/bin/printf", "m={{model}} p={{provider}}"],
        "hello",
        model="opus-4",
        provider="anthropic",
    )
    assert argv == ["/usr/bin/printf", "m=opus-4 p=anthropic"]


def test_render_command_leaves_model_placeholder_when_absent() -> None:
    argv = render_command(["/usr/bin/printf", "{{model}}"], "hello")
    assert argv == ["/usr/bin/printf", "{{model}}"]


def test_model_arg_appended_when_profile_model_present(tmp_path: Path) -> None:
    registry_path = tmp_path / "agents.toml"
    write_registry(
        registry_path,
        command=["/usr/bin/printf", "%s\\n", "{{message}}"],
        model_arg=["--model", "{{model}}"],
    )
    rendered = Registry(registry_path).build_run("shell", str(tmp_path), "OK", model="opus-4")
    assert rendered.argv == ["/usr/bin/printf", "%s\\n", "OK", "--model", "opus-4"]


def test_harness_without_model_arg_unchanged_by_profile_model(tmp_path: Path) -> None:
    registry_path = tmp_path / "agents.toml"
    write_registry(registry_path, command=["/usr/bin/printf", "%s\\n", "{{message}}"])
    rendered = Registry(registry_path).build_run("shell", str(tmp_path), "OK", model="opus-4")
    assert rendered.argv == ["/usr/bin/printf", "%s\\n", "OK"]


def test_provider_env_set_when_profile_provider_present(tmp_path: Path) -> None:
    agent = AgentDefinition(
        id="demo",
        label="Demo",
        command=["/usr/bin/printf", "{{message}}"],
        provider_env="TEST_PROVIDER",
    )
    argv, env = apply_profile_launch(
        agent,
        agent.command,
        "OK",
        model="opus-4",
        provider="anthropic",
    )
    assert argv == ["/usr/bin/printf", "OK"]
    assert env == {"TEST_PROVIDER": "anthropic"}


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


def test_agents_toml_has_tool_kind() -> None:
    """All non-shell agents should have tool_kind defined."""
    registry = Registry(Path("examples/agents.toml"))
    for agent in registry.list_agents():
        if agent.id == "shell":
            continue
        assert agent.tool_kind is not None, f"{agent.id} missing tool_kind"
        assert agent.tool_kind in ("vibe_coding", "agentic_runtime")


def test_tool_kind_mapping() -> None:
    """Verify expected tool_kind assignments."""
    registry = Registry(Path("examples/agents.toml"))
    agents = {a.id: a for a in registry.list_agents()}

    assert agents["claude"].tool_kind == "vibe_coding"
    assert agents["codex"].tool_kind == "vibe_coding"
    assert agents["cursor"].tool_kind == "vibe_coding"
    assert agents["openclaw"].tool_kind == "agentic_runtime"
    assert agents["hermes"].tool_kind == "agentic_runtime"
