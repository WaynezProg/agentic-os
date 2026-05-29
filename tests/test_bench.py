from __future__ import annotations

from agentic_os.bench import percentile, run_slo_benchmark, summarize_result


def test_percentile_uses_sorted_samples() -> None:
    assert percentile([5.0, 1.0, 9.0, 3.0], 50) == 3.0


def test_summarize_result_marks_failed_when_p99_exceeds_target() -> None:
    result = summarize_result("GET /agents", [10.0, 20.0, 80.0], target_ms_p99=50.0)

    assert result["passed"] is False
    assert result["p99_ms"] == 80.0


def test_run_slo_benchmark_returns_machine_readable_report() -> None:
    class FakeBenchClient:
        def list_agents(self) -> dict[str, object]:
            return {"agents": [{"id": "shell"}]}

        def list_sessions(self) -> dict[str, object]:
            return {"sessions": [{"id": "s_1"}]}

        def fleet_health(self) -> dict[str, object]:
            return {"instances": []}

        def audit_events(self, limit: int = 500) -> dict[str, object]:
            return {"events": [], "limit": limit}

        def fleet_probe(self) -> dict[str, object]:
            return {"probed": 0}

        def run_session(self, agent_id: str, cwd: str | None, message: str) -> dict[str, object]:
            return {"id": "s_new", "agent_id": agent_id, "cwd": cwd, "status": "succeeded"}

        def retry_session(self, session_id: str) -> dict[str, object]:
            return {"id": "s_retry", "agent_id": "shell", "status": "succeeded"}

        def diagnostics_resources(self) -> dict[str, object]:
            return {
                "rss_bytes": 1024,
                "sqlite_wal_bytes": 0,
                "session_count": 1,
                "audit_event_count": 0,
                "fleet_event_count": 0,
            }

    report = run_slo_benchmark(FakeBenchClient(), iterations=2)

    assert report["iterations"] == 2
    assert report["passed"] is True
    assert {item["name"] for item in report["results"]} >= {"GET /agents", "POST /sessions"}
    assert report["resources"]["rss_bytes"] == 1024


def test_run_slo_benchmark_retries_terminal_session_only() -> None:
    class FakeBenchClient:
        def __init__(self) -> None:
            self.retried: list[str] = []

        def list_agents(self) -> dict[str, object]:
            return {"agents": []}

        def list_sessions(self) -> dict[str, object]:
            return {
                "sessions": [
                    {"id": "s_running", "status": "running"},
                    {"id": "s_failed", "status": "failed"},
                ]
            }

        def fleet_health(self) -> dict[str, object]:
            return {"instances": []}

        def audit_events(self, limit: int = 500) -> dict[str, object]:
            return {"events": [], "limit": limit}

        def fleet_probe(self) -> dict[str, object]:
            return {"probed": 0}

        def run_session(self, agent_id: str, cwd: str | None, message: str) -> dict[str, object]:
            raise AssertionError("no agent exists, so run_session should not be called")

        def retry_session(self, session_id: str) -> dict[str, object]:
            if session_id != "s_failed":
                raise AssertionError(f"unexpected retry target: {session_id}")
            self.retried.append(session_id)
            return {"id": "s_retry", "agent_id": "shell", "status": "succeeded"}

        def diagnostics_resources(self) -> dict[str, object]:
            return {
                "rss_bytes": 1024,
                "sqlite_wal_bytes": 0,
                "session_count": 2,
                "audit_event_count": 0,
                "fleet_event_count": 0,
            }

    client = FakeBenchClient()
    report = run_slo_benchmark(client, iterations=1)

    assert client.retried == ["s_failed"]
    assert "POST /sessions/{id}/retry" in {item["name"] for item in report["results"]}
