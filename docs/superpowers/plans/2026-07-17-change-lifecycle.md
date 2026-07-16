# Verified Change Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable preview/apply/verify/rollback plans over existing safe file mutations and expose them through a unified Changes API.

**Architecture:** `SafeEditEngine` remains the only external config writer. `ChangeService` adds state transitions, stale checks, redacted persistence, re-observation, and verification around existing operation builders.

**Tech Stack:** Python 3.12, SQLite, Pydantic, FastAPI, existing SafeEditEngine/BackupStore/AuditStore, pytest.

## Global Constraints

- No generic mutation DSL.
- No secret-bearing value is stored in a plan or returned by an API.
- Every apply and rollback must re-observe the target.
- Unparseable config is never treated as an empty writable document.
- Existing direct mutation APIs remain compatible.
- Control-plane SQLite entity history remains relational and is not rewritten.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/agentic_os/change_models.py` | Change requests, plans, verification, and status |
| `src/agentic_os/change_store.py` | Additive SQLite schema and plan persistence |
| `src/agentic_os/change_service.py` | Preview/apply/re-observe/verify/rollback state machine |
| `src/agentic_os/safe_edit.py` | Strict parsing and reusable target observation |
| `src/agentic_os/api.py` | Change APIs and compatibility wrappers |
| `tests/test_change_store.py` | Migration and transition persistence |
| `tests/test_change_service.py` | State machine, stale, verify, rollback |
| `tests/test_api.py` | Unified endpoints and redaction |

### Task 1: Change models and additive store

**Interfaces:**

- Produces: `ChangeRequest`, `ChangePlan`, `ChangeVerification`, `ChangeStore`.
- Consumed by: Tasks 2–4.

- [x] **Step 1: Write failing store tests**

Create `tests/test_change_store.py`:

```python
from agentic_os.change_models import ChangePlan
from agentic_os.change_store import ChangeStore


def sample_plan(environment_id: str) -> ChangePlan:
    return ChangePlan.previewed(
        operation="mcp.copy",
        environment_id=environment_id,
        target_surfaces=["config"],
        redacted_request={"server": "context7"},
        before_evidence={"mtime_ns": 10},
        diff={"added": ["mcp_servers.context7"]},
        validation={"ok": True},
    )


def test_change_plan_round_trip(tmp_path) -> None:
    store = ChangeStore(tmp_path / "state.db")
    store.init()
    plan = ChangePlan.previewed(
        operation="mcp.copy",
        environment_id="codex",
        target_surfaces=["config"],
        redacted_request={"server": "context7", "from_tool": "claude", "to_tool": "codex"},
        before_evidence={"mtime_ns": 10},
        diff={"added": ["mcp_servers.context7"]},
        validation={"ok": True},
    )
    store.create(plan)
    assert store.get(plan.id) == plan


def test_change_store_lists_newest_first(tmp_path) -> None:
    store = ChangeStore(tmp_path / "state.db")
    store.init()
    first = sample_plan("one")
    second = sample_plan("two")
    store.create(first)
    store.create(second)
    assert [item.id for item in store.list()] == [second.id, first.id]
```

- [x] **Step 2: Verify failure**

```bash
rtk uv run pytest tests/test_change_store.py -q
```

Expected: missing module failure.

- [x] **Step 3: Add models**

Create `src/agentic_os/change_models.py` with:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ChangeStatus = Literal[
    "previewed",
    "approved",
    "applying",
    "verified",
    "partial",
    "failed",
    "rolled_back",
    "rollback_failed",
    "stale",
]


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ChangeVerification(BaseModel):
    status: Literal["verified", "partial", "failed"]
    observed: dict[str, object] = Field(default_factory=dict)
    checks: list[dict[str, object]] = Field(default_factory=list)


class ChangePlan(BaseModel):
    id: str = Field(default_factory=lambda: f"chg_{uuid4().hex}")
    operation: str
    environment_id: str
    target_surfaces: list[str]
    status: ChangeStatus
    redacted_request: dict[str, object]
    before_evidence: dict[str, object]
    diff: dict[str, object]
    validation: dict[str, object]
    base_versions: dict[str, object] = Field(default_factory=dict)
    restart_requirements: list[str] = Field(default_factory=list)
    backup_ref: str | None = None
    apply_result: dict[str, object] | None = None
    verification: ChangeVerification | None = None
    rollback: dict[str, object] | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @classmethod
    def previewed(cls, **values: object) -> "ChangePlan":
        return cls(status="previewed", **values)
```

- [x] **Step 4: Add SQLite store**

Create `src/agentic_os/change_store.py`. `init()` creates:

```sql
CREATE TABLE IF NOT EXISTS change_plans (
    id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

Serialize the full validated model into `payload_json`. `create()`, `update()`,
`get()`, and `list(limit=200)` open short SQLite transactions.

- [x] **Step 5: Verify**

```bash
rtk uv run pytest tests/test_change_store.py -q
rtk uv run ruff check src/agentic_os/change_models.py src/agentic_os/change_store.py
```

- [x] **Step 6: Commit**

```bash
git add src/agentic_os/change_models.py src/agentic_os/change_store.py tests/test_change_store.py
git commit -m "feat: persist change plans"
```

### Task 2: Strict target observation

**Interfaces:**

- Produces: `ObservedTarget`, `SafeEditEngine.observe_target()`.
- Used by: Change preview, stale check, apply verification, rollback verification.

- [x] **Step 1: Write strict parsing tests**

Add to `tests/test_safe_edit.py`:

```python
def test_observe_target_refuses_malformed_json(engine, target) -> None:
    target.file_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="parse"):
        engine.observe_target(target)


def test_observe_target_returns_hash_and_mtime(engine, target) -> None:
    observed = engine.observe_target(target)
    assert observed.content_sha256
    assert observed.mtime_ns == target.file_path.stat().st_mtime_ns
    assert observed.document == {}
```

- [x] **Step 2: Verify current malformed-file failure**

```bash
rtk uv run pytest tests/test_safe_edit.py -k observe_target -q
```

Expected: failure because `observe_target` does not exist.

- [x] **Step 3: Implement strict observation**

In `safe_edit.py` add:

```python
@dataclass(frozen=True)
class ObservedTarget:
    exists: bool
    mtime_ns: int | None
    content_sha256: str
    document: dict[str, object]


def observe_target(self, target: PatchTarget) -> ObservedTarget:
    if not target.file_path.exists():
        return ObservedTarget(False, None, sha256(b"").hexdigest(), {})
    raw = target.file_path.read_bytes()
    try:
        document = _parse_document(raw.decode("utf-8"), target.file_format)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"config parse error: {exc}") from exc
    return ObservedTarget(
        exists=True,
        mtime_ns=target.file_path.stat().st_mtime_ns,
        content_sha256=sha256(raw).hexdigest(),
        document=document,
    )
```

Use the same strict parser in `apply()` so malformed JSON/TOML can no longer
fall back to `{}`.

- [x] **Step 4: Run safe-edit regression**

```bash
rtk uv run pytest tests/test_safe_edit.py tests/test_harness_config_patch.py tests/test_mcp_alignment.py -q
rtk uv run ruff check src/agentic_os/safe_edit.py
```

- [x] **Step 5: Commit**

```bash
git add src/agentic_os/safe_edit.py tests/test_safe_edit.py tests/test_harness_config_patch.py tests/test_mcp_alignment.py
git commit -m "fix: refuse malformed config observations"
```

### Task 3: ChangeService for MCP copy/remove

**Interfaces:**

- Produces: `ChangeService.preview()`, `apply()`, `rollback()`.
- Initial operations: `mcp.copy`, `mcp.remove`.

- [ ] **Step 1: Write state-machine tests**

Create `tests/test_change_service.py`:

```python
def test_mcp_copy_preview_apply_verify_and_rollback(service, home) -> None:
    plan = service.preview(
        {
            "operation": "mcp.copy",
            "environment_id": "codex",
            "from_tool": "claude",
            "to_tool": "codex",
            "server": "github",
        }
    )
    assert plan.status == "previewed"
    assert plan.backup_ref is None

    verified = service.apply(plan.id)
    assert verified.status == "verified"
    assert verified.verification.status == "verified"
    assert verified.backup_ref

    rolled_back = service.rollback(plan.id)
    assert rolled_back.status == "rolled_back"
    assert rolled_back.rollback["verified"] is True


def test_apply_refuses_stale_preview(service, home) -> None:
    plan = service.preview(sample_copy_request())
    target = home / ".codex" / "config.toml"
    target.write_text(target.read_text() + "\nmodel = \"changed\"\n", encoding="utf-8")
    stale = service.apply(plan.id)
    assert stale.status == "stale"
```

- [ ] **Step 2: Implement operation dispatch**

Create `src/agentic_os/change_service.py`. Use an explicit `if/elif` switch:

```python
def _build(self, request: dict[str, object]) -> tuple[PatchTarget, list[PatchOp], dict[str, object]]:
    operation = str(request["operation"])
    if operation == "mcp.copy":
        return mcp_alignment.build_copy_patch(
            str(request["from_tool"]),
            str(request["to_tool"]),
            str(request["server"]),
            self.home,
        )
    if operation == "mcp.remove":
        return mcp_alignment.build_remove_patch(
            str(request["environment_id"]),
            str(request["server"]),
            self.home,
        )
    raise ValueError(f"unsupported change operation: {operation}")
```

`preview()` observes before state, runs `SafeEditEngine.apply(..., dry_run=True)`,
stores a redacted plan, and never stores raw command/env/url values.

`apply()` re-observes and compares hash/mtime, marks `applying`, invokes the
engine, re-observes, compares the actual document to `PatchEngine.apply(before,
ops)`, stores verification, and records `verified`, `partial`, or `failed`.

`rollback()` invokes engine rollback, re-observes, compares to the original
before document, and records verified rollback.

- [ ] **Step 3: Verify**

```bash
rtk uv run pytest tests/test_change_service.py tests/test_mcp_alignment.py tests/test_safe_edit.py -q
rtk uv run ruff check src/agentic_os/change_service.py
```

- [ ] **Step 4: Commit**

```bash
git add src/agentic_os/change_service.py tests/test_change_service.py
git commit -m "feat: add verified MCP change plans"
```

### Task 4: Add existing config operations

**Interfaces:**

- Extends `ChangeService` with:
  `catalog.patch`, `config.patch`, `harness_config.patch`, `profile.patch`,
  `registry.patch`.

- [ ] **Step 1: Add parametrized operation tests**

For every operation, create a real temporary target, preview, apply, assert
verified state, and roll back to byte-equivalent content.

```python
@pytest.mark.parametrize(
    "operation",
    [
        "catalog.patch",
        "config.patch",
        "harness_config.patch",
        "profile.patch",
        "registry.patch",
    ],
)
def test_supported_operation_round_trip(service, operation, operation_request) -> None:
    plan = service.preview(operation_request(operation))
    assert plan.status == "previewed"
    assert service.apply(plan.id).status == "verified"
    assert service.rollback(plan.id).status == "rolled_back"
```

- [ ] **Step 2: Extract existing target builders**

Move route-local target/operation construction into named functions in the
existing owner modules:

- `catalog.build_surface_patch()`
- `config_scope.build_config_patch()`
- `harness_config.build_harness_config_patch()`
- `profiles.build_profile_patch()`
- `registry.build_registry_patch()`

Each returns `PatchTarget`, `list[PatchOp]`, and a redacted summary.

- [ ] **Step 3: Extend explicit dispatch**

Add one `elif` branch per operation in `ChangeService._build()`. Do not add a
dynamic registry or reflection.

- [ ] **Step 4: Verify all mutation suites**

```bash
rtk uv run pytest tests/test_change_service.py tests/test_catalog.py tests/test_harness_config_patch.py tests/test_profile_patch.py tests/test_registry.py tests/test_safe_edit.py -q
rtk uv run ruff check src/agentic_os
```

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/catalog.py src/agentic_os/config_scope.py src/agentic_os/harness_config.py src/agentic_os/profiles.py src/agentic_os/registry.py src/agentic_os/change_service.py tests/test_change_service.py
git commit -m "refactor: route config changes through verified plans"
```

### Task 5: Unified Change APIs and compatibility wrappers

**Interfaces:**

- Adds:
  - `POST /changes/preview`
  - `GET /changes`
  - `GET /changes/{id}`
  - `POST /changes/{id}/apply`
  - `POST /changes/{id}/rollback`

- [ ] **Step 1: Write API tests**

Add to `tests/test_api.py`:

```python
def test_change_api_preview_apply_and_list(client, mcp_fixture) -> None:
    preview = client.post("/changes/preview", json=mcp_fixture)
    assert preview.status_code == 200
    plan = preview.json()
    assert plan["status"] == "previewed"

    applied = client.post(f"/changes/{plan['id']}/apply")
    assert applied.status_code == 200
    assert applied.json()["status"] == "verified"

    listed = client.get("/changes")
    assert listed.status_code == 200
    assert listed.json()["changes"][0]["id"] == plan["id"]


def test_change_api_never_returns_secret_values(client, secret_fixture) -> None:
    response = client.post("/changes/preview", json=secret_fixture)
    assert "FAKE-SECRET" not in response.text
```

- [ ] **Step 2: Wire stores and routes**

Instantiate `ChangeStore` and `ChangeService` in `create_app()`. Map `KeyError`
to 404, stale conflict to 409, validation/parse errors to 400 or 422, and
unsupported operations to 400.

- [ ] **Step 3: Convert direct mutation routes**

Compatibility routes construct an equivalent change request:

- dry-run returns the preview fields plus `change_id`;
- explicit apply previews then applies and returns legacy fields plus
  `change_id`, `verification`, and `status`;
- rollback calls `ChangeService.rollback()` when the patch belongs to a change
  plan and falls back to legacy rollback for historical patches.

- [ ] **Step 4: Verify API compatibility**

```bash
rtk uv run pytest tests/test_api.py tests/test_cli.py tests/test_end_to_end.py tests/test_mcp_alignment.py tests/test_harness_config_patch.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/api.py tests/test_api.py tests/test_cli.py tests/test_end_to_end.py
git commit -m "feat: expose verified change APIs"
```

### Task 6: Full verification and documentation

- [ ] **Step 1: Run complete backend gates**

```bash
rtk uv run pytest -q
rtk uv run ruff check .
```

- [ ] **Step 2: Record implementation decisions**

Append exact schema, operation list, verification rules, and compatibility
behavior to `decision_log.md`. Add a README phase row for verified Changes.

- [ ] **Step 3: Commit**

```bash
git add README.md decision_log.md
git commit -m "docs: record verified change lifecycle"
```

## Self-Review

- Spec coverage: strict observation is Task 2; the durable state machine and
  re-observation are Tasks 1 and 3; all existing mutation families are Task 4;
  compatibility APIs and redaction are Task 5.
- Placeholder scan: no deferred implementation markers remain. Every operation
  is explicitly enumerated; no generic mutation registry or reflection is
  introduced.
- Type consistency: plan statuses and verification statuses match the API and
  store contracts; `backup_ref` is the only rollback handle exposed to the
  Change service.
