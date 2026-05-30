# 020 Harness Config Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read harness-native configs separately from agentic-os config (013), expose `/harness-config/` API/CLI/UI.

**Architecture:** New `harness_config.py` mirrors `config_scope.py` patterns but uses per-harness path table from spec 020. Redaction via imports from `control_plane.py`.

**Tech Stack:** Python 3.12, json, tomllib, FastAPI.

---

## File Structure

| File | Action |
|------|--------|
| `src/agentic_os/harness_config.py` | Create — effective/diff/explain |
| `tests/test_harness_config.py` | Create — 10+ tests |
| `src/agentic_os/api.py` | Add `/harness-config/` routes |
| `src/agentic_os/cli.py` | Add `harness-config` typer group |
| `src/agentic_os/client.py` | Add client methods |
| `apps/web/app.js` | Native config panel on Harnesses tab |
| `tests/test_api.py` | 3 API tests |
| `specs/020-harness-config-bridge.md` | Status → Implemented |

---

### Task 1: harness_config module — JSON harness (claude)

**Files:**
- Create: `src/agentic_os/harness_config.py`
- Create: `tests/test_harness_config.py`

- [ ] **Step 1: Write failing effective merge test**

```python
def test_claude_effective_project_overrides_user(tmp_path, monkeypatch):
    home = tmp_path / "home"
    claude_home = home / ".claude"
    claude_home.mkdir(parents=True)
    (claude_home / "settings.json").write_text('{"model": "user-model"}', encoding="utf-8")
    project = tmp_path / "repo"
    project.mkdir()
    pc = project / ".claude"
    pc.mkdir()
    (pc / "settings.json").write_text('{"model": "project-model"}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    from agentic_os.harness_config import effective

    result = effective("claude", project)
    assert result["model"] == "project-model"
```

- [ ] **Step 2: Implement resolve paths + read JSON + merge**

Priority: local > project > user (same as 013).

- [ ] **Step 3: Run test — PASS**

- [ ] **Step 4: Commit**

---

### Task 2: TOML harness support (openclaw)

**Files:**
- Modify: `src/agentic_os/harness_config.py`
- Test: `tests/test_harness_config.py`

- [ ] **Step 1: Test openclaw effective reads config.toml**

- [ ] **Step 2: Add TOML reader branch in read_harness_config**

- [ ] **Step 3: Commit**

---

### Task 3: diff and explain

**Files:**
- Modify: `src/agentic_os/harness_config.py`
- Test: `tests/test_harness_config.py`

- [ ] **Step 1: Port diff/explain structure from config_scope.py**

Reuse logic patterns, not imports from config_scope data paths.

- [ ] **Step 2: Tests for added/removed keys**

- [ ] **Step 3: Commit**

---

### Task 4: Redaction

**Files:**
- Modify: `src/agentic_os/harness_config.py`
- Test: `tests/test_harness_config.py`

- [ ] **Step 1: Test API key redaction**

```python
def test_effective_redacts_secrets(tmp_path, monkeypatch):
    # settings.json with "api_key": "sk-secret"
    # assert "sk-secret" not in str(effective(...))
```

- [ ] **Step 2: Apply _redact_dict or equivalent from control_plane**

- [ ] **Step 3: Commit**

---

### Task 5: API routes

**Files:**
- Modify: `src/agentic_os/api.py`, `tests/test_api.py`

- [ ] **Step 1: Add routes under `/harness-config/{harness_id}/`**

- [ ] **Step 2: Test distinct from `/config/`**

```python
def test_harness_config_not_agentic_os_config(client):
    r1 = client.get("/config/shell/effective?cwd=.")
    r2 = client.get("/harness-config/claude/effective?cwd=.")
    assert r1.status_code == 200
    assert r2.status_code in (200, 404)  # 404 if no files in CI env
```

- [ ] **Step 3: Commit**

---

### Task 6: CLI and UI

**Files:**
- Modify: `cli.py`, `client.py`, `apps/web/app.js`

- [ ] **Step 1: Add harness-config typer group (3 subcommands)**

- [ ] **Step 2: Harnesses tab — fetch effective on expand**

Truncate response to 4096 chars in UI.

- [ ] **Step 3: Run full suite**

Run: `rtk uv run pytest -q && rtk uv run ruff check .`

- [ ] **Step 4: Mark spec Implemented**

---

## Self-Review

- [ ] `/harness-config/` namespace separate from 013
- [ ] JSON + TOML harnesses covered
- [ ] Redaction applied
- [ ] 013 tests still pass unchanged
