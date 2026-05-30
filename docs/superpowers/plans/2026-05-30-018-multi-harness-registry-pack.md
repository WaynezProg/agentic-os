# 018 Multi-Harness Registry Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register six harness instances in `examples/agents.toml` with full P3.7 profile fields, add registry validation endpoint, and verify fleet health lists all instances.

**Architecture:** Extend `registry.py` with validation helper; populate TOML from 018 command matrix; expose `GET /harnesses/validate`; tests use stub commands, smoke doc uses real CLIs.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, TOML, existing fleet prober.

---

## File Structure

| File | Changes |
|------|---------|
| `examples/agents.toml` | Add claude, codex, opencode, qwen; enrich openclaw/hermes |
| `src/agentic_os/registry.py` | Add `validate_registry()` |
| `src/agentic_os/api.py` | Add `GET /harnesses/validate` |
| `src/agentic_os/cli.py` | Add `agentctl harnesses validate` |
| `src/agentic_os/client.py` | Add `harnesses_validate()` |
| `tests/test_registry.py` | Validation tests |
| `tests/test_api.py` | Validate endpoint test |
| `tests/test_cli.py` | CLI validate test |
| `specs/018-multi-harness-registry-pack.md` | Status → Implemented |
| `README.md` | Real agent smoke list all six |

---

### Task 1: Populate agents.toml

**Files:**
- Modify: `examples/agents.toml`

- [ ] **Step 1: Add claude agent block**

```toml
[[agents]]
id = "claude"
label = "Claude Code"
command = ["claude", "-p", "{{message}}", "--output-format", "text"]
cwd_mode = "required"
stop_policy = "process_group"
health_command = ["claude", "--version"]
version_command = ["claude", "--version"]
config_fingerprint_command = ["claude", "--version"]
config_path = "~/.claude"
workspace_roots = ["~/bootstrap", "~/work"]
log_paths = ["~/.claude/projects"]
default_provider = "anthropic"
```

- [ ] **Step 2: Add codex, opencode, qwen blocks**

Use command matrix from `specs/018-multi-harness-registry-pack.md`. For qwen
use `log_paths = ["~/.qwen/debug"]`. For openclaw/hermes set
`config_fingerprint_command` to status commands (`openclaw status --json`,
`hermes status`).

- [ ] **Step 3: Enrich openclaw and hermes**

Add missing fields: `config_path`, `workspace_roots`, `log_paths`,
`default_provider`, `version_command`, `config_fingerprint_command`,
`attach_command` (openclaw/hermes only).

- [ ] **Step 4: Commit**

```bash
git add examples/agents.toml
git commit -m "feat: add six-harness registry pack to agents.toml"
```

---

### Task 2: Registry validation

**Files:**
- Modify: `src/agentic_os/registry.py`
- Test: `tests/test_registry.py`

- [ ] **Step 1: Write failing validation test**

```python
def test_validate_registry_requires_health_command(tmp_path):
    toml_path = tmp_path / "agents.toml"
    toml_path.write_text(
        """\
[[agents]]
id = "bad"
label = "Bad"
command = ["echo", "hi"]
config_path = "~/.bad"
default_provider = "x"
version_command = ["echo", "1"]
config_fingerprint_command = ["echo", "f"]
""",
        encoding="utf-8",
    )
    from agentic_os.registry import Registry, validate_registry

    reg = Registry(toml_path)
    errors = validate_registry(reg.list_agents())
    assert any("health_command" in e for e in errors)
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `rtk uv run pytest tests/test_registry.py::test_validate_registry_requires_health_command -v`

- [ ] **Step 3: Implement validate_registry**

```python
def validate_registry(agents: list[AgentDefinition]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for agent in agents:
        if agent.id == "shell":
            continue
        if not agent.health_command:
            errors.append(f"{agent.id}: missing health_command")
        if not agent.config_path:
            errors.append(f"{agent.id}: missing config_path")
        if not agent.default_provider:
            errors.append(f"{agent.id}: missing default_provider")
        if not agent.version_command:
            errors.append(f"{agent.id}: missing version_command")
        if not agent.config_fingerprint_command:
            errors.append(f"{agent.id}: missing config_fingerprint_command")
        if not agent.log_paths:
            warnings.append(f"{agent.id}: empty log_paths")
    return errors, warnings
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `rtk uv run pytest tests/test_registry.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/registry.py tests/test_registry.py
git commit -m "feat: add registry validation for harness profile fields"
```

---

### Task 3: API and CLI validate endpoint

**Files:**
- Modify: `src/agentic_os/api.py`, `cli.py`, `client.py`
- Test: `tests/test_api.py`, `tests/test_cli.py`

- [ ] **Step 1: Write failing API test**

```python
def test_harnesses_validate_ok(client):
    response = client.get("/harnesses/validate")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["errors"] == []
```

- [ ] **Step 2: Implement GET /harnesses/validate**

Return `{"ok": len(errors)==0, "errors": errors, "warnings": warnings}`.

- [ ] **Step 3: Add CLI `agentctl harnesses validate`**

- [ ] **Step 4: Run tests**

Run: `rtk uv run pytest tests/test_api.py -k validate tests/test_cli.py -k validate -q`

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/api.py src/agentic_os/cli.py src/agentic_os/client.py tests/
git commit -m "feat: expose harness registry validation via API and CLI"
```

---

### Task 4: Acceptance smoke script (manual — not CI)

**Files:**
- Create: `scripts/smoke-six-harnesses.sh`

- [ ] **Step 1: Add script that runs each harness with message OK**

Document in README. Script is **manual operator smoke only** — do not wire into
`pytest` or CI (CI continues to use `shell` only).

- [ ] **Step 2: Manual smoke**

Run each: `rtk uv run agentctl run <id> --cwd "$PWD" --message "OK"`

- [ ] **Step 3: Update spec 018 status → Implemented**

- [ ] **Step 4: Update spec 007 status → Implemented via 018** (same PR)

- [ ] **Step 5: Final commit**

```bash
git add scripts/smoke-six-harnesses.sh specs/018-multi-harness-registry-pack.md README.md
git commit -m "docs: 018 acceptance smoke and spec Implemented"
```

---

## Self-Review

- [ ] Six non-shell agents in TOML
- [ ] validate_registry covers required fields
- [ ] API/CLI validate exposed
- [ ] Fleet health lists six ids after probe cycle
