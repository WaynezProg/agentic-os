from __future__ import annotations

from pathlib import Path

from agentic_os.capability_inventory import ToolCapabilities
from agentic_os.config_inventory import ConfigSummary
from agentic_os.environment_service import EnvironmentService
from agentic_os.fleet import FleetStore
from agentic_os.native_session_service import NativeSessionService
from agentic_os.registry import Registry
from agentic_os.tool_discovery import ToolDiscoveryResult


def _registry(tmp_path: Path, agent_id: str, config_path: Path) -> Registry:
    path = tmp_path / "agents.toml"
    path.write_text(
        f"""
[[agents]]
id = "{agent_id}"
label = "{agent_id}"
command = ["{agent_id}"]
tool_kind = "vibe_coding"
config_path = "{config_path}"
""",
        encoding="utf-8",
    )
    return Registry(path)


def _fleet(tmp_path: Path) -> FleetStore:
    store = FleetStore(tmp_path / "state.db")
    store.init()
    return store


def _sessions(tmp_path: Path) -> NativeSessionService:
    return NativeSessionService(
        roots={
            "claude": tmp_path / "no-claude",
            "codex": tmp_path / "no-codex",
        }
    )


def test_config_residue_does_not_mark_cli_installed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config_dir = home / ".qwen"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"model":"qwen3"}', encoding="utf-8")
    registry = _registry(tmp_path, "qwen", config_dir)

    service = EnvironmentService(
        registry=registry,
        capability_home=home,
        native_sessions=_sessions(tmp_path),
        fleet_store=_fleet(tmp_path),
        tool_detector=lambda agent: ToolDiscoveryResult(
            agent_id=agent.id,
            tool_kind=agent.tool_kind,
            installed=False,
            binary_path=None,
            version=None,
            version_error=None,
        ),
        config_reader=lambda agent_id, path: ConfigSummary(
            config_source=path,
            model="qwen3",
        ),
        capability_reader=lambda tool, home: ToolCapabilities(tool=tool, present=True),
        application_finder=lambda names, home: None,
    )

    environment = service.observe("qwen")[0]
    surfaces = {surface.kind: surface for surface in environment.surfaces}

    assert surfaces["cli"].status == "missing"
    assert surfaces["config"].status == "configured_only"
    assert environment.overall_status == "degraded"


def test_surface_evidence_is_independent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config_dir = home / ".codex"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text('model = "gpt-5"\n', encoding="utf-8")
    registry = _registry(tmp_path, "codex", config_dir)

    service = EnvironmentService(
        registry=registry,
        capability_home=home,
        native_sessions=_sessions(tmp_path),
        fleet_store=_fleet(tmp_path),
        tool_detector=lambda agent: ToolDiscoveryResult(
            agent_id=agent.id,
            tool_kind=agent.tool_kind,
            installed=True,
            binary_path="/opt/homebrew/bin/codex",
            version="codex 1.2.3",
            version_error=None,
        ),
        config_reader=lambda agent_id, path: ConfigSummary(config_source=path),
        capability_reader=lambda tool, home: ToolCapabilities(
            tool=tool,
            present=True,
            skills=["review"],
            mcp_servers=["context7"],
        ),
        application_finder=lambda names, home: Path("/Applications/ChatGPT.app"),
    )

    environment = service.observe("codex")[0]
    surfaces = {surface.kind: surface for surface in environment.surfaces}

    assert set(surfaces) == {"cli", "config", "capability", "runtime", "desktop", "ide"}
    assert surfaces["cli"].status == "healthy"
    assert surfaces["config"].status == "healthy"
    assert surfaces["desktop"].status == "healthy"
    assert surfaces["ide"].status == "unsupported"
    assert surfaces["cli"].source == "binary_discovery"
    assert surfaces["desktop"].source == "application_bundle"
    assert environment.capability_names["skills"] == ["review"]
    assert environment.active_sessions == 0


def test_environment_reports_pending_change_count(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config_dir = home / ".codex"
    config_dir.mkdir(parents=True)
    registry = _registry(tmp_path, "codex", config_dir)

    service = EnvironmentService(
        registry=registry,
        capability_home=home,
        native_sessions=_sessions(tmp_path),
        fleet_store=_fleet(tmp_path),
        tool_detector=lambda agent: ToolDiscoveryResult(
            agent_id=agent.id,
            tool_kind=agent.tool_kind,
            installed=False,
            binary_path=None,
            version=None,
            version_error=None,
        ),
        config_reader=lambda agent_id, path: ConfigSummary(config_source=path),
        capability_reader=lambda tool, home: ToolCapabilities(tool=tool, present=False),
        application_finder=lambda names, home: None,
        pending_change_counter=lambda environment_id: 3 if environment_id == "codex" else 0,
    )

    environment = service.observe("codex")[0]

    assert environment.pending_change_count == 3
