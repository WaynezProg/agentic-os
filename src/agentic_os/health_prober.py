from __future__ import annotations

import asyncio

from agentic_os.fleet import FleetStore, HealthState
from agentic_os.models import AgentDefinition
from agentic_os.probe_service import ProbeService


class HealthProber:
    def __init__(
        self,
        fleet_store: FleetStore,
        timeout_seconds: float = 10.0,
        max_concurrent: int = 10,
        probe_service: ProbeService | None = None,
    ) -> None:
        self.fleet_store = fleet_store
        self.probe_service = probe_service or ProbeService(timeout_seconds=timeout_seconds)
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def probe_one(self, agent: AgentDefinition) -> None:
        if agent.health_command is None:
            return
        async with self._semaphore:
            result = await asyncio.to_thread(self.probe_service.probe, agent)
            self.fleet_store.record_health(
                agent.id,
                HealthState(result.state),
                result.message,
                version=result.version,
                config_fingerprint=result.config_fingerprint,
            )

    async def probe_all(self, agents: list[AgentDefinition]) -> None:
        tasks = [self.probe_one(agent) for agent in agents]
        await asyncio.gather(*tasks, return_exceptions=True)
