from __future__ import annotations

import sys

from agentic_os.models import AgentDefinition
from agentic_os.probe_service import ProbeService


def agent(command: list[str] | None) -> AgentDefinition:
    return AgentDefinition(
        id="demo",
        label="Demo",
        command=["/bin/echo", "run"],
        health_command=command,
    )


def test_probe_normalizes_success() -> None:
    result = ProbeService(timeout_seconds=1).probe(agent(["/bin/echo", "OK"]))

    assert result.state == "up"
    assert result.exit_code == 0
    assert result.stdout_preview == "OK"
    assert result.message == "OK"
    assert result.duration_ms >= 0


def test_probe_normalizes_nonzero() -> None:
    result = ProbeService(timeout_seconds=1).probe(agent(["/bin/sh", "-c", "exit 7"]))

    assert result.state == "down"
    assert result.exit_code == 7


def test_probe_without_command_is_unknown() -> None:
    result = ProbeService(timeout_seconds=1).probe(agent(None))

    assert result.state == "unknown"
    assert result.error == "health command not configured"


def test_probe_collects_version_and_fingerprint() -> None:
    definition = agent(["/bin/echo", "OK"])
    definition.version_command = ["/bin/echo", "v2.0"]
    definition.config_fingerprint_command = ["/bin/echo", "fp_123"]

    result = ProbeService(timeout_seconds=1).probe(definition)

    assert result.version == "v2.0"
    assert result.config_fingerprint == "fp_123"


def test_probe_bounds_utf8_output_by_bytes() -> None:
    result = ProbeService(timeout_seconds=1).probe(
        agent([sys.executable, "-c", "print('界' * 2000)"])
    )

    assert result.truncated is True
    assert len(result.stdout_preview.encode("utf-8")) <= 2048
