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


def test_ignored_cwd_ignores_nonexistent_caller_cwd(tmp_path: Path) -> None:
    config = tmp_path / "agents.toml"
    config.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/bin/echo", "{{message}}"]
cwd_mode = "ignored"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )

    registry = Registry(config)
    run = registry.build_run("shell", cwd=str(tmp_path / "missing"), message="OK")

    assert Path(run.cwd) == Path.cwd().resolve()
    assert Path(run.cwd).exists()


def test_registry_rejects_missing_non_ignored_cwd(tmp_path: Path) -> None:
    config = tmp_path / "agents.toml"
    config.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/bin/echo", "{{message}}"]
cwd_mode = "optional"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )

    registry = Registry(config)

    with pytest.raises(ValueError, match="cwd does not exist"):
        registry.build_run("shell", cwd=str(tmp_path / "missing"), message="OK")


def test_registry_rejects_file_cwd(tmp_path: Path) -> None:
    config = tmp_path / "agents.toml"
    config.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/bin/echo", "{{message}}"]
cwd_mode = "optional"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )
    cwd_file = tmp_path / "cwd.txt"
    cwd_file.write_text("not a directory", encoding="utf-8")

    registry = Registry(config)

    with pytest.raises(ValueError, match="cwd is not a directory"):
        registry.build_run("shell", cwd=str(cwd_file), message="OK")


def test_registry_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Registry(tmp_path / "missing.toml")


def test_registry_rejects_duplicate_agent_id(tmp_path: Path) -> None:
    config = tmp_path / "agents.toml"
    config.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/bin/echo", "{{message}}"]
cwd_mode = "optional"
stop_policy = "process_group"

[[agents]]
id = "shell"
label = "Shell Again"
command = ["/bin/echo", "{{message}}"]
cwd_mode = "optional"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate agent id: shell"):
        Registry(config)


def test_example_agents_load_and_shell_command_avoids_shell_interpolation() -> None:
    registry = Registry(Path("examples/agents.toml"))

    shell = registry.get("shell")

    assert shell.command == ["/usr/bin/printf", "%s\\n", "{{message}}"]
    assert shell.command[:2] != ["/bin/sh", "-lc"]
