from __future__ import annotations

import math
import os
import time
from datetime import UTC, datetime
from typing import Any, Callable, Protocol


READ_TARGET_MS = 50.0
WRITE_TARGET_MS = 200.0
PROBE_TARGET_MS = 5000.0
RSS_TARGET_BYTES = 256 * 1024 * 1024
SQLITE_WAL_TARGET_BYTES = 64 * 1024 * 1024
TERMINAL_SESSION_STATUSES = {"succeeded", "failed", "stopped"}


class SloClient(Protocol):
    def list_agents(self) -> dict[str, Any]: ...

    def list_sessions(self) -> dict[str, Any]: ...

    def fleet_health(self) -> dict[str, Any]: ...

    def audit_events(self, limit: int = 500) -> dict[str, Any]: ...

    def fleet_probe(self) -> dict[str, Any]: ...

    def run_session(self, agent_id: str, cwd: str | None, message: str) -> dict[str, Any]: ...

    def retry_session(self, session_id: str) -> dict[str, Any]: ...

    def diagnostics_resources(self) -> dict[str, Any]: ...


def percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, math.ceil((p / 100.0) * len(ordered)) - 1))
    return round(ordered[index], 3)


def summarize_result(name: str, samples_ms: list[float], target_ms_p99: float) -> dict[str, Any]:
    p99 = percentile(samples_ms, 99)
    return {
        "name": name,
        "target_ms_p99": target_ms_p99,
        "p50_ms": percentile(samples_ms, 50),
        "p95_ms": percentile(samples_ms, 95),
        "p99_ms": p99,
        "passed": p99 <= target_ms_p99,
    }


def run_slo_benchmark(client: SloClient, iterations: int) -> dict[str, Any]:
    safe_iterations = max(1, iterations)
    started_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    first_agent_id = _first_agent_id(client)
    first_session_id = _first_retryable_session_id(client)
    operations: list[tuple[str, float, Callable[[], object]]] = [
        ("GET /agents", READ_TARGET_MS, client.list_agents),
        ("GET /sessions", READ_TARGET_MS, client.list_sessions),
        ("GET /fleet/health", READ_TARGET_MS, client.fleet_health),
        ("GET /audit/events", READ_TARGET_MS, lambda: client.audit_events(limit=100)),
        ("POST /fleet/probe", PROBE_TARGET_MS, client.fleet_probe),
    ]
    if first_agent_id is not None:
        operations.append(
            (
                "POST /sessions",
                WRITE_TARGET_MS,
                lambda: client.run_session(first_agent_id, os.getcwd(), "slo-benchmark"),
            )
        )
    if first_session_id is not None:
        operations.append(
            (
                "POST /sessions/{id}/retry",
                WRITE_TARGET_MS,
                lambda: client.retry_session(first_session_id),
            )
        )

    results = [
        summarize_result(name, _measure(operation, safe_iterations), target)
        for name, target, operation in operations
    ]
    resources = client.diagnostics_resources()
    resource_checks = {
        "rss_bytes": int(resources.get("rss_bytes", 0)) <= RSS_TARGET_BYTES,
        "sqlite_wal_bytes": int(resources.get("sqlite_wal_bytes", 0)) <= SQLITE_WAL_TARGET_BYTES,
    }
    return {
        "started_at": started_at,
        "iterations": safe_iterations,
        "results": results,
        "resources": resources,
        "resource_checks": resource_checks,
        "passed": all(result["passed"] for result in results) and all(resource_checks.values()),
    }


def _measure(operation: Callable[[], object], iterations: int) -> list[float]:
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples


def _first_agent_id(client: SloClient) -> str | None:
    agents = client.list_agents().get("agents", [])
    if isinstance(agents, list) and agents:
        agent_id = agents[0].get("id") if isinstance(agents[0], dict) else None
        return str(agent_id) if agent_id else None
    return None


def _first_retryable_session_id(client: SloClient) -> str | None:
    sessions = client.list_sessions().get("sessions", [])
    if isinstance(sessions, list):
        for session in sessions:
            if not isinstance(session, dict):
                continue
            if session.get("status") not in TERMINAL_SESSION_STATUSES:
                continue
            session_id = session.get("id")
            return str(session_id) if session_id else None
    return None
