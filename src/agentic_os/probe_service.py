from __future__ import annotations

import subprocess
import time
from typing import Literal

from pydantic import BaseModel

from agentic_os.models import AgentDefinition

ProbeState = Literal["up", "down", "unknown"]
_OUTPUT_LIMIT_BYTES = 2048


def _bounded_text(value: str) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= _OUTPUT_LIMIT_BYTES:
        return value.strip(), False
    return encoded[:_OUTPUT_LIMIT_BYTES].decode("utf-8", errors="ignore").strip(), True


class ProbeResult(BaseModel):
    state: ProbeState
    message: str
    duration_ms: int
    exit_code: int | None = None
    stdout_preview: str = ""
    stderr_preview: str = ""
    truncated: bool = False
    error: str | None = None
    version: str | None = None
    config_fingerprint: str | None = None

    def api_payload(self, agent_id: str) -> dict[str, object]:
        return {"id": agent_id, **self.model_dump(exclude={"version", "config_fingerprint"})}


class ProbeService:
    def __init__(self, timeout_seconds: float = 10) -> None:
        self.timeout_seconds = timeout_seconds

    def probe(self, agent: AgentDefinition) -> ProbeResult:
        if not agent.health_command:
            message = "health command not configured"
            return ProbeResult(
                state="unknown",
                message=message,
                duration_ms=0,
                error=message,
            )

        started = time.monotonic()
        try:
            completed = subprocess.run(
                agent.health_command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ProbeResult(
                state="down",
                message="health check timeout",
                duration_ms=round((time.monotonic() - started) * 1000),
                error="timeout",
            )
        except OSError as exc:
            return ProbeResult(
                state="down",
                message=str(exc),
                duration_ms=round((time.monotonic() - started) * 1000),
                error=str(exc),
            )

        stdout, stdout_truncated = _bounded_text(completed.stdout or "")
        stderr, stderr_truncated = _bounded_text(completed.stderr or "")
        return ProbeResult(
            state="up" if completed.returncode == 0 else "down",
            message=stdout or stderr or ("OK" if completed.returncode == 0 else f"exit {completed.returncode}"),
            duration_ms=round((time.monotonic() - started) * 1000),
            exit_code=completed.returncode,
            stdout_preview=stdout,
            stderr_preview=stderr,
            truncated=stdout_truncated or stderr_truncated,
            version=self.info(agent.version_command),
            config_fingerprint=self.info(agent.config_fingerprint_command),
        )

    def info(self, command: list[str] | None) -> str | None:
        if not command:
            return None
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        value, _ = _bounded_text(completed.stdout or completed.stderr or "")
        return value or None
