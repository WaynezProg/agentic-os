# 010 -- SLO Benchmark Harness (P8)

Status: Planned
Date: 2026-05-29

## Positioning

P8 makes the SLO targets in `specs/008-harness-fleet-control-plane-goals.md`
measurable on a developer machine. It does not optimize the daemon by itself.
It adds a repeatable benchmark command, resource snapshot endpoint, and report
format so regressions can be seen before later feature work.

This remains a deterministic local harness. It does not add Prometheus, Grafana,
OpenTelemetry, cloud telemetry, or a long-running metrics daemon.

## Goals

1. **Repeatable latency benchmark** -- measure p50, p95, and p99 for key daemon
   read/write routes with a synthetic local registry and state directory.

2. **Probe round measurement** -- measure an on-demand `/fleet/probe` round for
   responsive instances and separately count timed-out probes.

3. **Resource snapshot** -- expose daemon RSS, SQLite DB/WAL file sizes, session
   count, audit event count, and fleet event count through a diagnostics API.

4. **Machine-readable report** -- produce JSON that can be checked into
   artifacts or compared between runs.

5. **Non-invasive by default** -- benchmarks run against an explicit test state
   directory and registry path, not the operator's live `.agentic-os` state.

## SLO Targets Covered

| Target from 008 | P8 measurement |
|-----------------|----------------|
| GET list p99 <= 50 ms | repeated GET `/agents`, `/sessions`, `/fleet/health`, `/audit/events` |
| POST run/retry p99 <= 200 ms | short local `/sessions` and `/sessions/{id}/retry` |
| Health probe round <= 5 s for responsive instances | `/fleet/probe` wall-clock excluding timed-out probes from pass/fail |
| Daemon RSS <= 256 MB | diagnostics endpoint RSS snapshot |
| SQLite WAL <= 64 MB | diagnostics endpoint DB/WAL file sizes |

## API Contract

New route:

- `GET /diagnostics/resources` returns:

```json
{
  "pid": 12345,
  "rss_bytes": 73400320,
  "state_dir_bytes": 1048576,
  "sqlite_db_bytes": 524288,
  "sqlite_wal_bytes": 0,
  "session_count": 10,
  "audit_event_count": 25,
  "fleet_event_count": 5
}
```

The endpoint is local-only by deployment assumption, matching the rest of the
daemon. It must not expose secrets, argv env values, log contents, or memory
payloads.

## CLI Contract

New command:

```bash
agentctl bench slo --api http://127.0.0.1:8767 --iterations 100 --output report.json
```

Output:

- Human summary to stdout.
- Full JSON report when `--output` is provided.
- Exit code `1` when `--api` is omitted; the benchmark must point at an
  explicitly started test daemon.
- Exit code `0` when all measured targets pass.
- Exit code `2` when one or more SLO targets fail.

## Report Shape

```json
{
  "started_at": "2026-05-29T00:00:00Z",
  "api": "http://127.0.0.1:8767",
  "iterations": 100,
  "results": [
    {
      "name": "GET /agents",
      "target_ms_p99": 50,
      "p50_ms": 3.0,
      "p95_ms": 7.0,
      "p99_ms": 9.0,
      "passed": true
    }
  ],
  "resources": {
    "rss_bytes": 73400320,
    "sqlite_wal_bytes": 0
  },
  "passed": true
}
```

## Non-Goals

- No continuous monitoring daemon.
- No hosted telemetry or remote aggregation.
- No synthetic LLM/model calls.
- No automatic performance tuning.
- No benchmark claims across different machines.
