from pydantic import BaseModel

from agentic_os.adapter_contract import contract_from_agent
from agentic_os.models import AgentDefinition


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
