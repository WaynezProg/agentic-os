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

    def build_run(self, agent_id: str, cwd: str | None, message: str) -> RenderedRun:
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
        return RenderedRun(
            agent=agent,
            cwd=run_cwd,
            argv=render_command(agent.command, message),
            env=dict(agent.env),
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


def render_command(command: list[str], message: str) -> list[str]:
    return [part.replace("{{message}}", message) for part in command]


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
