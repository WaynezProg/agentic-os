# 023 Session Attach Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **GATE:** Do not start until 018–022 gate checklist in `specs/023-session-attach-contract.md` is signed off in PR description.

**Goal:** Define attach preview/exec contract, extend session model with external_session_id, implement POST /sessions/{id}/attach for supported harnesses.

**Architecture:** SQLite migration for new session columns; parse external id from harness JSON stdout where available; policy gate on exec mode; no PTY UI.

**Tech Stack:** Python 3.12, FastAPI, SQLite migration in storage.py.

---

## Gate sign-off (manual, before Task 1)

- [ ] Six harness runs completed with logs
- [ ] Fleet health records for six ids
- [ ] Catalog merged for six harnesses
- [ ] harness-config effective works (claude + openclaw)
- [ ] Timeline shows log_chunk
- [ ] Overview/Runs/Approvals visual OK

Record sign-off: `Gate approved YYYY-MM-DD by <operator>` in spec 023 header.

---

## File Structure

| File | Changes |
|------|---------|
| `src/agentic_os/models.py` | attach_status enum fields on SessionRecord |
| `src/agentic_os/storage.py` | Migration + columns |
| `src/agentic_os/supervisor.py` | Parse external_session_id from stdout (openclaw JSON) |
| `src/agentic_os/api.py` | POST /sessions/{id}/attach |
| `src/agentic_os/cli.py` | sessions attach |
| `tests/test_api.py` | preview, unsupported, policy deny |
| `apps/web/app.js` | Attach button + modal |
| `specs/023-session-attach-contract.md` | Status → Implemented |

---

### Task 1: Session model migration

**Files:**
- Modify: `models.py`, `storage.py`
- Test: `tests/test_storage.py`

Follow existing migration style in `storage.py` (e.g. `_migrate_sessions_*` using
`ALTER TABLE ... ADD COLUMN` guarded by schema inspection — see lines ~421+).

- [ ] **Step 1: Add fields to SessionRecord**

```python
external_session_id: str | None = None
attachable: bool = False
attach_status: Literal["none", "available", "attached", "unsupported"] = "none"
```

- [ ] **Step 2: SQLite migration in `_init_db` / dedicated `_migrate_sessions_attach_fields`**

```python
def _migrate_sessions_attach_fields(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "external_session_id" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN external_session_id TEXT")
    if "attachable" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN attachable INTEGER NOT NULL DEFAULT 0")
    if "attach_status" not in columns:
        conn.execute(
            "ALTER TABLE sessions ADD COLUMN attach_status TEXT NOT NULL DEFAULT 'none'"
        )
```

- [ ] **Step 3: Test round-trip read/write**

- [ ] **Step 4: Commit**

---

### Task 2: Parse external_session_id (openclaw)

**Files:**
- Modify: `supervisor.py` or log completion hook
- Test: `tests/test_supervisor.py`

- [ ] **Step 1: On session end, if agent id openclaw, scan stdout JSON for session id field**

Set `attachable=True`, `attach_status=available` when id found.

- [ ] **Step 2: Test with fixture JSON line in stdout log**

- [ ] **Step 3: Commit**

---

### Task 3: POST /sessions/{id}/attach

**Files:**
- Modify: `api.py`, `tests/test_api.py`

- [ ] **Step 1: preview mode test**

```python
def test_attach_preview_returns_argv(client, openclaw_session_with_external_id):
    r = client.post(f"/sessions/{id}/attach", json={"mode": "preview"})
    assert r.status_code == 200
    assert r.json()["decision"] == "allow"
    assert "openclaw" in r.json()["attach_command"][0]
```

- [ ] **Step 2: Implement preview — render attach_command with external id substitution**

- [ ] **Step 3: unsupported harness → decision unsupported**

- [ ] **Step 4: exec mode spawns subprocess + audit event (mock in test)**

- [ ] **Step 5: Policy deny → 403**

- [ ] **Step 6: Commit**

---

### Task 4: CLI and UI

**Files:**
- Modify: `cli.py`, `app.js`

- [ ] **Step 1: agentctl sessions attach <id> [--exec]**

- [ ] **Step 2: Timeline Attach button when attach_status available**

Modal shows preview; exec requires confirm.

- [ ] **Step 3: Commit + mark spec Implemented**

---

## Self-Review

- [ ] Gate signed off before code
- [ ] preview/exec modes work
- [ ] Harness matrix documented in responses
- [ ] No PTY/browser terminal added
