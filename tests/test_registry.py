from pathlib import Path

import pytest

from agentic_os.registry import Registry, render_command


def test_registry_loads_agents(tmp_path: Path) -> None:
    config = tmp_path / "agents.toml"
    config.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/bin/echo", "{{message}}"]
cwd_mode = "required"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )

    registry = Registry(config)
    agents = registry.list_agents()

    assert [agent.id for agent in agents] == ["shell"]
    assert registry.get("shell").label == "Shell"


def test_render_command_replaces_message() -> None:
    assert render_command(["/bin/echo", "{{message}}"], message="OK") == ["/bin/echo", "OK"]


def test_registry_rejects_missing_required_cwd(tmp_path: Path) -> None:
    config = tmp_path / "agents.toml"
    config.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/bin/echo", "{{message}}"]
cwd_mode = "required"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )

    registry = Registry(config)

    with pytest.raises(ValueError, match="cwd is required"):
        registry.build_run("shell", cwd=None, message="OK")
