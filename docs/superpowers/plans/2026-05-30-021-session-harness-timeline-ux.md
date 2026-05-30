# 021 Session & Harness Timeline UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Timeline-first Runs/Logs UI; close 015 gaps (log_chunk, retry, fleet events, pagination).

**Architecture:** Extend timeline builders in `api.py`; refactor `app.js` session views; emit retry audit event in retry route. API response key is `timeline` (not `entries`).

**Tech Stack:** Python 3.12, FastAPI, vanilla JS, JSONL log reader.

---

## File Structure

| File | Changes |
|------|---------|
| `src/agentic_os/api.py` | Timeline + activity extensions |
| `src/agentic_os/logs.py` | Optional helper for log summaries |
| `apps/web/index.html` | Timeline panel DOM; tab label Runs |
| `apps/web/app.js` | loadSessionTimeline, refactor loadLogs |
| `tests/test_api.py` | log_chunk, pagination, fleet events |
| `tests/test_web.py` | Timeline panel + Runs tab label |
| `specs/015-evidence-audit-timeline.md` | Close gaps section |
| `specs/021-session-harness-timeline-ux.md` | Status → Implemented |

---

### Task 1: log_chunk timeline entries

**Files:**
- Modify: `src/agentic_os/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing test**

```python
def test_session_timeline_includes_log_chunks(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "log-chunk-test"},
    )
    assert run.status_code == 200
    session_id = run.json()["id"]
    log_dir = tmp_path / "sessions" / session_id
    stdout_log = log_dir / "stdout.jsonl"
    stdout_log.parent.mkdir(parents=True, exist_ok=True)
    stdout_log.write_text('{"line": "hello from stdout", "ts": "2026-05-30T00:00:00Z"}\n')

    response = client.get(f"/sessions/{session_id}/timeline")
    assert response.status_code == 200
    types = [e["type"] for e in response.json()["timeline"]]
    assert "log_chunk" in types
```

Adjust log path to match `JsonlLogStore` layout if different.

- [ ] **Step 2: Implement `_log_chunk_entries(session_id, limit=20)`**

Read last N lines from stdout/stderr JSONL; append to timeline builder.

- [ ] **Step 3: Run test — PASS**

Run: `rtk uv run pytest tests/test_api.py::test_session_timeline_includes_log_chunks -v`

- [ ] **Step 4: Commit**

---

### Task 2: retry_requested event

**Files:**
- Modify: `src/agentic_os/api.py` (POST retry handler)
- Test: `tests/test_api.py`

- [ ] **Step 1: On successful retry, record event with type `retry_requested`**

Use `store.append_event(session_id, "retry_requested", ...)`.

- [ ] **Step 2: Test timeline contains retry_requested after retry**

- [ ] **Step 3: Commit**

---

### Task 3: Harness activity fleet events + pagination

**Files:**
- Modify: `src/agentic_os/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Query `fleet_events` where `agent_id == harness_id`**

Use `tmp_app.state.fleet_store.list_events(agent_id=harness_id)` (field is
`agent_id`, not `harness_id`). Merge into activity response sorted by timestamp.

- [ ] **Step 2: Add query params `limit` (default 100, max 500) and `before` (ISO ts cursor)**

- [ ] **Step 3: Tests for pagination and fleet event presence**

```python
def test_harness_activity_includes_fleet_events(tmp_app) -> None:
    client = TestClient(tmp_app)
    tmp_app.state.fleet_store.record_health("shell", HealthState.UP, "OK")
    response = client.get("/harnesses/shell/activity")
    types = [e["type"] for e in response.json()["activity"]]
    assert "health_probe" in types or len(types) >= 1
```

- [ ] **Step 4: Commit**

---

### Task 4: UI timeline panel + Runs tab rename

**Files:**
- Modify: `apps/web/index.html`, `apps/web/app.js`, `tests/test_web.py`

- [ ] **Step 1: Add `#session-timeline` container below session table**

- [ ] **Step 2: Implement `loadSessionTimeline(sessionId)`**

Fetch `GET /sessions/{id}/timeline`; render from `response.timeline`.

- [ ] **Step 3: Refactor session row click → load timeline then logs**

- [ ] **Step 4: Rename tab label `Sessions` → `Runs` in index.html**

- [ ] **Step 5: Update `test_five_tabs_are_present` — replace `"Sessions"` with `"Runs"`**

- [ ] **Step 6: Add `test_session_timeline_panel_exists` checking `#session-timeline`**

- [ ] **Step 7: Approvals tab — approved_session_id button calls selectSession(id)**

- [ ] **Step 8: Commit**

---

### Task 5: Close 015 spec gaps

**Files:**
- Modify: `specs/015-evidence-audit-timeline.md`

- [ ] **Step 1: Update gap rows to ✅ with test references**

- [ ] **Step 2: Mark 021 Implemented**

- [ ] **Step 3: Commit**

---

## Self-Review

- [ ] log_chunk in timeline API (`timeline` key)
- [ ] retry_requested emitted
- [ ] fleet events use `agent_id` column
- [ ] pagination params work
- [ ] Runs tab label + test_web updated
