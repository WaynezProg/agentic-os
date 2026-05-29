# P7 Human Approval Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable local operator approval workflow for launch-policy `approval_required` decisions.

**Architecture:** Add an `ApprovalStore` backed by SQLite, wire it into `api.py`, and keep the daemon as the only process owner. Approval stores the rendered run payload, approval re-checks policy before spawning, and all lifecycle transitions write governance audit events.

**Tech Stack:** Python 3.12, FastAPI, Typer, SQLite, pytest, ruff, static HTML/CSS/JavaScript.

---

## File Structure

- Create: `src/agentic_os/approvals.py` -- approval dataclasses, SQLite schema, state transitions.
- Modify: `src/agentic_os/api.py` -- approval store wiring, approval-required branch, approval endpoints.
- Modify: `src/agentic_os/client.py` -- approval client methods.
- Modify: `src/agentic_os/cli.py` -- `agentctl approvals` subgroup.
- Modify: `apps/web/index.html` -- Approvals section.
- Modify: `apps/web/app.js` -- load/approve/reject approval requests.
- Modify: `tests/test_approvals.py` -- store tests.
- Modify: `tests/test_api.py` -- approval API and run/retry integration tests.
- Modify: `tests/test_cli.py` -- approval CLI tests.
- Modify: `tests/test_web.py` -- static UI contract tests.
- Modify: `README.md`, `CLAUDE.md` -- P7 usage and scope.

### Task 1: ApprovalStore

**Files:**
- Create: `src/agentic_os/approvals.py`
- Test: `tests/test_approvals.py`

- [ ] **Step 1: Write failing store tests**

```python
from pathlib import Path

import pytest

from agentic_os.approvals import ApprovalCreate, ApprovalStatus, ApprovalStore


def make_store(tmp_path: Path) -> ApprovalStore:
    store = ApprovalStore(tmp_path / "agentic-os.db")
    store.init()
    return store


def test_create_list_show_and_reject_approval(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    approval = store.create(
        ApprovalCreate(
            source_session_id="s_blocked",
            agent_id="shell",
            cwd=str(tmp_path),
            argv=["/usr/bin/printf", "OK"],
            env={"A": "B"},
            reason="session.start requires approval",
        )
    )

    assert approval.status == ApprovalStatus.PENDING
    assert store.get(approval.id).source_session_id == "s_blocked"
    assert [item.id for item in store.list()] == [approval.id]

    rejected = store.reject(approval.id, "not needed")
    assert rejected.status == ApprovalStatus.REJECTED
    assert rejected.decision_reason == "not needed"


def test_approve_sets_approved_session_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    approval = store.create(
        ApprovalCreate(
            source_session_id="s_blocked",
            agent_id="shell",
            cwd=str(tmp_path),
            argv=["/bin/echo", "OK"],
            env={},
            reason="session.start requires approval",
        )
    )

    approved = store.approve(approval.id, approved_session_id="s_started")
    assert approved.status == ApprovalStatus.APPROVED
    assert approved.approved_session_id == "s_started"

    with pytest.raises(ValueError):
        store.reject(approval.id, "too late")
```

- [ ] **Step 2: Run store tests to verify failure**

Run: `rtk uv run pytest tests/test_approvals.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'agentic_os.approvals'`.

- [ ] **Step 3: Implement `ApprovalStore` minimally**

Create `src/agentic_os/approvals.py` with:

```python
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


APPROVAL_STATUS_SQL = ", ".join(f"'{status.value}'" for status in ApprovalStatus)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  source_session_id TEXT NOT NULL,
  approved_session_id TEXT,
  agent_id TEXT NOT NULL,
  cwd TEXT NOT NULL,
  argv_json TEXT NOT NULL,
  env_json TEXT NOT NULL DEFAULT '{{}}',
  reason TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ({APPROVAL_STATUS_SQL})),
  decision_reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True)
class ApprovalCreate:
    source_session_id: str
    agent_id: str
    cwd: str
    argv: list[str]
    env: dict[str, str]
    reason: str


@dataclass(frozen=True)
class ApprovalRecord:
    id: str
    source_session_id: str
    approved_session_id: str | None
    agent_id: str
    cwd: str
    argv: list[str]
    env: dict[str, str]
    reason: str
    status: ApprovalStatus
    decision_reason: str
    created_at: str
    updated_at: str


class ApprovalStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, request: ApprovalCreate) -> ApprovalRecord:
        approval_id = f"ap_{uuid.uuid4().hex}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals (
                  id, source_session_id, agent_id, cwd, argv_json, env_json, reason, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    request.source_session_id,
                    request.agent_id,
                    request.cwd,
                    json.dumps(request.argv),
                    json.dumps(request.env),
                    request.reason,
                    ApprovalStatus.PENDING.value,
                ),
            )
        return self.get(approval_id)

    def list(self) -> list[ApprovalRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM approvals
                ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, updated_at DESC, id DESC
                """
            ).fetchall()
        return [_from_row(row) for row in rows]

    def get(self, approval_id: str) -> ApprovalRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            raise KeyError(approval_id)
        return _from_row(row)

    def approve(self, approval_id: str, approved_session_id: str) -> ApprovalRecord:
        current = self.get(approval_id)
        if current.status != ApprovalStatus.PENDING:
            raise ValueError(f"approval {approval_id} is not pending")
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE approvals
                SET status = ?, approved_session_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (ApprovalStatus.APPROVED.value, approved_session_id, approval_id),
            )
        return self.get(approval_id)

    def reject(self, approval_id: str, reason: str) -> ApprovalRecord:
        current = self.get(approval_id)
        if current.status != ApprovalStatus.PENDING:
            raise ValueError(f"approval {approval_id} is not pending")
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE approvals
                SET status = ?, decision_reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (ApprovalStatus.REJECTED.value, reason, approval_id),
            )
        return self.get(approval_id)


def _from_row(row: sqlite3.Row) -> ApprovalRecord:
    return ApprovalRecord(
        id=row["id"],
        source_session_id=row["source_session_id"],
        approved_session_id=row["approved_session_id"],
        agent_id=row["agent_id"],
        cwd=row["cwd"],
        argv=[str(value) for value in json.loads(row["argv_json"])],
        env={str(k): str(v) for k, v in json.loads(row["env_json"]).items()},
        reason=row["reason"],
        status=ApprovalStatus(row["status"]),
        decision_reason=row["decision_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
```

- [ ] **Step 4: Run store tests**

Run: `rtk uv run pytest tests/test_approvals.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/approvals.py tests/test_approvals.py
git commit -m "feat(p7): add approval request store"
```

### Task 2: API approval lifecycle

**Files:**
- Modify: `src/agentic_os/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests that:

- configure policy with `approval_required_tool_names=["session.start"]`;
- call `POST /sessions`;
- assert HTTP 409 includes `approval_id`;
- list `/approvals`;
- approve the request;
- assert a new session starts and audit events exist;
- reject a second request and assert no new session starts.

- [ ] **Step 2: Run API tests to verify failure**

Run: `rtk uv run pytest tests/test_api.py -q`

Expected: FAIL because `/approvals` routes and `approval_id` response field do not exist.

- [ ] **Step 3: Wire `ApprovalStore` in `create_app`**

In `src/agentic_os/api.py`, initialize:

```python
approval_store = ApprovalStore(state_dir / "agentic-os.db")
approval_store.init()
app.state.approval_store = approval_store
```

- [ ] **Step 4: Create approval in `_reject_session` for approval-required decisions**

When `result.decision == "approval_required"`, create an approval from the
shadow session and include `approval_id` in the JSON response. Record
`approval_requested` audit metadata with `approval_id` and `source_session_id`.

- [ ] **Step 5: Add approval endpoints**

Implement:

```python
@app.get("/approvals")
def list_approvals() -> dict[str, object]: ...

@app.get("/approvals/{approval_id}")
def show_approval(approval_id: str) -> dict[str, object]: ...

@app.post("/approvals/{approval_id}/approve")
def approve_approval(approval_id: str) -> dict[str, object]: ...

@app.post("/approvals/{approval_id}/reject")
def reject_approval(approval_id: str, request: ApprovalRejectRequest) -> dict[str, object]: ...
```

- [ ] **Step 6: Run API tests**

Run: `rtk uv run pytest tests/test_api.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat(p7): add approval workflow API"
```

### Task 3: CLI and client

**Files:**
- Modify: `src/agentic_os/client.py`
- Modify: `src/agentic_os/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Add tests for:

```bash
agentctl approvals list
agentctl approvals show ap_1
agentctl approvals approve ap_1
agentctl approvals reject ap_1 --reason "not needed"
```

- [ ] **Step 2: Run CLI tests**

Run: `rtk uv run pytest tests/test_cli.py -q`

Expected: FAIL because approval client methods and Typer subgroup do not exist.

- [ ] **Step 3: Add client methods**

Add `list_approvals`, `show_approval`, `approve_approval`, and
`reject_approval` to `AgenticClient`.

- [ ] **Step 4: Add `approvals` Typer subgroup**

Mirror existing `fleet` and `audit` command patterns. Print tab-separated rows
for list and JSON for show/approve/reject.

- [ ] **Step 5: Run CLI tests**

Run: `rtk uv run pytest tests/test_cli.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/client.py src/agentic_os/cli.py tests/test_cli.py
git commit -m "feat(p7): expose approvals in CLI"
```

### Task 4: Static UI

**Files:**
- Modify: `apps/web/index.html`
- Modify: `apps/web/app.js`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing UI contract tests**

Assert `index.html` contains `id="approvals-table"`, `id="approvals-body"`,
and `app.js` references `/approvals`, `approveApproval`, and `rejectApproval`.

- [ ] **Step 2: Run UI tests**

Run: `rtk uv run pytest tests/test_web.py -q`

Expected: FAIL.

- [ ] **Step 3: Add approvals table and JS handlers**

Add a thin table-oriented Approvals section. Buttons call `POST
/approvals/{id}/approve` and `POST /approvals/{id}/reject`, then reload the
section.

- [ ] **Step 4: Run UI tests**

Run: `rtk uv run pytest tests/test_web.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/index.html apps/web/app.js tests/test_web.py
git commit -m "feat(p7): add approvals to static UI"
```

### Task 5: Docs and final verification

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update docs**

Document approval API and CLI usage under a new P7 section.

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
git commit -m "docs(p7): document approval workflow"
```
