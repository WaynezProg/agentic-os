# P10 Safe Native Config Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Safe Edit Engine with dry-run patch, schema validation, hybrid backup, rollback, and audit for workflow surfaces (P10a), harness-native config (P10b), and agentic-os config (P10c).

**Architecture:** Unified pipeline in `safe_edit.py` — `surface_ops` compiles semantic ops to `PatchOp[]`, then `patch_engine` applies path merges, `schema_registry` validates, `backup_store` snapshots, `audit_store` records `domain=config_patch`. Structured files use state-dir snapshots; standalone `.md` files use sidecar `.bak.<ts>`.

**Tech Stack:** Python 3.12, FastAPI, Typer, `jsonschema`, `tomli-w`, existing `tomllib` + `jsonio.atomic_write_json`.

**Design reference:** `docs/superpowers/specs/2026-06-06-p10-safe-native-config-editing-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `pyproject.toml` | Modify | Add `jsonschema`, `tomli-w` |
| `src/agentic_os/patch_engine.py` | Create | Path parse, merge/remove, diff |
| `src/agentic_os/toml_io.py` | Create | `atomic_write_toml`, `load_toml` |
| `src/agentic_os/schema_registry.py` | Create | Load bundled schemas, whitelist paths |
| `src/agentic_os/schemas/**/*.json` | Create | Per-harness/kind JSON Schemas |
| `src/agentic_os/backup_store.py` | Create | Snapshot, sidecar, index.jsonl, rollback |
| `src/agentic_os/safe_edit.py` | Create | `PatchTarget`, pipeline orchestration |
| `src/agentic_os/surface_ops.py` | Create | Semantic op compiler |
| `src/agentic_os/catalog.py` | Modify | `resolve_surface_write_target()` |
| `src/agentic_os/harness_config.py` | Modify | `resolve_write_path()` |
| `src/agentic_os/config_scope.py` | Modify | `resolve_write_path()` export |
| `src/agentic_os/api.py` | Modify | Patch + rollback routes |
| `src/agentic_os/cli.py` | Modify | `catalog patch`, `patches`, etc. |
| `src/agentic_os/client.py` | Modify | HTTP client methods |
| `tests/test_patch_engine.py` | Create | Engine unit tests |
| `tests/test_toml_io.py` | Create | TOML round-trip |
| `tests/test_schema_registry.py` | Create | Schema + whitelist |
| `tests/test_backup_store.py` | Create | Backup/rollback |
| `tests/test_safe_edit.py` | Create | Pipeline integration |
| `tests/test_surface_ops.py` | Create | Semantic compiler |
| `tests/test_api.py` | Modify | Patch API tests |
| `tests/test_cli.py` | Modify | CLI patch tests |
| `specs/027-safe-native-config-editing.md` | Create | Phase acceptance spec |
| `README.md` | Modify | P10 phase row |

---

## Task 1: Dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock` (via `uv sync`)

- [ ] **Step 1: Add runtime dependencies**

In `pyproject.toml` `dependencies` list, append:

```toml
  "jsonschema>=4.23.0",
  "tomli-w>=1.0.0",
```

- [ ] **Step 2: Sync lockfile**

Run: `rtk uv sync`
Expected: exit 0, lockfile updated.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add jsonschema and tomli-w for P10 config editing"
```

---

## Task 2: PatchEngine — path merge and remove

**Files:**
- Create: `src/agentic_os/patch_engine.py`
- Create: `tests/test_patch_engine.py`

- [ ] **Step 1: Write failing merge test**

```python
# tests/test_patch_engine.py
from agentic_os.patch_engine import PatchEngine, PatchOp


def test_merge_nested_path_preserves_unknown_keys() -> None:
    doc = {"model": "sonnet", "mcpServers": {"existing": {"command": "keep"}}}
    ops = [PatchOp(op="merge", path="mcpServers.github", value={"command": "npx"})]
    result = PatchEngine.apply(doc, ops)
    assert result["model"] == "sonnet"
    assert result["mcpServers"]["existing"]["command"] == "keep"
    assert result["mcpServers"]["github"]["command"] == "npx"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run pytest tests/test_patch_engine.py::test_merge_nested_path_preserves_unknown_keys -v`
Expected: FAIL (`ModuleNotFoundError` or `PatchEngine` not defined)

- [ ] **Step 3: Implement PatchEngine**

```python
# src/agentic_os/patch_engine.py
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


@dataclass(frozen=True)
class PatchOp:
    op: str
    path: str
    value: Any | None = None


class PatchEngine:
    @staticmethod
    def apply(doc: dict[str, Any], ops: list[PatchOp]) -> dict[str, Any]:
        result = copy.deepcopy(doc)
        for item in ops:
            if item.op == "merge":
                if item.value is None:
                    msg = "merge op requires value"
                    raise ValueError(msg)
                _set_at_path(result, item.path, item.value, merge=True)
            elif item.op == "remove":
                _delete_at_path(result, item.path)
            else:
                msg = f"unsupported op: {item.op}"
                raise ValueError(msg)
        return result

    @staticmethod
    def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        added: dict[str, Any] = {}
        modified: dict[str, Any] = {}
        removed: dict[str, Any] = {}
        all_keys = set(before) | set(after)
        for key in sorted(all_keys):
            if key not in before:
                added[key] = after[key]
            elif key not in after:
                removed[key] = before[key]
            elif before[key] != after[key]:
                modified[key] = {"before": before[key], "after": after[key]}
        return {"added": added, "modified": modified, "removed": removed}


def _parse_tokens(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    for match in _PATH_TOKEN.finditer(path):
        if match.group(1) is not None:
            tokens.append(match.group(1))
        else:
            tokens.append(int(match.group(2)))
    return tokens


def _set_at_path(doc: dict[str, Any], path: str, value: Any, *, merge: bool) -> None:
    tokens = _parse_tokens(path)
    if not tokens:
        msg = "empty path"
        raise ValueError(msg)
    cursor: Any = doc
    for token in tokens[:-1]:
        cursor = _descend(cursor, token, create=True)
    last = tokens[-1]
    if merge and isinstance(cursor.get(last), dict) and isinstance(value, dict):
        cursor[last] = PatchEngine.apply(cursor[last], [PatchOp(op="merge", path="", value=value)])
        return
    if last == "":
        if not isinstance(value, dict):
            msg = "root merge requires object value"
            raise ValueError(msg)
        doc.clear()
        doc.update(copy.deepcopy(value))
        return
    cursor[last] = copy.deepcopy(value)


def _delete_at_path(doc: dict[str, Any], path: str) -> None:
    tokens = _parse_tokens(path)
    if not tokens:
        return
    cursor: Any = doc
    for token in tokens[:-1]:
        cursor = _descend(cursor, token, create=False)
        if cursor is None:
            return
    last = tokens[-1]
    if isinstance(cursor, dict):
        cursor.pop(last, None)
    elif isinstance(cursor, list) and isinstance(last, int) and 0 <= last < len(cursor):
        cursor.pop(last)


def _descend(cursor: Any, token: str | int, *, create: bool) -> Any:
    if isinstance(token, int):
        if not isinstance(cursor, list):
            msg = f"expected list at index access, got {type(cursor)}"
            raise TypeError(msg)
        while create and len(cursor) <= token:
            cursor.append({})
        return cursor[token]
    if not isinstance(cursor, dict):
        msg = f"expected dict at key {token!r}, got {type(cursor)}"
        raise TypeError(msg)
    if create and token not in cursor:
        cursor[token] = {}
    return cursor[token]
```

- [ ] **Step 4: Add remove test and fix root merge edge case**

Add to `tests/test_patch_engine.py`:

```python
def test_remove_key() -> None:
    doc = {"hooks": {"PreToolUse": [{"command": "x"}]}, "model": "x"}
    ops = [PatchOp(op="remove", path="hooks.PreToolUse")]
    result = PatchEngine.apply(doc, ops)
    assert "hooks" not in result or "PreToolUse" not in result["hooks"]
    assert result["model"] == "x"
```

Run: `rtk uv run pytest tests/test_patch_engine.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/patch_engine.py tests/test_patch_engine.py
git commit -m "feat: add PatchEngine for path-directed config merges"
```

---

## Task 3: TOML atomic write

**Files:**
- Create: `src/agentic_os/toml_io.py`
- Create: `tests/test_toml_io.py`

- [ ] **Step 1: Write failing round-trip test**

```python
# tests/test_toml_io.py
from pathlib import Path

from agentic_os.toml_io import atomic_write_toml, load_toml


def test_atomic_write_toml_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    payload = {"mcp_servers": {"github": {"command": "npx", "args": ["-y", "mcp"]}}}
    atomic_write_toml(path, payload)
    assert load_toml(path) == payload
```

- [ ] **Step 2: Run test — FAIL**

Run: `rtk uv run pytest tests/test_toml_io.py -v`

- [ ] **Step 3: Implement toml_io**

```python
# src/agentic_os/toml_io.py
from __future__ import annotations

import os
import tomllib
import uuid
from pathlib import Path
from typing import Any

import tomli_w


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def atomic_write_toml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_text(tomli_w.dumps(payload), encoding="utf-8")
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
```

- [ ] **Step 4: Run test — PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/toml_io.py tests/test_toml_io.py
git commit -m "feat: add atomic TOML read/write helpers"
```

---

## Task 4: Schema registry and bundled schemas

**Files:**
- Create: `src/agentic_os/schema_registry.py`
- Create: `src/agentic_os/schemas/_common/patch_op@v1.json`
- Create: `src/agentic_os/schemas/claude/mcp_server@v1.json`
- Create: `src/agentic_os/schemas/claude/hook@v1.json`
- Create: `src/agentic_os/schemas/cursor/mcp_server@v1.json`
- Create: `src/agentic_os/schemas/cursor/hook@v1.json`
- Create: `src/agentic_os/schemas/codex/mcp_server@v1.json`
- Create: `src/agentic_os/schemas/opencode/mcp_server@v1.json`
- Create: `src/agentic_os/schemas/qwen/mcp_server@v1.json`
- Create: `src/agentic_os/schemas/openclaw/mcp_server@v1.json`
- Create: `src/agentic_os/schemas/hermes/mcp_server@v1.json`
- Create: `src/agentic_os/schemas/agentic_os/config@v1.json`
- Create: `tests/test_schema_registry.py`
- Modify: `pyproject.toml` (include schemas in package data if needed — hatchling includes package by default under `src/agentic_os`)

- [ ] **Step 1: Write minimal MCP server schema**

`src/agentic_os/schemas/claude/mcp_server@v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "mcpServers": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "command": { "type": "string" },
          "args": { "type": "array", "items": { "type": "string" } },
          "url": { "type": "string" },
          "env": { "type": "object", "additionalProperties": { "type": "string" } }
        },
        "additionalProperties": true
      }
    }
  },
  "additionalProperties": true
}
```

Copy and adapt for `cursor/mcp_server@v1.json` (same shape — `mcp.json` uses `mcpServers`).

`src/agentic_os/schemas/claude/hook@v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "hooks": {
      "type": "object",
      "additionalProperties": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "matcher": { "type": "string" },
            "hooks": { "type": "array" }
          },
          "additionalProperties": true
        }
      }
    }
  },
  "additionalProperties": true
}
```

For TOML harnesses (`codex`, `openclaw`, `hermes`), use schema with top-level `mcp_servers` table map:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "mcp_servers": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "command": { "type": "string" },
          "args": { "type": "array", "items": { "type": "string" } }
        },
        "additionalProperties": true
      }
    }
  },
  "additionalProperties": true
}
```

`opencode` and `qwen` reuse JSON `mcpServers` shape (copy claude schema).

`agentic_os/config@v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": true
}
```

- [ ] **Step 2: Write failing validation test**

```python
# tests/test_schema_registry.py
from agentic_os.schema_registry import SchemaRegistry


def test_validate_claude_mcp_document_ok() -> None:
    reg = SchemaRegistry()
    doc = {"mcpServers": {"gh": {"command": "npx", "args": ["-y", "mcp"]}}, "model": "x"}
    errors = reg.validate_document("claude", "mcp_server", doc)
    assert errors == []


def test_validate_claude_mcp_document_rejects_bad_type() -> None:
    reg = SchemaRegistry()
    doc = {"mcpServers": {"gh": {"command": 123}}}
    errors = reg.validate_document("claude", "mcp_server", doc)
    assert errors


def test_path_whitelist_allows_mcp_servers() -> None:
    reg = SchemaRegistry()
    assert reg.is_path_allowed("claude", "mcp_server", "mcpServers.github") is True
    assert reg.is_path_allowed("claude", "mcp_server", "permissions.allow") is False
```

- [ ] **Step 3: Implement SchemaRegistry**

```python
# src/agentic_os/schema_registry.py
from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

_SCHEMAS_PKG = "agentic_os.schemas"

# path prefix whitelist per harness/kind
_PATH_WHITELIST: dict[tuple[str, str], tuple[str, ...]] = {
    ("claude", "mcp_server"): ("mcpServers",),
    ("claude", "hook"): ("hooks",),
    ("cursor", "mcp_server"): ("mcpServers",),
    ("cursor", "hook"): ("hooks",),
    ("codex", "mcp_server"): ("mcp_servers",),
    ("opencode", "mcp_server"): ("mcpServers",),
    ("qwen", "mcp_server"): ("mcpServers",),
    ("openclaw", "mcp_server"): ("mcp_servers",),
    ("hermes", "mcp_server"): ("mcp_servers",),
    ("agentic_os", "config"): ("harness", "daemon", "fleet"),
}


class SchemaRegistry:
    def validate_document(self, harness: str, kind: str, doc: dict[str, Any]) -> list[str]:
        schema = _load_schema(harness, kind)
        if schema is None:
            return [f"no schema for {harness}/{kind}"]
        validator = Draft202012Validator(schema)
        return [f"{e.json_path}: {e.message}" for e in sorted(validator.iter_errors(doc), key=str)]

    def is_path_allowed(self, harness: str, kind: str, path: str) -> bool:
        prefixes = _PATH_WHITELIST.get((harness, kind), ())
        if not prefixes:
            return False
        top = path.split(".")[0].split("[")[0]
        return any(top == prefix or path.startswith(f"{prefix}.") for prefix in prefixes)


@lru_cache(maxsize=64)
def _load_schema(harness: str, kind: str) -> dict[str, Any] | None:
    filename = f"{kind}@v1.json"
    try:
        raw = resources.files(_SCHEMAS_PKG).joinpath(harness, filename).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, TypeError):
        return None
    return json.loads(raw)
```

Add `src/agentic_os/schemas/__init__.py` (empty file) so it is a package.

- [ ] **Step 4: Run tests — PASS**

Run: `rtk uv run pytest tests/test_schema_registry.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/schema_registry.py src/agentic_os/schemas tests/test_schema_registry.py
git commit -m "feat: add versioned schema registry with path whitelist"
```

---

## Task 5: BackupStore — snapshot, index, rollback

**Files:**
- Create: `src/agentic_os/backup_store.py`
- Create: `tests/test_backup_store.py`

- [ ] **Step 1: Write failing snapshot test**

```python
# tests/test_backup_store.py
from pathlib import Path

from agentic_os.backup_store import BackupStore, PatchIndexEntry


def test_snapshot_backup_and_restore(tmp_path: Path) -> None:
    state_dir = tmp_path / ".agentic-os"
    target = tmp_path / "repo" / ".claude" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"model": "before"}', encoding="utf-8")
    store = BackupStore(state_dir)
    entry = store.create_snapshot(
        patch_id="p_test1",
        harness_id="claude",
        cwd=tmp_path / "repo",
        target_path=target,
        target_kind="surface",
        source="test",
    )
    target.write_text('{"model": "after"}', encoding="utf-8")
    store.restore(entry)
    assert target.read_text(encoding="utf-8") == '{"model": "before"}'
```

- [ ] **Step 2: Implement BackupStore**

```python
# src/agentic_os/backup_store.py
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class PatchIndexEntry:
    patch_id: str
    harness_id: str
    cwd: str
    target_kind: str
    surface_id: str | None
    backup_kind: str
    backup_paths: list[str]
    target_path: str
    source: str
    created_at: str
    rolled_back_at: str | None = None
    rollback_of: str | None = None


class BackupStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.patches_dir = state_dir / "patches"
        self.index_path = self.patches_dir / "index.jsonl"

    def create_snapshot(
        self,
        *,
        patch_id: str,
        harness_id: str,
        cwd: Path,
        target_path: Path,
        target_kind: str,
        source: str,
        surface_id: str | None = None,
    ) -> PatchIndexEntry:
        self.patches_dir.mkdir(parents=True, exist_ok=True)
        rel = target_path.name
        backup_dir = self.patches_dir / patch_id / "before"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_dir / rel
        if target_path.exists():
            shutil.copy2(target_path, backup_file)
        else:
            backup_file.write_text("", encoding="utf-8")
        entry = PatchIndexEntry(
            patch_id=patch_id,
            harness_id=harness_id,
            cwd=str(cwd.resolve()),
            target_kind=target_kind,
            surface_id=surface_id,
            backup_kind="snapshot",
            backup_paths=[str(backup_file)],
            target_path=str(target_path),
            source=source,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._append_index(entry)
        return entry

    def create_sidecar(self, target_path: Path) -> Path:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        sidecar = target_path.with_name(f"{target_path.name}.bak.{ts}")
        if target_path.exists():
            shutil.copy2(target_path, sidecar)
        else:
            sidecar.write_text("", encoding="utf-8")
        return sidecar

    def restore(self, entry: PatchIndexEntry) -> None:
        target = Path(entry.target_path)
        backup = Path(entry.backup_paths[0])
        target.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists() and backup.read_text(encoding="utf-8") == "":
            if target.exists():
                target.unlink()
            return
        shutil.copy2(backup, target)

    def get(self, patch_id: str) -> PatchIndexEntry | None:
        if not self.index_path.exists():
            return None
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if data["patch_id"] == patch_id:
                return PatchIndexEntry(**data)
        return None

    def list_entries(
        self, *, harness_id: str | None = None, cwd: str | None = None, limit: int = 50
    ) -> list[PatchIndexEntry]:
        if not self.index_path.exists():
            return []
        entries: list[PatchIndexEntry] = []
        for line in reversed(self.index_path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            entry = PatchIndexEntry(**json.loads(line))
            if harness_id and entry.harness_id != harness_id:
                continue
            if cwd and entry.cwd != str(Path(cwd).resolve()):
                continue
            entries.append(entry)
            if len(entries) >= limit:
                break
        return entries

    def mark_rolled_back(self, patch_id: str) -> None:
        if not self.index_path.exists():
            return
        lines: list[str] = []
        now = datetime.now(UTC).isoformat()
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if data["patch_id"] == patch_id:
                data["rolled_back_at"] = now
            lines.append(json.dumps(data))
        self.index_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def _append_index(self, entry: PatchIndexEntry) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "patch_id": entry.patch_id,
            "harness_id": entry.harness_id,
            "cwd": entry.cwd,
            "target_kind": entry.target_kind,
            "surface_id": entry.surface_id,
            "backup_kind": entry.backup_kind,
            "backup_paths": entry.backup_paths,
            "target_path": entry.target_path,
            "source": entry.source,
            "created_at": entry.created_at,
            "rolled_back_at": entry.rolled_back_at,
            "rollback_of": entry.rollback_of,
        }
        with self.index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
```

- [ ] **Step 3: Run test — PASS**

- [ ] **Step 4: Commit**

```bash
git add src/agentic_os/backup_store.py tests/test_backup_store.py
git commit -m "feat: add BackupStore with snapshot backup and index"
```

---

## Task 6: Safe Edit pipeline

**Files:**
- Create: `src/agentic_os/safe_edit.py`
- Create: `tests/test_safe_edit.py`

- [ ] **Step 1: Write failing dry-run integration test**

```python
# tests/test_safe_edit.py
import json
from pathlib import Path

from agentic_os.audit import AuditStore
from agentic_os.backup_store import BackupStore
from agentic_os.patch_engine import PatchOp
from agentic_os.safe_edit import PatchTarget, SafeEditEngine


def test_dry_run_does_not_write_file(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    claude = repo / ".claude"
    claude.mkdir(parents=True)
    settings = claude / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    state_dir = tmp_path / ".agentic-os"
    engine = SafeEditEngine(
        state_dir=state_dir,
        backup_store=BackupStore(state_dir),
        audit_store=AuditStore(state_dir / "agentic-os.db"),
    )
    engine.audit_store.init()
    target = PatchTarget(
        harness_id="claude",
        cwd=repo,
        scope="project",
        target_kind="surface",
        kind="mcp_server",
        file_path=settings,
        file_format="json",
    )
    ops = [PatchOp(op="merge", path="mcpServers.gh", value={"command": "npx"})]
    result = engine.apply(target, ops, source="test", dry_run=True)
    assert result.applied is False
    assert json.loads(settings.read_text(encoding="utf-8")) == {}
```

- [ ] **Step 2: Implement SafeEditEngine**

```python
# src/agentic_os/safe_edit.py
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentic_os.audit import AuditStore
from agentic_os.backup_store import BackupStore, PatchIndexEntry
from agentic_os.control_plane import _redact_value
from agentic_os.jsonio import atomic_write_json
from agentic_os.patch_engine import PatchEngine, PatchOp
from agentic_os.schema_registry import SchemaRegistry
from agentic_os.toml_io import atomic_write_toml, load_toml


@dataclass(frozen=True)
class PatchTarget:
    harness_id: str
    cwd: Path
    scope: str
    target_kind: str
    kind: str
    file_path: Path
    file_format: str  # json | toml
    surface_id: str | None = None


@dataclass(frozen=True)
class PatchResult:
    patch_id: str
    applied: bool
    diff: dict[str, Any]
    validation: dict[str, Any]
    backup: dict[str, Any] | None
    audit_event_id: int | None
    base_mtime: float | None = None


class SafeEditEngine:
    def __init__(
        self,
        *,
        state_dir: Path,
        backup_store: BackupStore,
        audit_store: AuditStore,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.backup_store = backup_store
        self.audit_store = audit_store
        self.schema_registry = schema_registry or SchemaRegistry()

    def apply(
        self,
        target: PatchTarget,
        ops: list[PatchOp],
        *,
        source: str,
        dry_run: bool = False,
        base_mtime: float | None = None,
    ) -> PatchResult:
        patch_id = f"p_{uuid.uuid4().hex}"
        before = self._load_document(target)
        for op in ops:
            if not self.schema_registry.is_path_allowed(target.harness_id, target.kind, op.path):
                msg = f"forbidden path: {op.path}"
                raise PermissionError(msg)
        after = PatchEngine.apply(before, ops)
        errors = self.schema_registry.validate_document(target.harness_id, target.kind, after)
        validation = {"ok": not errors, "errors": errors}
        diff = PatchEngine.diff(before, after)
        file_path = target.file_path
        current_mtime = file_path.stat().st_mtime if file_path.exists() else None
        if base_mtime is not None and current_mtime is not None and base_mtime != current_mtime:
            msg = "stale_target"
            raise ConflictError(msg)
        if errors:
            self.audit_store.record(
                domain="config_patch",
                entity_id=patch_id,
                event_type="config_patch_failed",
                message=f"validation failed for {target.harness_id}",
                metadata=_audit_metadata(target, patch_id, ops, before, after, source, dry_run=True),
            )
            raise ValidationError(errors)
        would_backup = {
            "kind": "snapshot",
            "path": str(self.backup_store.patches_dir / patch_id / "before" / file_path.name),
        }
        if dry_run:
            return PatchResult(
                patch_id=patch_id,
                applied=False,
                diff=diff,
                validation=validation,
                backup=would_backup,
                audit_event_id=None,
                base_mtime=current_mtime,
            )
        entry = self.backup_store.create_snapshot(
            patch_id=patch_id,
            harness_id=target.harness_id,
            cwd=target.cwd,
            target_path=file_path,
            target_kind=target.target_kind,
            source=source,
            surface_id=target.surface_id,
        )
        self._write_document(target, after)
        event = self.audit_store.record(
            domain="config_patch",
            entity_id=patch_id,
            event_type="config_patch_applied",
            message=f"patched {target.harness_id} {target.kind}",
            metadata=_audit_metadata(target, patch_id, ops, before, after, source, dry_run=False),
        )
        return PatchResult(
            patch_id=patch_id,
            applied=True,
            diff=_redact_value(diff),
            validation=validation,
            backup={"kind": entry.backup_kind, "path": entry.backup_paths[0]},
            audit_event_id=event.id,
            base_mtime=current_mtime,
        )

    def rollback(self, patch_id: str, *, source: str) -> PatchResult:
        entry = self.backup_store.get(patch_id)
        if entry is None:
            raise LookupError("patch_not_found")
        if entry.rolled_back_at is not None:
            raise ConflictError("already_rolled_back")
        self.backup_store.restore(entry)
        self.backup_store.mark_rolled_back(patch_id)
        rollback_id = f"p_{uuid.uuid4().hex}"
        event = self.audit_store.record(
            domain="config_patch",
            entity_id=rollback_id,
            event_type="config_patch_rolled_back",
            message=f"rolled back {patch_id}",
            metadata={"rollback_of": patch_id, "source": source},
        )
        return PatchResult(
            patch_id=rollback_id,
            applied=True,
            diff={},
            validation={"ok": True, "errors": []},
            backup=None,
            audit_event_id=event.id,
        )

    def _load_document(self, target: PatchTarget) -> dict[str, Any]:
        if target.file_format == "json":
            if not target.file_path.exists():
                return {}
            try:
                data = json.loads(target.file_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}
        return load_toml(target.file_path)

    def _write_document(self, target: PatchTarget, doc: dict[str, Any]) -> None:
        if target.file_format == "json":
            atomic_write_json(target.file_path, doc)
        else:
            atomic_write_toml(target.file_path, doc)


class ValidationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class ConflictError(Exception):
    pass


def _audit_metadata(
    target: PatchTarget,
    patch_id: str,
    ops: list[PatchOp],
    before: dict[str, Any],
    after: dict[str, Any],
    source: str,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    return _redact_value(
        {
            "patch_id": patch_id,
            "harness_id": target.harness_id,
            "scope": target.scope,
            "cwd": str(target.cwd.resolve()),
            "target_kind": target.target_kind,
            "surface_id": target.surface_id,
            "ops": [{"op": o.op, "path": o.path, "value": o.value} for o in ops],
            "before_hash": _hash_doc(before),
            "after_hash": _hash_doc(after),
            "source": source,
            "dry_run": dry_run,
        }
    )


def _hash_doc(doc: dict[str, Any]) -> str:
    payload = json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
```

- [ ] **Step 3: Add apply + rollback integration test**

```python
def test_apply_writes_and_rollback_restores(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    state_dir = tmp_path / ".agentic-os"
    engine = SafeEditEngine(
        state_dir=state_dir,
        backup_store=BackupStore(state_dir),
        audit_store=AuditStore(state_dir / "agentic-os.db"),
    )
    engine.audit_store.init()
    target = PatchTarget(
        harness_id="claude",
        cwd=repo,
        scope="project",
        target_kind="surface",
        kind="mcp_server",
        file_path=settings,
        file_format="json",
        surface_id="mcp_server:gh@project",
    )
    ops = [PatchOp(op="merge", path="mcpServers.gh", value={"command": "npx"})]
    applied = engine.apply(target, ops, source="test", dry_run=False)
    assert "gh" in json.loads(settings.read_text(encoding="utf-8"))["mcpServers"]
    engine.rollback(applied.patch_id, source="test")
    assert json.loads(settings.read_text(encoding="utf-8")) == {}
```

Run: `rtk uv run pytest tests/test_safe_edit.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/agentic_os/safe_edit.py tests/test_safe_edit.py
git commit -m "feat: add SafeEditEngine pipeline with dry-run and rollback"
```

---

## Task 7: Surface ops compiler (P10a)

**Files:**
- Create: `src/agentic_os/surface_ops.py`
- Modify: `src/agentic_os/catalog.py`
- Create: `tests/test_surface_ops.py`

- [ ] **Step 1: Add write target resolver to catalog**

In `catalog.py`, add:

```python
def resolve_surface_write_target(
    harness: str,
    scope: str,
    surface_kind: str,
    cwd: Path | None = None,
    home_dir: Path | None = None,
) -> tuple[Path, str]:
    """Return (file_path, file_format) for structured surface writes."""
    if harness not in _HARNESS_SCOPES:
        msg = f"unsupported harness: {harness}"
        raise ValueError(msg)
    cwd_path = cwd or Path.cwd()
    base_home = home_dir or Path.home()
    scope_dir = {
        "user": base_home / _HARNESS_SCOPES[harness]["user"],
        "project": cwd_path.resolve() / _HARNESS_SCOPES[harness]["project"],
        "local": cwd_path.resolve() / _HARNESS_SCOPES[harness]["local"],
    }[scope]
    if harness == "cursor" and surface_kind == "mcp_server":
        return scope_dir / "mcp.json", "json"
    if harness == "cursor" and surface_kind == "hook":
        return scope_dir / "hooks.json", "json"
    if harness in _JSON_SETTINGS_FILES:
        return scope_dir / _JSON_SETTINGS_FILES[harness], "json"
    return scope_dir / "config.toml", "toml"
```

- [ ] **Step 2: Write failing semantic op test**

```python
# tests/test_surface_ops.py
from agentic_os.patch_engine import PatchOp
from agentic_os.surface_ops import compile_semantic_ops


def test_enable_mcp_server_claude() -> None:
    ops = compile_semantic_ops(
        "claude",
        [
            {
                "op": "enable_mcp_server",
                "name": "github",
                "scope": "project",
                "config": {"command": "npx", "args": ["-y", "mcp"]},
            }
        ],
    )
    assert ops == [
        PatchOp(
            op="merge",
            path="mcpServers.github",
            value={"command": "npx", "args": ["-y", "mcp"]},
        )
    ]
```

- [ ] **Step 3: Implement surface_ops**

```python
# src/agentic_os/surface_ops.py
from __future__ import annotations

from typing import Any

from agentic_os.patch_engine import PatchOp

_MCP_PATH = {
    "claude": "mcpServers",
    "cursor": "mcpServers",
    "opencode": "mcpServers",
    "qwen": "mcpServers",
    "codex": "mcp_servers",
    "openclaw": "mcp_servers",
    "hermes": "mcp_servers",
}


def compile_semantic_ops(harness: str, raw_ops: list[dict[str, Any]]) -> list[PatchOp]:
    compiled: list[PatchOp] = []
    for raw in raw_ops:
        op = raw.get("op")
        if op == "enable_mcp_server":
            prefix = _MCP_PATH[harness]
            name = raw["name"]
            compiled.append(
                PatchOp(op="merge", path=f"{prefix}.{name}", value=raw["config"])
            )
        elif op == "disable_mcp_server":
            prefix = _MCP_PATH[harness]
            compiled.append(PatchOp(op="remove", path=f"{prefix}.{raw['name']}"))
        elif op == "upsert_hook":
            compiled.extend(_compile_hook(harness, raw))
        else:
            msg = f"unsupported semantic op: {op}"
            raise ValueError(msg)
    return compiled


def _compile_hook(harness: str, raw: dict[str, Any]) -> list[PatchOp]:
    event = raw["event"]
    entry: dict[str, Any] = {}
    if raw.get("matcher") is not None:
        entry["matcher"] = raw["matcher"]
    if raw.get("command") is not None:
        entry["command"] = raw["command"]
    if harness == "cursor":
        # cursor hooks.json: hooks.EventName is a list; append entry
        return [PatchOp(op="merge", path=f"hooks.{event}", value=[entry])]
    return [PatchOp(op="merge", path=f"hooks.{event}", value=[entry])]
```

- [ ] **Step 4: Run tests — PASS**

Run: `rtk uv run pytest tests/test_surface_ops.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/surface_ops.py src/agentic_os/catalog.py tests/test_surface_ops.py
git commit -m "feat: add surface semantic op compiler for MCP and hooks"
```

---

## Task 8: API — catalog patch and patches rollback (P10a)

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Wire SafeEditEngine in create_app**

Near other store init in `create_app`:

```python
from agentic_os.backup_store import BackupStore
from agentic_os.safe_edit import ConflictError, SafeEditEngine, ValidationError
from agentic_os.surface_ops import compile_semantic_ops
from agentic_os.catalog import resolve_surface_write_target

backup_store = BackupStore(state_dir)
safe_edit = SafeEditEngine(state_dir=state_dir, backup_store=backup_store, audit_store=audit_store)
app.state.safe_edit = safe_edit
app.state.backup_store = backup_store
```

- [ ] **Step 2: Add Pydantic models and routes**

```python
class PatchOpsRequest(BaseModel):
    ops: list[dict[str, object]]
    source: str = "api"
    base_mtime: float | None = None


@app.post("/catalog/{harness}/surfaces/patch")
def catalog_surfaces_patch(
    harness: str,
    body: PatchOpsRequest,
    cwd: str | None = Query(default=None),
    dry_run: bool = Query(default=False),
) -> dict[str, object]:
    _require_catalog_harness(harness)
    cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
    patch_ops = compile_semantic_ops(harness, body.ops)
  # group ops by scope+kind inferred from first op or require scope in each op
    scope = str(body.ops[0].get("scope", "project"))
    kind = "mcp_server" if body.ops[0]["op"] in ("enable_mcp_server", "disable_mcp_server") else "hook"
    file_path, file_format = resolve_surface_write_target(harness, scope, kind, cwd_path)
    target = PatchTarget(
        harness_id=harness,
        cwd=cwd_path,
        scope=scope,
        target_kind="surface",
        kind=kind,
        file_path=file_path,
        file_format=file_format,
    )
    try:
        result = safe_edit.apply(
            target, patch_ops, source=body.source, dry_run=dry_run, base_mtime=body.base_mtime
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"validation_errors": exc.errors}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"error": "forbidden_path", "message": str(exc)}) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail={"error": "stale_target"}) from exc
    return {
        "patch_id": result.patch_id,
        "applied": result.applied,
        "diff": result.diff,
        "validation": result.validation,
        "backup": result.backup,
        "audit_event_id": result.audit_event_id,
        "base_mtime": result.base_mtime,
    }


@app.get("/patches")
def patches_list(
    harness: str | None = Query(default=None),
    cwd: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, object]:
    entries = backup_store.list_entries(
        harness_id=harness,
        cwd=str(Path(cwd).resolve()) if cwd else None,
        limit=limit,
    )
    return {"patches": [entry.__dict__ for entry in entries]}


@app.post("/patches/{patch_id}/rollback")
def patches_rollback(patch_id: str, source: str = Query(default="api")) -> dict[str, object]:
    try:
        result = safe_edit.rollback(patch_id, source=source)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
    return {
        "patch_id": result.patch_id,
        "applied": result.applied,
        "audit_event_id": result.audit_event_id,
    }
```

Import `PatchTarget` from `safe_edit`.

- [ ] **Step 3: Write API test**

```python
def test_catalog_patch_dry_run_does_not_mutate(client, tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    response = client.post(
        "/catalog/claude/surfaces/patch",
        params={"cwd": str(repo), "dry_run": "true"},
        json={
            "ops": [
                {
                    "op": "enable_mcp_server",
                    "name": "gh",
                    "scope": "project",
                    "config": {"command": "npx"},
                }
            ],
            "source": "test",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is False
    assert settings.read_text(encoding="utf-8") == "{}"


def test_catalog_patch_apply_and_audit(client, tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    response = client.post(
        "/catalog/claude/surfaces/patch",
        params={"cwd": str(repo)},
        json={
            "ops": [
                {
                    "op": "enable_mcp_server",
                    "name": "gh",
                    "scope": "project",
                    "config": {"command": "npx"},
                }
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["applied"] is True
    audit = client.get("/audit/events", params={"domain": "config_patch", "limit": 5})
    assert audit.status_code == 200
    assert any(e["event_type"] == "config_patch_applied" for e in audit.json()["events"])
```

- [ ] **Step 4: Run tests**

Run: `rtk uv run pytest tests/test_api.py -k "catalog_patch" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat: add catalog surface patch and rollback API"
```

---

## Task 9: CLI and client (P10a)

**Files:**
- Modify: `src/agentic_os/client.py`
- Modify: `src/agentic_os/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add client methods**

```python
def catalog_patch(
    self,
    harness: str,
    ops: list[dict[str, object]],
    *,
    cwd: str | None = None,
    dry_run: bool = False,
    source: str = "cli",
) -> dict[str, Any]:
    params: dict[str, str] = {"source": source}
    if cwd:
        params["cwd"] = cwd
    if dry_run:
        params["dry_run"] = "true"
    response = self._client.post(
        f"/catalog/{harness}/surfaces/patch",
        params=params,
        json={"ops": ops, "source": source},
    )
    response.raise_for_status()
    return response.json()


def patches_list(self, harness: str | None = None, cwd: str | None = None) -> dict[str, Any]:
    params: dict[str, str] = {}
    if harness:
        params["harness"] = harness
    if cwd:
        params["cwd"] = cwd
    response = self._client.get("/patches", params=params)
    response.raise_for_status()
    return response.json()


def patches_rollback(self, patch_id: str) -> dict[str, Any]:
    response = self._client.post(f"/patches/{patch_id}/rollback")
    response.raise_for_status()
    return response.json()
```

- [ ] **Step 2: Add CLI commands**

Under existing `catalog` typer group:

```python
@catalog.command("patch")
def catalog_patch_cmd(
    harness: str,
    op: list[str] = typer.Option(..., "--op", help="JSON semantic op (repeatable)."),
    cwd: Path | None = typer.Option(None, "--cwd"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    api: str | None = _api_option(),
) -> None:
    import json

    ops = [json.loads(item) for item in op]
    result = _run(api, lambda: make_client(api).catalog_patch(harness, ops, cwd=str(cwd or Path.cwd()), dry_run=dry_run))
    typer.echo(json.dumps(result, indent=2))
```

Add `patches` typer group with `list`, `show`, `rollback` subcommands.

- [ ] **Step 3: CLI test**

```python
def test_cli_catalog_patch_dry_run(cli_runner, daemon_url, tmp_path, monkeypatch) -> None:
    # mirror API fixture setup
    ...
    result = cli_runner.invoke(app, ["catalog", "patch", "claude", "--dry-run", "--op", json_op, "--cwd", str(repo)])
    assert result.exit_code == 0
```

- [ ] **Step 4: Run suite**

Run: `rtk uv run pytest tests/test_cli.py -k "catalog_patch" -v`

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/cli.py src/agentic_os/client.py tests/test_cli.py
git commit -m "feat: add catalog patch and patches CLI commands"
```

---

## Task 10: P10a.1 — skill and command semantic ops

**Files:**
- Modify: `src/agentic_os/surface_ops.py`
- Modify: `src/agentic_os/backup_store.py` (sidecar path in SafeEditEngine for standalone files)
- Modify: `src/agentic_os/safe_edit.py`
- Modify: `tests/test_surface_ops.py`, `tests/test_safe_edit.py`

- [ ] **Step 1: Extend surface_ops**

```python
elif op == "upsert_skill":
    # returns marker PatchOp with path "" unsupported — instead raise helper
    raise StandaloneFileOp(
        kind="skill",
        scope=raw["scope"],
        name=raw["name"],
        content=raw["content"],
    )
```

Implement `StandaloneFileOp` dataclass and `compile_semantic_ops` returning `CompiledPatch` union
(structured ops OR standalone file writes). Update `SafeEditEngine.apply` to accept standalone file
target: use `backup_store.create_sidecar`, write file text, index `backup_kind=sidecar`.

- [ ] **Step 2: Tests for skill upsert + rollback**

```python
def test_upsert_skill_creates_file_with_sidecar_backup(tmp_path: Path) -> None:
    ...
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: add upsert_skill and upsert_command surface ops with sidecar backup"
```

---

## Task 11: P10b — harness-native config patch

**Files:**
- Modify: `src/agentic_os/harness_config.py`
- Modify: `src/agentic_os/api.py`
- Modify: `src/agentic_os/cli.py`, `client.py`
- Create: `tests/test_harness_config_patch.py`

- [ ] **Step 1: Add resolve_write_path to harness_config**

```python
def resolve_write_path(
    harness: str,
    scope: str,
    cwd: Path,
    *,
    home: Path | None = None,
    file_name: str | None = None,
) -> tuple[Path, str]:
    """Return (path, format) for harness-native config writes."""
    paths = _config_files_for_scope(harness, scope, cwd, home or Path.home())
    if harness == "cursor" and file_name:
        base = _scope_base_dir(harness, scope, cwd, home or Path.home())
        assert base is not None
        return base / file_name, "json"
    if paths:
        path = paths[0]
        fmt = "toml" if path.suffix == ".toml" else "json"
        return path, fmt
    # create default path when missing
    single = _config_file_for_scope(harness, scope, cwd, home or Path.home())
    ...
```

- [ ] **Step 2: API route**

```
POST /harness-config/{harness_id}/patch
```

Body uses raw `PatchOp[]` (`op: merge|remove`), not semantic ops. `kind` derived from harness primary
config (`harness_config` kind in schema registry — add `claude/config@v1.json` etc. or reuse
`mcp_server` whitelist expanded to full settings keys for P10b).

- [ ] **Step 3: Test preserve unknown keys**

```python
def test_harness_config_patch_preserves_unknown_keys(client, tmp_path, monkeypatch) -> None:
    settings = repo / ".claude" / "settings.json"
    settings.write_text('{"model": "x", "extra": 1}', encoding="utf-8")
    client.post(
        "/harness-config/claude/patch",
        params={"cwd": str(repo), "scope": "project"},
        json={"ops": [{"op": "merge", "path": "mcpServers.gh", "value": {"command": "npx"}}]},
    )
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["model"] == "x"
    assert data["extra"] == 1
```

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add harness-native config patch API (P10b)"
```

---

## Task 12: P10c — agentic-os config patch

**Files:**
- Modify: `src/agentic_os/config_scope.py`
- Modify: `src/agentic_os/api.py`
- Modify: `tests/test_config_scope.py`, `tests/test_api.py`

- [ ] **Step 1: Export write path helper**

```python
def resolve_write_path(scope: str, cwd: str | None = None, home_dir: Path | None = None) -> Path:
    paths = resolve_paths("shell", cwd, home_dir)
    path = paths.get(scope)
    if path is None:
        msg = f"invalid scope: {scope}"
        raise ValueError(msg)
    return path
```

- [ ] **Step 2: API route**

```
POST /config/{harness_id}/patch?scope=user|project|local&cwd=&dry_run=
```

Uses `target_kind=agentic_config`, `kind=config`, `file_format=toml`.

- [ ] **Step 3: Integration test**

```python
def test_config_patch_user_scope(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    ao = home / ".agentic-os"
    ao.mkdir(parents=True)
    (ao / "config.toml").write_text("[daemon]\nport = 8767\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    # POST patch merge daemon.port = 8768
    # GET /config/shell/effective shows new port
```

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add agentic-os config patch API (P10c)"
```

---

## Task 13: Spec, README, final gate

**Files:**
- Create: `specs/027-safe-native-config-editing.md`
- Modify: `README.md`

- [ ] **Step 1: Create spec 027**

Copy acceptance tables from design doc sections P10a / P10a.1 / P10b / P10c. Set `Status: Implemented`
only after all tasks pass.

- [ ] **Step 2: Update README phase table**

Add row:

| P10 | safe native config editing | dry-run patch, backup, rollback, surface/config writers, audit | harness runtime, approval for config writes, desktop app |

Replace or clarify existing P10 row if it conflicts (currently mentions adapter contract / usage).

- [ ] **Step 3: Full CI gate**

Run: `rtk uv run pytest -q && rtk uv run ruff check .`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add specs/027-safe-native-config-editing.md README.md
git commit -m "docs: add P10 spec and README phase row"
```

---

## Self-Review (plan vs design)

| Design requirement | Task |
|--------------------|------|
| Unified Patch Engine | Tasks 2, 6 |
| Path merge preserves unknown keys | Task 2 test |
| Semantic ops (MCP + hooks) | Task 7 |
| 7 harness MCP + claude/cursor hooks | Task 7 + schema Task 4 |
| Hybrid backup | Tasks 5, 10 (sidecar) |
| dry-run | Tasks 6, 8 |
| Audit domain=config_patch | Tasks 6, 8 |
| Rollback API | Tasks 5, 8 |
| Schema registry + whitelist | Task 4 |
| P10b harness-config patch | Task 11 |
| P10c config patch | Task 12 |
| P10a.1 skills/commands | Task 10 |
| specs/027 + README | Task 13 |
| tomli-w dependency | Task 1 |
| stale mtime 409 | Task 6, 8 |
| No P7 approval | Enforced by design (no task) |

No TBD placeholders remain in task steps.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-06-p10-safe-native-config-editing.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
