import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from agentic_os.adapter_contract import (
    SEMANTIC_HARNESS_IDS,
    HarnessAdapterContractV2,
    contract_from_agent,
    contract_from_agent_v2,
)
from agentic_os.models import AgentDefinition
from agentic_os.registry import Registry


FIXTURE_DIR = Path("tests/fixtures/adapter_contract_v2")


def test_contract_from_agent_has_required_fields() -> None:
    agent = AgentDefinition(
        id="claude",
        label="Claude",
        command=["claude", "--print", "{message}"],
        health_command=["claude", "--status"],
        version_command=["claude", "--version"],
        attach_command=["claude", "resume", "{session_id}"],
        env={"ANTHROPIC_API_KEY": "x"},
        config_path="/home/user/.claude/settings.toml",
        log_paths=["/tmp/claude.log"],
    )
    contract = contract_from_agent(agent)

    assert isinstance(contract, BaseModel)
    assert contract.contract_version == "v1"
    assert contract.launch.command_template == ["claude", "--print", "{message}"]
    assert contract.health.command_template == ["claude", "--status"]
    assert contract.version.command_template == ["claude", "--version"]
    assert contract.attach.command_template == ["claude", "resume", "{session_id}"]
    assert contract.capability.supports_attach is True
    assert contract.capability.supports_session_id is False
    assert contract.capability.supports_config_native is True
    assert contract.required_env == ["ANTHROPIC_API_KEY"]


def test_contract_marks_external_session_id_capable_harnesses() -> None:
    agent = AgentDefinition(
        id="openclaw",
        label="OpenClaw",
        command=["openclaw", "run", "{{message}}"],
    )

    contract = contract_from_agent(agent)

    assert contract.capability.supports_session_id is True


def test_contract_v2_cursor_semantics() -> None:
    registry = Registry(Path("examples/agents.toml"))
    contract = contract_from_agent_v2(registry.get("cursor"))

    assert isinstance(contract, HarnessAdapterContractV2)
    assert contract.contract_version == "v2"
    assert contract.launch.prompt_input_mode == "argv"
    assert contract.launch.output_mode == "plain_text"
    assert contract.launch.requires_workspace is True
    assert contract.resume.supported is True
    assert contract.resume.identity_kind == "upstream_session_id"
    assert contract.resume.requires_discovered_identity is True
    assert contract.attach.supported is True
    assert contract.config.native_supported is True
    assert ".cursor/cli-config.json" in contract.config.native_files
    assert ".cursor/mcp.json" in contract.config.native_files
    assert ".cursor/hooks.json" in contract.config.native_files
    assert contract.surface.hook_scan is True
    assert contract.policy.launch_gate is True
    assert contract.policy.runtime_enforcement is False
    assert contract.capability_matrix["resume"] is True
    assert contract.capability_matrix["json_output"] is False


def test_contract_v2_openclaw_declares_json_usage() -> None:
    registry = Registry(Path("examples/agents.toml"))
    contract = contract_from_agent_v2(registry.get("openclaw"))

    assert contract.launch.output_mode == "json"
    assert contract.usage.supported is True
    assert contract.usage.source == "openclaw"
    assert contract.usage.evidence_mode == "json"
    assert contract.capability_matrix["json_output"] is True
    assert contract.capability_matrix["usage_parse"] is True


def test_contract_v2_semantic_harness_set_excludes_shell() -> None:
    assert SEMANTIC_HARNESS_IDS == (
        "claude",
        "codex",
        "cursor",
        "hermes",
        "openclaw",
        "opencode",
        "qwen",
    )


def test_contract_v2_configless_agent_has_no_native_config_surfaces() -> None:
    agent = AgentDefinition(
        id="claude",
        label="Claude",
        command=["claude", "--print", "{message}"],
        config_path=None,
    )

    contract = contract_from_agent_v2(agent)

    assert contract.config.native_supported is False
    assert contract.config.native_files == []
    assert contract.config.file_kinds == []
    assert contract.surface.hook_scan is False
    assert contract.surface.native_config_scan is False
    assert contract.surface.mcp_scan is False
    assert contract.surface.skill_scan is False
    assert contract.surface.command_scan is False
    assert contract.surface.subagent_scan is False
    assert contract.capability_matrix["config_scopes"] is False
    assert contract.capability_matrix["mcp_scan"] is False
    assert contract.capability_matrix["skill_scan"] is False


def test_contract_v2_unknown_config_path_is_not_scannable() -> None:
    agent = AgentDefinition(
        id="unknown",
        label="Unknown",
        command=["unknown", "{{message}}"],
        config_path="~/.unknown",
    )

    contract = contract_from_agent_v2(agent)

    assert contract.config.primary_path == "~/.unknown"
    assert contract.config.native_supported is False
    assert contract.config.scopes == []
    assert contract.config.native_files == []
    assert contract.config.file_kinds == []
    assert contract.surface.hook_scan is False
    assert contract.surface.native_config_scan is False
    assert contract.surface.mcp_scan is False
    assert contract.surface.skill_scan is False
    assert contract.surface.command_scan is False
    assert contract.surface.subagent_scan is False
    assert contract.capability_matrix["config_scopes"] is False
    assert contract.capability_matrix["mcp_scan"] is False
    assert contract.capability_matrix["skill_scan"] is False


@pytest.mark.parametrize(
    ("harness_id", "native_files", "file_kinds"),
    [
        ("claude", [".claude/settings.json"], ["json"]),
        ("codex", [".codex/config.toml"], ["toml"]),
        (
            "cursor",
            [".cursor/cli-config.json", ".cursor/mcp.json", ".cursor/hooks.json"],
            ["json"],
        ),
        ("hermes", [".hermes/config.toml"], ["toml"]),
        ("openclaw", [".openclaw/config.toml"], ["toml"]),
        ("opencode", [".opencode/config.json"], ["json"]),
        ("qwen", [".qwen/settings.json"], ["json"]),
    ],
)
def test_contract_v2_config_files_match_native_scan_contract(
    harness_id: str,
    native_files: list[str],
    file_kinds: list[str],
) -> None:
    registry = Registry(Path("examples/agents.toml"))
    contract = contract_from_agent_v2(registry.get(harness_id))

    assert contract.config.native_files == native_files
    assert contract.config.file_kinds == file_kinds


@pytest.mark.parametrize("harness_id", SEMANTIC_HARNESS_IDS)
def test_contract_v2_semantic_harnesses_round_trip_and_config_consistency(
    harness_id: str,
) -> None:
    registry = Registry(Path("examples/agents.toml"))
    contract = contract_from_agent_v2(registry.get(harness_id))

    payload = contract.model_dump(mode="json")
    round_tripped = HarnessAdapterContractV2.model_validate(payload)

    assert round_tripped == contract
    if contract.config.native_supported:
        assert contract.config.native_files
        assert contract.config.file_kinds
        assert contract.surface.native_config_scan is True
        assert contract.surface.mcp_scan is True
        assert contract.surface.skill_scan is True
        assert contract.surface.command_scan is True
        assert contract.surface.subagent_scan is True
        assert contract.capability_matrix["config_scopes"] is True
        assert contract.capability_matrix["mcp_scan"] is True
        assert contract.capability_matrix["skill_scan"] is True
    else:
        assert contract.config.native_files == []
        assert contract.config.file_kinds == []
        assert contract.surface.native_config_scan is False
        assert contract.surface.mcp_scan is False
        assert contract.surface.skill_scan is False
        assert contract.surface.command_scan is False
        assert contract.surface.subagent_scan is False
        assert contract.capability_matrix["config_scopes"] is False
        assert contract.capability_matrix["mcp_scan"] is False
        assert contract.capability_matrix["skill_scan"] is False


def test_contract_v2_semantic_harness_set_matches_registry_non_shell_ids() -> None:
    registry = Registry(Path("examples/agents.toml"))
    non_shell_ids = tuple(
        sorted(agent.id for agent in registry.list_agents() if agent.id != "shell")
    )

    assert non_shell_ids == SEMANTIC_HARNESS_IDS


@pytest.mark.parametrize("harness_id", SEMANTIC_HARNESS_IDS)
def test_contract_v2_matches_golden_fixture(harness_id: str) -> None:
    registry = Registry(Path("examples/agents.toml"))
    contract = contract_from_agent_v2(registry.get(harness_id))
    fixture_path = FIXTURE_DIR / f"{harness_id}.json"

    expected = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert contract.model_dump(mode="json") == expected


def test_contract_v2_fixtures_cover_only_semantic_harnesses() -> None:
    fixture_ids = tuple(sorted(path.stem for path in FIXTURE_DIR.glob("*.json")))

    assert fixture_ids == SEMANTIC_HARNESS_IDS
    assert "shell" not in fixture_ids
