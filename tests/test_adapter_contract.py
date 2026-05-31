from pathlib import Path

from pydantic import BaseModel

from agentic_os.adapter_contract import (
    SEMANTIC_HARNESS_IDS,
    HarnessAdapterContractV2,
    contract_from_agent,
    contract_from_agent_v2,
)
from agentic_os.models import AgentDefinition
from agentic_os.registry import Registry


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
