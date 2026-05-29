from __future__ import annotations

import asyncio

from agentic_os.fleet import FleetStore, HealthState
from agentic_os.models import AgentDefinition


class HealthProber:
    def __init__(
        self,
        fleet_store: FleetStore,
        timeout_seconds: float = 10.0,
        max_concurrent: int = 10,
    ) -> None:
        self.fleet_store = fleet_store
        self.timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def probe_one(self, agent: AgentDefinition) -> None:
        if agent.health_command is None:
            return
        async with self._semaphore:
            state, message = await self._run_health_command(agent)
            version = await self._run_info_command(agent.version_command)
            fingerprint = await self._run_info_command(agent.config_fingerprint_command)
            self.fleet_store.record_health(
                agent.id,
                state,
                message,
                version=version,
                config_fingerprint=fingerprint,
            )

    async def probe_all(self, agents: list[AgentDefinition]) -> None:
        tasks = [self.probe_one(agent) for agent in agents]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_health_command(self, agent: AgentDefinition) -> tuple[HealthState, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *agent.health_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_seconds
            )
            if proc.returncode == 0:
                return HealthState.UP, stdout.decode().strip()
            return HealthState.DOWN, f"exit {proc.returncode}: {stderr.decode().strip()}"
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return HealthState.DOWN, f"timeout after {self.timeout_seconds}s"
        except OSError as exc:
            return HealthState.DOWN, f"launch failed: {exc}"

    async def _run_info_command(self, command: list[str] | None) -> str | None:
        if command is None:
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            return None
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_seconds)
            if proc.returncode == 0:
                return stdout.decode().strip()
            return None
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return None
