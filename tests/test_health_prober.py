from pathlib import Path

import pytest

from agentic_os.fleet import FleetStore, HealthState
from agentic_os.health_prober import HealthProber
from agentic_os.models import AgentDefinition
from agentic_os.probe_service import ProbeResult


def _make_fleet_store(tmp_path: Path) -> FleetStore:
    store = FleetStore(tmp_path / "fleet.db")
    store.init()
    return store


def _agent(
    agent_id: str = "shell",
    health_command: list[str] | None = None,
    version_command: list[str] | None = None,
    config_fingerprint_command: list[str] | None = None,
) -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        label=agent_id,
        command=["/bin/echo", "hi"],
        health_command=health_command,
        version_command=version_command,
        config_fingerprint_command=config_fingerprint_command,
    )


@pytest.mark.asyncio
async def test_probe_one_healthy(tmp_path):
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=10)
    agent = _agent(health_command=["/bin/echo", "OK"])
    await prober.probe_one(agent)
    record = fleet.get_health("shell")
    assert record is not None
    assert record.state == HealthState.UP


@pytest.mark.asyncio
async def test_probe_one_unhealthy_exit_code(tmp_path):
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=10)
    agent = _agent(health_command=["/bin/sh", "-c", "exit 1"])
    await prober.probe_one(agent)
    record = fleet.get_health("shell")
    assert record is not None
    assert record.state == HealthState.DOWN


@pytest.mark.asyncio
async def test_probe_one_timeout(tmp_path):
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=0.1)
    agent = _agent(health_command=["/bin/sleep", "10"])
    await prober.probe_one(agent)
    record = fleet.get_health("shell")
    assert record is not None
    assert record.state == HealthState.DOWN
    assert "timeout" in record.message.lower()


@pytest.mark.asyncio
async def test_probe_one_no_health_command_skips(tmp_path):
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=10)
    agent = _agent(health_command=None)
    await prober.probe_one(agent)
    assert fleet.get_health("shell") is None


@pytest.mark.asyncio
async def test_probe_one_collects_version(tmp_path):
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=10)
    agent = _agent(
        health_command=["/bin/echo", "OK"],
        version_command=["/bin/echo", "2.1.0"],
        config_fingerprint_command=["/bin/echo", "fp_abc"],
    )
    await prober.probe_one(agent)
    record = fleet.get_health("shell")
    assert record is not None
    assert record.version == "2.1.0"
    assert record.config_fingerprint == "fp_abc"


@pytest.mark.asyncio
async def test_probe_one_persists_shared_probe_result(tmp_path):
    class FakeProbeService:
        def probe(self, agent: AgentDefinition) -> ProbeResult:
            assert agent.id == "shell"
            return ProbeResult(
                state="up",
                message="shared result",
                duration_ms=2,
                exit_code=0,
                version="9.9.9",
                config_fingerprint="fp_shared",
            )

    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, probe_service=FakeProbeService())
    await prober.probe_one(_agent(health_command=["not-executed"]))

    record = fleet.get_health("shell")
    assert record is not None
    assert record.message == "shared result"
    assert record.version == "9.9.9"
    assert record.config_fingerprint == "fp_shared"


@pytest.mark.asyncio
async def test_probe_all_multiple_agents(tmp_path):
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=10)
    agents = [
        _agent("a1", health_command=["/bin/echo", "OK"]),
        _agent("a2", health_command=["/bin/sh", "-c", "exit 1"]),
        _agent("a3", health_command=None),
    ]
    await prober.probe_all(agents)
    assert fleet.get_health("a1").state == HealthState.UP
    assert fleet.get_health("a2").state == HealthState.DOWN
    assert fleet.get_health("a3") is None


@pytest.mark.asyncio
async def test_probe_all_isolation_one_failure_does_not_block_others(tmp_path):
    """A failing probe must not prevent other probes from completing (G2)."""
    fleet = _make_fleet_store(tmp_path)
    prober = HealthProber(fleet, timeout_seconds=0.2)
    agents = [
        _agent("fast", health_command=["/bin/echo", "OK"]),
        _agent("slow", health_command=["/bin/sleep", "10"]),
        _agent("also_fast", health_command=["/bin/echo", "OK"]),
    ]
    await prober.probe_all(agents)
    assert fleet.get_health("fast").state == HealthState.UP
    assert fleet.get_health("slow").state == HealthState.DOWN
    assert fleet.get_health("also_fast").state == HealthState.UP
