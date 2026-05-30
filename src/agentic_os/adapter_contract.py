from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agentic_os.models import AgentDefinition

ContractVersion = Literal["v1"]


class CommandTemplate(BaseModel):
    supported: bool = True
    command_template: list[str] = Field(default_factory=list)


class ContractCapabilities(BaseModel):
    interactive: bool = False
    supports_attach: bool = False
    supports_session_id: bool = False
    supports_config_native: bool = False


class HarnessAdapterContract(BaseModel):
    harness_id: str
    contract_version: ContractVersion = "v1"
    launch: CommandTemplate
    health: CommandTemplate
    version: CommandTemplate
    attach: CommandTemplate
    logs: dict[str, list[str]]
    capability: ContractCapabilities = Field(default_factory=ContractCapabilities)
    required_env: list[str] = Field(default_factory=list)
    error_modes: list[str] = Field(
        default_factory=lambda: ["not_found", "timeout", "auth_error", "parse_error"]
    )


_SESSION_ID_CAPABLE_HARNESSES = {"openclaw", "hermes", "opencode"}


def contract_from_agent(agent: AgentDefinition) -> HarnessAdapterContract:
    return HarnessAdapterContract(
        harness_id=agent.id,
        launch=CommandTemplate(
            supported=bool(agent.command),
            command_template=list(agent.command),
        ),
        health=CommandTemplate(
            supported=bool(agent.health_command),
            command_template=list(agent.health_command or []),
        ),
        version=CommandTemplate(
            supported=bool(agent.version_command),
            command_template=list(agent.version_command or []),
        ),
        attach=CommandTemplate(
            supported=bool(agent.attach_command),
            command_template=list(agent.attach_command or []),
        ),
        logs={"log_paths": list(agent.log_paths)},
        capability=ContractCapabilities(
            interactive=False,
            supports_attach=bool(agent.attach_command),
            supports_session_id=agent.id in _SESSION_ID_CAPABLE_HARNESSES,
            supports_config_native=agent.config_path is not None,
        ),
        required_env=sorted(agent.env.keys()),
    )
