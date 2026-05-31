from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agentic_os.models import AgentDefinition

ContractVersion = Literal["v1"]
ContractVersionAny = Literal["v1", "v2"]
PromptInputMode = Literal["argv", "stdin", "file", "json"]
OutputMode = Literal["plain_text", "json", "jsonl", "tool_events", "mixed"]
NativeIdentityKind = Literal["none", "upstream_session_id", "conversation_id", "thread_id"]
ResumeStrategy = Literal["unsupported", "command", "best_effort"]
LogStreamContract = Literal["none", "text", "json", "jsonl", "mixed"]
EventTimelineMode = Literal["stdout_stderr_only"]
UsageEvidenceMode = Literal["json", "jsonl", "text_regex", "none"]
ConfigFileKind = Literal["json", "toml", "markdown"]
ConfigScopeName = Literal["user", "project", "local"]


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


class LaunchContractV2(BaseModel):
    supported: bool = True
    command_template: list[str] = Field(default_factory=list)
    prompt_input_mode: PromptInputMode = "argv"
    output_mode: OutputMode = "plain_text"
    cwd_mode: str = "optional"
    requires_workspace: bool = False


class NativeSessionContractV2(BaseModel):
    supported: bool = False
    command_template: list[str] = Field(default_factory=list)
    identity_kind: NativeIdentityKind = "none"
    requires_discovered_identity: bool = False
    strategy: ResumeStrategy = "unsupported"


class LogContractV2(BaseModel):
    paths: list[str] = Field(default_factory=list)
    stdout_contract: LogStreamContract = "text"
    stderr_contract: LogStreamContract = "text"
    event_timeline: EventTimelineMode = "stdout_stderr_only"


class UsageContractV2(BaseModel):
    supported: bool = False
    source: str = "fallback"
    evidence_mode: UsageEvidenceMode = "none"
    fields: list[str] = Field(default_factory=list)


class ConfigContractV2(BaseModel):
    native_supported: bool = False
    scopes: list[ConfigScopeName] = Field(default_factory=list)
    primary_path: str | None = None
    native_files: list[str] = Field(default_factory=list)
    file_kinds: list[ConfigFileKind] = Field(default_factory=list)
    redacts_secrets: bool = True


class SurfaceContractV2(BaseModel):
    mcp_scan: bool = False
    skill_scan: bool = False
    command_scan: bool = False
    hook_scan: bool = False
    subagent_scan: bool = False
    native_config_scan: bool = False


class PolicyContractV2(BaseModel):
    launch_gate: bool = True
    preflight_config_warning: bool = True
    runtime_enforcement: bool = False
    native_policy: bool = False
    notes: str = "agentic-os currently gates launch and preflight warnings only."


class HarnessAdapterContractV2(BaseModel):
    harness_id: str
    contract_version: Literal["v2"] = "v2"
    launch: LaunchContractV2
    resume: NativeSessionContractV2
    attach: NativeSessionContractV2
    log: LogContractV2
    usage: UsageContractV2
    config: ConfigContractV2
    surface: SurfaceContractV2
    policy: PolicyContractV2 = Field(default_factory=PolicyContractV2)
    capability_matrix: dict[str, bool] = Field(default_factory=dict)
    required_env: list[str] = Field(default_factory=list)
    error_modes: list[str] = Field(
        default_factory=lambda: ["not_found", "timeout", "auth_error", "parse_error"]
    )


SUPPORTED_CONTRACT_VERSIONS: tuple[str, ...] = ("v1", "v2")
SEMANTIC_HARNESS_IDS = ("claude", "codex", "cursor", "hermes", "openclaw", "opencode", "qwen")
_SESSION_ID_CAPABLE_HARNESSES = {"openclaw", "hermes", "opencode"}
_JSON_OUTPUT_HARNESSES = {"openclaw"}
_TEXT_REGEX_USAGE_HARNESSES = {"claude", "codex", "cursor", "hermes", "opencode", "qwen"}
_USAGE_SOURCE_BY_HARNESS = {
    "claude": "claude",
    "codex": "codex",
    "cursor": "cursor",
    "hermes": "fallback",
    "openclaw": "openclaw",
    "opencode": "opencode",
    "qwen": "fallback",
}
_CURSOR_NATIVE_FILES = [
    ".cursor/cli-config.json",
    ".cursor/mcp.json",
    ".cursor/hooks.json",
]
_JSON_CONFIG_HARNESSES = {"claude", "cursor"}
_TOML_CONFIG_HARNESSES = {"codex", "hermes", "openclaw", "opencode", "qwen"}
_NATIVE_CONFIG_HARNESSES = _JSON_CONFIG_HARNESSES | _TOML_CONFIG_HARNESSES
_HOOK_SCAN_HARNESSES = {"claude", "cursor"}


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


def contract_from_agent_v2(agent: AgentDefinition) -> HarnessAdapterContractV2:
    supports_native_identity = agent.id in _SESSION_ID_CAPABLE_HARNESSES or agent.id == "cursor"
    output_mode: OutputMode = "json" if agent.id in _JSON_OUTPUT_HARNESSES else "plain_text"
    usage_evidence: UsageEvidenceMode = (
        "json"
        if agent.id in _JSON_OUTPUT_HARNESSES
        else "text_regex"
        if agent.id in _TEXT_REGEX_USAGE_HARNESSES
        else "none"
    )
    usage_supported = usage_evidence != "none"
    native_supported = agent.config_path is not None and agent.id in _NATIVE_CONFIG_HARNESSES
    config_scopes: list[ConfigScopeName] = ["user", "project", "local"] if native_supported else []
    native_files = _native_config_files(agent.id, native_supported)
    file_kinds = _config_file_kinds(agent.id, native_supported)
    resume = NativeSessionContractV2(
        supported=supports_native_identity,
        command_template=list(agent.attach_command or []),
        identity_kind="upstream_session_id" if supports_native_identity else "none",
        requires_discovered_identity=supports_native_identity,
        strategy="command"
        if agent.attach_command
        else "best_effort"
        if supports_native_identity
        else "unsupported",
    )
    attach = NativeSessionContractV2(
        supported=bool(agent.attach_command),
        command_template=list(agent.attach_command or []),
        identity_kind="upstream_session_id" if supports_native_identity else "none",
        requires_discovered_identity=supports_native_identity,
        strategy="command" if agent.attach_command else "unsupported",
    )
    surface = SurfaceContractV2(
        mcp_scan=native_supported,
        skill_scan=native_supported,
        command_scan=native_supported,
        hook_scan=native_supported and agent.id in _HOOK_SCAN_HARNESSES,
        subagent_scan=native_supported,
        native_config_scan=native_supported,
    )
    capability_matrix = {
        "launch": bool(agent.command),
        "resume": resume.supported,
        "attach": attach.supported,
        "json_output": output_mode == "json",
        "mcp_scan": surface.mcp_scan,
        "skill_scan": surface.skill_scan,
        "usage_parse": usage_supported,
        "native_policy": False,
        "sandbox": False,
        "config_scopes": bool(config_scopes),
    }
    return HarnessAdapterContractV2(
        harness_id=agent.id,
        launch=LaunchContractV2(
            supported=bool(agent.command),
            command_template=list(agent.command),
            output_mode=output_mode,
            cwd_mode=agent.cwd_mode,
            requires_workspace=agent.cwd_mode == "required",
        ),
        resume=resume,
        attach=attach,
        log=LogContractV2(paths=list(agent.log_paths)),
        usage=UsageContractV2(
            supported=usage_supported,
            source=_USAGE_SOURCE_BY_HARNESS.get(agent.id, "fallback"),
            evidence_mode=usage_evidence,
            fields=[
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "cost_usd",
                "currency",
                "raw_evidence",
            ],
        ),
        config=ConfigContractV2(
            native_supported=native_supported,
            scopes=config_scopes,
            primary_path=agent.config_path,
            native_files=native_files,
            file_kinds=file_kinds,
            redacts_secrets=True,
        ),
        surface=surface,
        capability_matrix=capability_matrix,
        required_env=sorted(agent.env.keys()),
    )


def _native_config_files(harness_id: str, native_supported: bool) -> list[str]:
    if not native_supported:
        return []
    if harness_id == "cursor":
        return list(_CURSOR_NATIVE_FILES)
    if harness_id == "claude":
        return [".claude/settings.json"]
    if harness_id == "codex":
        return [".codex/config.toml"]
    if harness_id == "opencode":
        return [".opencode/config.toml"]
    if harness_id == "qwen":
        return [".qwen/config.toml"]
    if harness_id == "openclaw":
        return [".openclaw/config.toml"]
    if harness_id == "hermes":
        return [".hermes/config.toml"]
    return []


def _config_file_kinds(harness_id: str, native_supported: bool) -> list[ConfigFileKind]:
    if not native_supported:
        return []
    if harness_id in _JSON_CONFIG_HARNESSES:
        return ["json"]
    if harness_id in _TOML_CONFIG_HARNESSES:
        return ["toml"]
    return []
