# P8 SLO Benchmark Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the P4/P8 control-plane SLO targets measurable through local diagnostics and a repeatable benchmark command.

**Architecture:** Add a diagnostics module/API for resource snapshots and a benchmark runner that drives the existing HTTP API through `AgenticClient`. Keep metrics local, deterministic, and dependency-free.

**Tech Stack:** Python 3.12, FastAPI, Typer, SQLite, stdlib timing/statistics, pytest, ruff.

---

## File Structure

- Create: `src/agentic_os/diagnostics.py` -- resource snapshot and DB/WAL sizing.
- Create: `src/agentic_os/bench.py` -- SLO benchmark runner and report dataclasses.
- Modify: `src/agentic_os/api.py` -- `GET /diagnostics/resources`.
- Modify: `src/agentic_os/client.py` -- diagnostics client method.
- Modify: `src/agentic_os/cli.py` -- `agentctl bench slo`.
- Modify: `tests/test_diagnostics.py` -- diagnostics unit tests.
- Modify: `tests/test_api.py` -- diagnostics API tests.
- Modify: `tests/test_cli.py` -- benchmark CLI tests with fake client.
- Modify: `README.md`, `CLAUDE.md` -- P8 usage and scope.

### Task 1: Diagnostics snapshot

**Files:**
- Create: `src/agentic_os/diagnostics.py`
- Test: `tests/test_diagnostics.py`

- [ ] **Step 1: Write failing diagnostics tests**

```python
from pathlib import Path

from agentic_os.diagnostics import resource_snapshot


def test_resource_snapshot_reports_sqlite_file_sizes(tmp_path: Path) -> None:
    db = tmp_path / "agentic-os.db"
    db.write_bytes(b"1234")
    wal = tmp_path / "agentic-os.db-wal"
    wal.write_bytes(b"12")

    snap = resource_snapshot(tmp_path, db)

    assert snap["sqlite_db_bytes"] == 4
    assert snap["sqlite_wal_bytes"] == 2
    assert snap["state_dir_bytes"] >= 6
    assert snap["pid"] > 0
    assert snap["rss_bytes"] >= 0
```

- [ ] **Step 2: Run test to verify failure**

Run: `rtk uv run pytest tests/test_diagnostics.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement diagnostics**

Create `src/agentic_os/diagnostics.py`:

```python
from __future__ import annotations

import os
import resource
from pathlib import Path


def resource_snapshot(state_dir: Path, sqlite_path: Path) -> dict[str, int]:
    return {
        "pid": os.getpid(),
        "rss_bytes": _rss_bytes(),
        "state_dir_bytes": _dir_size(state_dir),
        "sqlite_db_bytes": _file_size(sqlite_path),
        "sqlite_wal_bytes": _file_size(Path(f"{sqlite_path}-wal")),
    }


def _rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # macOS returns bytes; Linux returns KiB. Keep macOS primary, avoid failure
    # by returning a non-negative integer on every platform.
    return max(int(usage.ru_maxrss), 0)


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
```

- [ ] **Step 4: Run diagnostics tests**

Run: `rtk uv run pytest tests/test_diagnostics.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/diagnostics.py tests/test_diagnostics.py
git commit -m "feat(p8): add diagnostics resource snapshot"
```

### Task 2: Diagnostics API and client

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `src/agentic_os/client.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing API test**

Add `test_diagnostics_resources_endpoint` asserting `GET
/diagnostics/resources` returns `rss_bytes`, `sqlite_db_bytes`,
`sqlite_wal_bytes`, `session_count`, `audit_event_count`, and
`fleet_event_count`.

- [ ] **Step 2: Run API test**

Run: `rtk uv run pytest tests/test_api.py::test_diagnostics_resources_endpoint -q`

Expected: FAIL with HTTP 404.

- [ ] **Step 3: Add endpoint**

In `api.py`, return `resource_snapshot(state_dir, state_dir / "agentic-os.db")`
plus counts from existing stores.

- [ ] **Step 4: Add client method**

Add `diagnostics_resources()` to `AgenticClient`.

- [ ] **Step 5: Run API tests**

Run: `rtk uv run pytest tests/test_api.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/api.py src/agentic_os/client.py tests/test_api.py
git commit -m "feat(p8): expose diagnostics resources API"
```

### Task 3: Benchmark runner

**Files:**
- Create: `src/agentic_os/bench.py`
- Test: `tests/test_bench.py`

- [ ] **Step 1: Write failing benchmark tests**

Create tests for percentile calculation and report pass/fail status:

```python
from agentic_os.bench import percentile, summarize_result


def test_percentile_uses_sorted_samples() -> None:
    assert percentile([5.0, 1.0, 9.0, 3.0], 50) == 3.0


def test_summarize_result_marks_failed_when_p99_exceeds_target() -> None:
    result = summarize_result("GET /agents", [10.0, 20.0, 80.0], target_ms_p99=50.0)
    assert result["passed"] is False
    assert result["p99_ms"] == 80.0
```

- [ ] **Step 2: Run test to verify failure**

Run: `rtk uv run pytest tests/test_bench.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement benchmark helpers**

Implement `percentile`, `summarize_result`, and `run_slo_benchmark(client,
iterations)` using `time.perf_counter()` around existing client calls.

- [ ] **Step 4: Run benchmark unit tests**

Run: `rtk uv run pytest tests/test_bench.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/bench.py tests/test_bench.py
git commit -m "feat(p8): add SLO benchmark runner"
```

### Task 4: CLI command

**Files:**
- Modify: `src/agentic_os/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Add a fake client that returns stable responses and assert:

```bash
agentctl bench slo --api http://127.0.0.1:8767 --iterations 3
agentctl bench slo --api http://127.0.0.1:8767 --iterations 3 --output /tmp/report.json
```

The command must fail without `--api`, and the output file must contain JSON
with top-level `passed`.

- [ ] **Step 2: Run CLI tests**

Run: `rtk uv run pytest tests/test_cli.py -q`

Expected: FAIL because `bench` subgroup does not exist.

- [ ] **Step 3: Add `bench slo` command**

Add `bench = typer.Typer(...)`, then `bench.command("slo")`. The command calls
`run_slo_benchmark`, echoes a compact summary, writes JSON when requested, and
raises `typer.Exit(2)` when `passed` is false.

- [ ] **Step 4: Run CLI tests**

Run: `rtk uv run pytest tests/test_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/cli.py tests/test_cli.py
git commit -m "feat(p8): expose SLO benchmark CLI"
```

### Task 5: Docs and final verification

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document benchmark usage**

Add P8 commands:

```bash
rtk uv run agentctl bench slo --api http://127.0.0.1:8797 --iterations 100 --output .agentic-os-bench/slo-report.json
curl http://127.0.0.1:8767/diagnostics/resources
```

- [ ] **Step 2: Run full gate**

Run:

```bash
rtk uv run pytest -q
rtk uv run ruff check .
git diff --check
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs(p8): document SLO benchmark workflow"
```
