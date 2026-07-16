from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from agentic_os.models import AgentDefinition
from agentic_os.patch_engine import PatchOp
from agentic_os.safe_edit import PatchTarget
from agentic_os.toml_io import load_toml

REGISTRY_HARNESS_ID = "agentic_os"
REGISTRY_KIND = "registry"


@dataclass(frozen=True)
class RenderedRun:
    agent: AgentDefinition
    cwd: str
    argv: list[str]
    env: dict[str, str]


class Registry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._agents = self._load()

    def reload(self) -> None:
        self._agents = self._load()

    def list_agents(self) -> list[AgentDefinition]:
        return sorted(self._agents.values(), key=lambda agent: agent.id)

    def get(self, agent_id: str) -> AgentDefinition:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent: {agent_id}") from exc

    def build_run(
        self,
        agent_id: str,
        cwd: str | None,
        message: str,
        *,
        model: str | None = None,
        provider: str | None = None,
    ) -> RenderedRun:
        agent = self.get(agent_id)
        if agent.cwd_mode == "ignored":
            run_cwd = str(Path.cwd().resolve())
        else:
            if agent.cwd_mode == "required" and not cwd:
                raise ValueError("cwd is required")
            run_cwd = str(Path(cwd).expanduser().resolve()) if cwd else str(Path.cwd().resolve())
            cwd_path = Path(run_cwd)
            if not cwd_path.exists():
                raise ValueError(f"cwd does not exist: {run_cwd}")
            if not cwd_path.is_dir():
                raise ValueError(f"cwd is not a directory: {run_cwd}")
        argv, env = apply_profile_launch(agent, agent.command, message, model=model, provider=provider)
        return RenderedRun(
            agent=agent,
            cwd=run_cwd,
            argv=argv,
            env=env,
        )

    def _load(self) -> dict[str, AgentDefinition]:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        agents = {}
        for raw_agent in data.get("agents", []):
            agent = AgentDefinition.model_validate(raw_agent)
            if agent.id in agents:
                raise ValueError(f"duplicate agent id: {agent.id}")
            agents[agent.id] = agent
        return agents


def render_command(
    command: list[str],
    message: str,
    *,
    model: str | None = None,
    provider: str | None = None,
) -> list[str]:
    return [
        _substitute_launch_template(part, message=message, model=model, provider=provider)
        for part in command
    ]


def _substitute_launch_template(
    part: str,
    *,
    message: str,
    model: str | None = None,
    provider: str | None = None,
) -> str:
    rendered = part.replace("{{message}}", message)
    if model is not None:
        rendered = rendered.replace("{{model}}", model)
    if provider is not None:
        rendered = rendered.replace("{{provider}}", provider)
    return rendered


def apply_profile_launch(
    agent: AgentDefinition,
    command: list[str],
    message: str,
    *,
    model: str | None = None,
    provider: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    argv = render_command(command, message, model=model, provider=provider)
    if agent.model_arg and model is not None:
        argv.extend(render_command(agent.model_arg, message="", model=model, provider=provider))
    env = dict(agent.env)
    if agent.provider_env and provider is not None:
        env[agent.provider_env] = provider
    return argv, env


def registry_patch_target(registry_path: Path, cwd: Path) -> PatchTarget:
    return PatchTarget(
        harness_id=REGISTRY_HARNESS_ID,
        cwd=cwd,
        scope="registry",
        target_kind=REGISTRY_KIND,
        kind=REGISTRY_KIND,
        file_path=registry_path,
        file_format="toml",
    )


def load_registry_document(registry_path: Path) -> dict[str, object]:
    return load_toml(registry_path)


def agents_document(agents: list[AgentDefinition]) -> list[dict[str, object]]:
    return [agent.model_dump(exclude_none=True) for agent in agents]


def replace_agents_ops(agent_payloads: list[dict[str, object]]) -> list[PatchOp]:
    return [
        PatchOp(op="remove", path="agents"),
        PatchOp(op="merge", path="agents", value=agent_payloads),
    ]


def merge_agent_instance(
    current: list[AgentDefinition],
    instance: AgentDefinition,
) -> list[AgentDefinition]:
    merged = [agent for agent in current if agent.id != instance.id]
    merged.append(instance)
    return sorted(merged, key=lambda agent: agent.id)


def disable_agent_instance(current: list[AgentDefinition], agent_id: str) -> list[AgentDefinition]:
    updated: list[AgentDefinition] = []
    found = False
    for agent in current:
        if agent.id == agent_id:
            found = True
            updated.append(agent.model_copy(update={"enabled": False}))
        else:
            updated.append(agent)
    if not found:
        raise KeyError(f"unknown agent: {agent_id}")
    return updated


def build_registry_patch(
    registry_path: Path,
    request: dict[str, object],
) -> tuple[PatchTarget, list[PatchOp], dict[str, object]]:
    registry = Registry(registry_path)
    action = str(request.get("action", ""))
    if action == "upsert":
        raw_agent = request.get("agent")
        if not isinstance(raw_agent, dict):
            raise ValueError("agent is required")
        agent = AgentDefinition.model_validate(raw_agent)
        merged = merge_agent_instance(registry.list_agents(), agent)
        summary = {"action": action, "agent_id": agent.id}
    elif action == "disable":
        agent_id = str(request.get("agent_id", ""))
        merged = disable_agent_instance(registry.list_agents(), agent_id)
        summary = {"action": action, "agent_id": agent_id}
    else:
        raise ValueError(f"unsupported registry action: {action}")
    payloads = agents_document(merged)
    return (
        registry_patch_target(registry_path, registry_path.parent),
        replace_agents_ops(payloads),
        summary,
    )


def validate_registry_document(doc: dict[str, object]) -> tuple[list[str], list[str]]:
    raw_agents = doc.get("agents", [])
    if not isinstance(raw_agents, list):
        return ["agents must be a list"], []
    agents: list[AgentDefinition] = []
    for raw in raw_agents:
        if not isinstance(raw, dict):
            return ["agents entries must be objects"], []
        try:
            agents.append(AgentDefinition.model_validate(raw))
        except Exception as exc:  # noqa: BLE001
            return [str(exc)], []
    return validate_registry(agents)


def validate_registry(agents: list[AgentDefinition]) -> tuple[list[str], list[str]]:
    """Validate harness profile fields for non-shell registry entries."""
    errors: list[str] = []
    warnings: list[str] = []
    for agent in agents:
        if agent.id == "shell":
            continue
        if not agent.health_command:
            errors.append(f"{agent.id}: missing health_command")
        if not agent.config_path:
            errors.append(f"{agent.id}: missing config_path")
        if not agent.default_provider:
            errors.append(f"{agent.id}: missing default_provider")
        if not agent.version_command:
            errors.append(f"{agent.id}: missing version_command")
        if not agent.config_fingerprint_command:
            errors.append(f"{agent.id}: missing config_fingerprint_command")
        if not agent.log_paths:
            warnings.append(f"{agent.id}: empty log_paths")
    return errors, warnings
