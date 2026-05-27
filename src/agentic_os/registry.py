from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from agentic_os.models import AgentDefinition


@dataclass(frozen=True)
class RenderedRun:
    agent: AgentDefinition
    cwd: str
    argv: list[str]


class Registry:
    def __init__(self, path: Path) -> None:
        self.path = path
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
        return RenderedRun(agent=agent, cwd=run_cwd, argv=render_command(agent.command, message))

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
