# 019 Workflow Catalog Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand `_HARNESS_SCOPES` to six harnesses, implement TOML scanning for OpenClaw/Hermes, dedupe catalog allowlists in `api.py`, and wire Surfaces tab harness selector.

**Architecture:** Extend `catalog.py`; add `_require_catalog_harness()` in `api.py` using `SUPPORTED_HARNESSES`; return HTTP 400 with structured detail for unknown harness (matches existing status code).

**Tech Stack:** Python 3.12, pathlib, tomllib/json loaders.

---

## File Structure

| File | Changes |
|------|---------|
| `src/agentic_os/catalog.py` | `_HARNESS_SCOPES` + TOML scanner |
| `src/agentic_os/api.py` | `_require_catalog_harness()`; remove 3 hardcoded tuples |
| `tests/test_catalog.py` | Six harness + TOML tests |
| `tests/test_api.py` | 400 unsupported harness test |
| `apps/web/index.html` | Harness `<select>` on Surfaces tab |
| `apps/web/app.js` | Pass selected harness to catalog API |
| `tests/test_web.py` | Dropdown presence |
| `specs/014-workflow-surface-catalog.md` | Note TOML gap closed |
| `specs/019-workflow-catalog-expansion.md` | Status → Implemented |

---

### Task 1: Expand _HARNESS_SCOPES

**Files:**
- Modify: `src/agentic_os/catalog.py:16-32`
- Test: `tests/test_catalog.py`

- [ ] **Step 1: Write failing test**

```python
def test_supported_harnesses_includes_six():
    from agentic_os.catalog import SUPPORTED_HARNESSES

    assert set(SUPPORTED_HARNESSES) == {
        "claude", "codex", "opencode", "qwen", "openclaw", "hermes"
    }
```

- [ ] **Step 2: Add codex, opencode, qwen scope entries**

Per `specs/019-workflow-catalog-expansion.md` path table.

- [ ] **Step 3: Run test — PASS**

Run: `rtk uv run pytest tests/test_catalog.py::test_supported_harnesses_includes_six -v`

- [ ] **Step 4: Commit**

---

### Task 2: Implement _scan_toml_config

**Files:**
- Modify: `src/agentic_os/catalog.py`
- Test: `tests/test_catalog.py`

- [ ] **Step 1: Write failing TOML test with fixture config.toml**

```python
def test_scan_openclaw_toml_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    oc = home / ".openclaw"
    oc.mkdir(parents=True)
    (oc / "config.toml").write_text('[agent]\nname = "main"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    from agentic_os.catalog import scan

    records = scan("openclaw", str(tmp_path))
    assert len(records) >= 1
```

- [ ] **Step 2: Implement _scan_toml_config**

Parse TOML; emit one `permission` SurfaceRecord per top-level `[section]`.

- [ ] **Step 3: Run catalog tests**

Run: `rtk uv run pytest tests/test_catalog.py -q`

- [ ] **Step 4: Commit**

---

### Task 3: Deduplicate api.py catalog allowlist

**Files:**
- Modify: `src/agentic_os/api.py` (catalog routes ~1055–1095)
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing test for unknown harness**

```python
def test_catalog_unknown_harness_returns_400_with_supported(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/catalog/unknown/merged", params={"cwd": str(tmp_path)})
    assert response.status_code == 400
    detail = response.json()["detail"]
    if isinstance(detail, dict):
        assert detail["message"] == "unsupported harness: unknown"
        assert "claude" in detail["supported"]
    else:
        assert "unsupported harness" in detail
```

- [ ] **Step 2: Add helper near catalog routes**

```python
from agentic_os.catalog import SUPPORTED_HARNESSES

def _require_catalog_harness(harness: str) -> None:
    if harness not in SUPPORTED_HARNESSES:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"unsupported harness: {harness}",
                "supported": list(SUPPORTED_HARNESSES),
            },
        )
```

- [ ] **Step 3: Replace all three `if harness not in ("claude", ...)` blocks**

Call `_require_catalog_harness(harness)` at the start of `catalog_surfaces`,
`catalog_merged`, and `catalog_diff_endpoint`.

- [ ] **Step 4: Run tests**

Run: `rtk uv run pytest tests/test_api.py -k catalog_unknown -v`

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat: dedupe catalog harness allowlist via SUPPORTED_HARNESSES"
```

---

### Task 4: Surfaces tab harness selector

**Files:**
- Modify: `apps/web/index.html`, `apps/web/app.js`, `tests/test_web.py`

- [ ] **Step 1: Add `<select id="catalog-harness">` with six options**

- [ ] **Step 2: Update loadCatalog() to read selector value**

- [ ] **Step 3: Show empty state message when surfaces array empty**

- [ ] **Step 4: Update test_web.py**

- [ ] **Step 5: Run tests**

Run: `rtk uv run pytest tests/test_web.py tests/test_catalog.py -q`

- [ ] **Step 6: Commit + mark spec Implemented**

---

## Self-Review

- [ ] SUPPORTED_HARNESSES length 6
- [ ] api.py has no hardcoded harness tuple
- [ ] Unknown harness returns 400 with supported list
- [ ] TOML scanner non-stub for openclaw/hermes
- [ ] UI harness dropdown wired
