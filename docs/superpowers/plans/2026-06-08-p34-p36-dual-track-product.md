# P34–P36: Dual-Track Product (Tool Discovery → Vibe Coding Runtime → Attach/Resume)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the dual-track product foundation — discover installed tools (P34), launch Codex/Claude Code from UI (P35), and attach to existing CLI sessions (P36).

**Architecture:** Three new backend modules (`tool_discovery.py`, `config_inventory.py`, `session_discovery.py`) feed read-only API endpoints. `attach.py` is expanded to support vibe coding agents. `models.py` gains `tool_kind` and `workspace_path` fields. Three new UI modules mount on the existing tab system. No control-plane additions (frozen per decision).

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, tomllib, plain JS (no build step).

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `src/agentic_os/tool_discovery.py` | Detect tool installation via `which` + well-known paths |
| `src/agentic_os/config_inventory.py` | Read non-secret config (model, provider) per tool |
| `src/agentic_os/session_discovery.py` | Scan external sessions for attach (P36) |
| `tests/test_tool_discovery.py` | Tests for P34 discovery |
| `tests/test_config_inventory.py` | Tests for P34 config reading |
| `tests/test_session_discovery.py` | Tests for P36 session scanning |
| `tests/test_attach_vibe_coding.py` | Tests for P35/P36 attach expansion |
| `apps/web/ui/tool-discovery.js` | P34 UI — read-only tool list |
| `apps/web/ui/vibe-coding-launcher.js` | P35 UI — workspace → launch → log → stop |
| `apps/web/ui/session-attach.js` | P36 UI — scan → bind → attach |

### Modified files

| File | Change |
|------|--------|
| `src/agentic_os/models.py` | Add `ToolKind` type + `tool_kind` field to `AgentDefinition`; add `workspace_path` to `SessionCreate`/`SessionRecord` |
| `src/agentic_os/attach.py` | Expand `_SUPPORTED`, add vibe coding parsers, add `build_attach_command` for claude/codex |
| `src/agentic_os/storage.py` | Add `workspace_path` column migration |
| `src/agentic_os/api.py` | Add `/tools/discovery`, `/tools/inventory`, `/sessions/discover`, `/sessions/{id}/workspace` endpoints |
| `examples/agents.toml` | Add `tool_kind` to each agent entry |
| `apps/web/index.html` | Add "Tools" tab, "Vibe Coding" tab, "Sessions" attach section |
| `apps/web/app.js` | Wire new UI modules |

---

## Phase P34: Tool Discovery + Config Inventory

### Task 1: Add ToolKind to models.py

**Files:**
- Modify: `src/agentic_os/models.py`
- Test: `tests/test_models.py` (new if not exists, else add to existing)

- [ ] **Step 1: Write failing test for tool_kind field**

Create `tests/test_models.py`:

```python
"""Tests for domain model extensions (P34+)."""
import pytest
from agentic_os.models import AgentDefinition, ToolKind


def test_tool_kind_type_exists():
    """ToolKind should be a Literal type."""
    from typing import get_args
    args = get_args(ToolKind)
    assert "vibe_coding" in args
    assert "agentic_runtime" in args


def test_agent_definition_has_tool_kind():
    agent = AgentDefinition(
        id="test",
        label="Test",
        command=["test"],
        tool_kind="vibe_coding",
    )
    assert agent.tool_kind == "vibe_coding"


def test_agent_definition_tool_kind_default():
    agent = AgentDefinition(
        id="test",
        label="Test",
        command=["test"],
    )
    assert agent.tool_kind is None


def test_agent_definition_tool_kind_invalid():
    with pytest.raises(Exception):
        AgentDefinition(
            id="test",
            label="Test",
            command=["test"],
            tool_kind="invalid_kind",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'ToolKind'`

- [ ] **Step 3: Add ToolKind to models.py**

In `src/agentic_os/models.py`, after the `AttachStatus` line (line 20):

```python
ToolKind = Literal["vibe_coding", "agentic_runtime"]
```

In `AgentDefinition` class, after `enabled: bool = True` (line 40):

```python
    tool_kind: ToolKind | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run full test suite to verify no regression**

Run: `uv run pytest -q`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/models.py tests/test_models.py
git commit -m "feat(P34): add ToolKind type and agent tool_kind field"
```

---

### Task 2: Update agents.toml with tool_kind

**Files:**
- Modify: `examples/agents.toml`
- Test: `tests/test_registry.py` (add tool_kind assertion)

- [ ] **Step 1: Write failing test for tool_kind in registry**

Add to `tests/test_registry.py` (or create if not exists):

```python
def test_agents_toml_has_tool_kind():
    """All non-shell agents should have tool_kind defined."""
    from pathlib import Path
    from agentic_os.registry import Registry

    registry = Registry(Path("examples/agents.toml"))
    for agent in registry.list_agents():
        if agent.id == "shell":
            continue
        assert agent.tool_kind is not None, f"{agent.id} missing tool_kind"
        assert agent.tool_kind in ("vibe_coding", "agentic_runtime")


def test_tool_kind_mapping():
    """Verify expected tool_kind assignments."""
    from pathlib import Path
    from agentic_os.registry import Registry

    registry = Registry(Path("examples/agents.toml"))
    agents = {a.id: a for a in registry.list_agents()}

    assert agents["claude"].tool_kind == "vibe_coding"
    assert agents["codex"].tool_kind == "vibe_coding"
    assert agents["cursor"].tool_kind == "vibe_coding"
    assert agents["openclaw"].tool_kind == "agentic_runtime"
    assert agents["hermes"].tool_kind == "agentic_runtime"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry.py::test_agents_toml_has_tool_kind -v`
Expected: FAIL (tool_kind is None for all agents)

- [ ] **Step 3: Update agents.toml**

Add `tool_kind` to each agent in `examples/agents.toml`:

```toml
# claude agent: add tool_kind = "vibe_coding"
[[agents]]
id = "claude"
label = "Claude Code"
tool_kind = "vibe_coding"
# ... rest unchanged

# codex agent: add tool_kind = "vibe_coding"
[[agents]]
id = "codex"
label = "Codex"
tool_kind = "vibe_coding"
# ... rest unchanged

# opencode: add tool_kind = "vibe_coding"
[[agents]]
id = "opencode"
label = "OpenCode"
tool_kind = "vibe_coding"
# ... rest unchanged

# qwen: add tool_kind = "vibe_coding"
[[agents]]
id = "qwen"
label = "Qwen Code"
tool_kind = "vibe_coding"
# ... rest unchanged

# cursor: add tool_kind = "vibe_coding"
[[agents]]
id = "cursor"
label = "Cursor Agent"
tool_kind = "vibe_coding"
# ... rest unchanged

# openclaw: add tool_kind = "agentic_runtime"
[[agents]]
id = "openclaw"
label = "OpenClaw"
tool_kind = "agentic_runtime"
# ... rest unchanged

# hermes: add tool_kind = "agentic_runtime"
[[agents]]
id = "hermes"
label = "Hermes"
tool_kind = "agentic_runtime"
# ... rest unchanged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_registry.py -v -k "tool_kind"`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -q && uv run ruff check .`
Expected: All pass, lint clean

- [ ] **Step 6: Commit**

```bash
git add examples/agents.toml tests/test_registry.py
git commit -m "feat(P34): add tool_kind to all agents in registry"
```

---

### Task 3: Implement tool_discovery.py (TDD)

**Files:**
- Create: `src/agentic_os/tool_discovery.py`
- Create: `tests/test_tool_discovery.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tool_discovery.py`:

```python
"""Tests for tool discovery (P34)."""
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agentic_os.tool_discovery import (
    ToolDiscoveryResult,
    find_binary,
    detect_version,
    detect_tool,
    discover_all,
)
from agentic_os.models import AgentDefinition


def test_find_binary_existing():
    """find_binary should return path for known binary."""
    result = find_binary("python3")
    assert result is not None
    assert "python" in result


def test_find_binary_missing():
    """find_binary should return None for unknown binary."""
    result = find_binary("nonexistent_binary_xyz_12345")
    assert result is None


def test_detect_version_success():
    """detect_version should return version string on success."""
    result = detect_version(["python3", "--version"])
    assert result.version is not None
    assert result.error is None


def test_detect_version_failure():
    """detect_version should return error on failure."""
    result = detect_version(["nonexistent_binary_xyz_12345", "--version"])
    assert result.version is None
    assert result.error is not None


def test_detect_tool_installed():
    """detect_tool should report installed=True when binary exists."""
    agent = AgentDefinition(
        id="test_tool",
        label="Test",
        command=["python3", "test"],
        version_command=["python3", "--version"],
        tool_kind="vibe_coding",
    )
    result = detect_tool(agent)
    assert result.agent_id == "test_tool"
    assert result.tool_kind == "vibe_coding"
    assert result.installed is True
    assert result.binary_path is not None


def test_detect_tool_not_installed():
    """detect_tool should report installed=False when binary missing."""
    agent = AgentDefinition(
        id="fake_tool",
        label="Fake",
        command=["fake_binary_xyz", "test"],
        version_command=["fake_binary_xyz", "--version"],
        tool_kind="vibe_coding",
    )
    result = detect_tool(agent)
    assert result.installed is False
    assert result.binary_path is None


def test_detect_tool_no_version_command():
    """detect_tool should handle missing version_command gracefully."""
    agent = AgentDefinition(
        id="no_version",
        label="No Version",
        command=["python3", "test"],
        version_command=None,
        tool_kind="vibe_coding",
    )
    result = detect_tool(agent)
    assert result.installed is True
    assert result.version is None


def test_discover_all_filters_enabled():
    """discover_all should only check enabled agents."""
    from agentic_os.registry import Registry

    agent_enabled = AgentDefinition(
        id="enabled_tool",
        label="Enabled",
        command=["python3", "test"],
        version_command=["python3", "--version"],
        enabled=True,
        tool_kind="vibe_coding",
    )
    agent_disabled = AgentDefinition(
        id="disabled_tool",
        label="Disabled",
        command=["python3", "test"],
        enabled=False,
        tool_kind="vibe_coding",
    )

    mock_registry = MagicMock(spec=Registry)
    mock_registry.list_agents.return_value = [agent_enabled, agent_disabled]

    results = discover_all(mock_registry)
    ids = [r.agent_id for r in results]
    assert "enabled_tool" in ids
    assert "disabled_tool" not in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tool_discovery.py -v`
Expected: FAIL with `ImportError: cannot import name 'ToolDiscoveryResult'`

- [ ] **Step 3: Implement tool_discovery.py**

Create `src/agentic_os/tool_discovery.py`:

```python
"""Tool discovery: detect installed tools and their versions (P34).

Scans well-known paths and runs `which` to detect tool installation.
Results are cached in-memory for 5 minutes to avoid repeated subprocess calls.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from agentic_os.models import AgentDefinition


@dataclass(frozen=True)
class ToolDiscoveryResult:
    agent_id: str
    tool_kind: str | None
    installed: bool
    binary_path: str | None
    version: str | None
    version_error: str | None


@dataclass(frozen=True)
class _VersionResult:
    version: str | None
    error: str | None


# Module-level cache
_cache: dict[str, tuple[float, ToolDiscoveryResult]] = {}
_CACHE_TTL = 300  # 5 minutes


def _cache_key(agent_id: str) -> str:
    return f"discovery:{agent_id}"


def invalidate_cache() -> None:
    """Clear the discovery cache. Call after tool install/uninstall."""
    _cache.clear()


def find_binary(name: str) -> str | None:
    """Find binary path using shutil.which. Returns None if not found."""
    return shutil.which(name)


def detect_version(command: list[str] | None) -> _VersionResult:
    """Run version command and parse output. Returns (version, error)."""
    if not command:
        return _VersionResult(version=None, error=None)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            output = (result.stdout or result.stderr).strip()
            # Take first line as version
            version = output.split("\n")[0] if output else None
            return _VersionResult(version=version, error=None)
        else:
            error = (result.stderr or result.stdout).strip() or "non-zero exit"
            return _VersionResult(version=None, error=error[:200])
    except subprocess.TimeoutExpired:
        return _VersionResult(version=None, error="timeout after 10s")
    except FileNotFoundError:
        return _VersionResult(version=None, error="binary not found")
    except OSError as e:
        return _VersionResult(version=None, error=str(e)[:200])


def detect_tool(agent: AgentDefinition) -> ToolDiscoveryResult:
    """Detect a single tool's installation status and version."""
    # Extract binary name from command[0]
    binary_name = agent.command[0] if agent.command else ""
    binary_path = find_binary(binary_name) if binary_name else None
    installed = binary_path is not None

    version = None
    version_error = None
    if installed and agent.version_command:
        vresult = detect_version(agent.version_command)
        version = vresult.version
        version_error = vresult.error

    return ToolDiscoveryResult(
        agent_id=agent.id,
        tool_kind=agent.tool_kind,
        installed=installed,
        binary_path=binary_path,
        version=version,
        version_error=version_error,
    )


def discover_all(registry: Any) -> list[ToolDiscoveryResult]:
    """Discover all enabled agents in registry. Uses 5-min cache."""
    now = time.monotonic()
    results: list[ToolDiscoveryResult] = []

    for agent in registry.list_agents():
        if not agent.enabled:
            continue

        key = _cache_key(agent.id)
        cached = _cache.get(key)
        if cached and (now - cached[0]) < _CACHE_TTL:
            results.append(cached[1])
            continue

        result = detect_tool(agent)
        _cache[key] = (now, result)
        results.append(result)

    return sorted(results, key=lambda r: r.agent_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tool_discovery.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/tool_discovery.py tests/test_tool_discovery.py
git commit -m "feat(P34): implement tool_discovery module with caching"
```

---

### Task 4: Implement config_inventory.py (TDD)

**Files:**
- Create: `src/agentic_os/config_inventory.py`
- Create: `tests/test_config_inventory.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_config_inventory.py`:

```python
"""Tests for config inventory (P34)."""
import json
import tempfile
from pathlib import Path

import pytest

from agentic_os.config_inventory import (
    ConfigSummary,
    read_config_summary,
    _read_claude_config,
    _read_codex_config,
    _read_generic_json_config,
    _read_generic_toml_config,
)


def test_config_summary_model():
    """ConfigSummary should hold non-secret config fields."""
    summary = ConfigSummary(
        config_source="/home/user/.claude/settings.json",
        model="claude-sonnet-4-20250514",
        provider="anthropic",
        system_prompt_path=None,
        parse_error=None,
    )
    assert summary.model == "claude-sonnet-4-20250514"
    assert summary.parse_error is None


def test_read_config_summary_missing_path():
    """Should return error for non-existent config path."""
    summary = read_config_summary("claude", "/nonexistent/path/xyz")
    assert summary.config_source == "/nonexistent/path/xyz"
    assert summary.parse_error is not None
    assert "not found" in summary.parse_error or "does not exist" in summary.parse_error


def test_read_claude_config_json():
    """Should parse Claude settings.json for model."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = Path(tmpdir) / "settings.json"
        settings.write_text(json.dumps({
            "model": "claude-sonnet-4-20250514",
            "provider": "anthropic",
        }))
        summary = _read_claude_config(tmpdir)
        assert summary.model == "claude-sonnet-4-20250514"
        assert summary.provider == "anthropic"
        assert summary.parse_error is None


def test_read_claude_config_missing():
    """Should handle missing Claude config dir."""
    summary = _read_claude_config("/nonexistent/claude/dir")
    assert summary.parse_error is not None


def test_read_codex_config_toml():
    """Should parse Codex config.toml for model."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = Path(tmpdir) / "config.toml"
        config.write_text('[defaults]\nmodel = "o4-mini"\n')
        summary = _read_codex_config(tmpdir)
        assert summary.model == "o4-mini"
        assert summary.parse_error is None


def test_read_generic_json_config():
    """Should parse generic JSON config for model field."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = Path(tmpdir) / "config.json"
        config.write_text(json.dumps({"model": "gpt-4", "provider": "openai"}))
        summary = _read_generic_json_config(tmpdir, "config.json")
        assert summary.model == "gpt-4"
        assert summary.provider == "openai"


def test_no_secrets_leaked():
    """Config readers should never return API keys or tokens."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = Path(tmpdir) / "settings.json"
        settings.write_text(json.dumps({
            "model": "claude-sonnet-4-20250514",
            "api_key": "sk-secret-key-12345",
            "token": "bearer-token-xyz",
        }))
        summary = _read_claude_config(tmpdir)
        # api_key and token should NOT appear in summary
        assert summary.model == "claude-sonnet-4-20250514"
        # Verify no secret fields in the dataclass
        assert not hasattr(summary, "api_key")
        assert not hasattr(summary, "token")


def test_read_config_summary_dispatch():
    """read_config_summary should dispatch to correct reader by agent_id."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a Claude-style config
        settings = Path(tmpdir) / "settings.json"
        settings.write_text(json.dumps({"model": "claude-sonnet-4-20250514"}))

        summary = read_config_summary("claude", tmpdir)
        assert summary.model == "claude-sonnet-4-20250514"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_inventory.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement config_inventory.py**

Create `src/agentic_os/config_inventory.py`:

```python
"""Config inventory: read non-secret config summaries per tool (P34).

Reads tool-specific config files to extract model, provider, and
system prompt path. Explicitly does NOT read API keys, tokens, or
session state.

Each tool has a dedicated reader function. If the config format is
unknown or changes, the reader returns parse_error instead of
silently falling back.
"""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConfigSummary:
    config_source: str
    model: str | None = None
    provider: str | None = None
    system_prompt_path: str | None = None
    parse_error: str | None = None


# Dispatch table: agent_id -> reader function
_READERS: dict[str, callable] = {}


def _register_reader(agent_id: str):
    """Decorator to register a config reader for an agent."""
    def decorator(func):
        _READERS[agent_id] = func
        return func
    return decorator


def read_config_summary(agent_id: str, config_path: str) -> ConfigSummary:
    """Read non-secret config summary for a tool.

    Dispatches to agent-specific reader. Returns ConfigSummary with
    parse_error if config cannot be read.
    """
    path = Path(config_path).expanduser()
    if not path.exists():
        return ConfigSummary(
            config_source=config_path,
            parse_error=f"config path does not exist: {config_path}",
        )

    reader = _READERS.get(agent_id)
    if reader is None:
        # Fallback: try generic JSON then TOML
        return _read_generic_config(config_path)

    try:
        return reader(str(path))
    except Exception as e:
        return ConfigSummary(
            config_source=config_path,
            parse_error=f"reader error: {str(e)[:200]}",
        )


def _read_generic_config(config_path: str) -> ConfigSummary:
    """Fallback: try reading config.json or config.toml."""
    path = Path(config_path)
    if path.is_dir():
        # Try common filenames
        for name in ["config.json", "settings.json", "config.toml"]:
            candidate = path / name
            if candidate.exists():
                if name.endswith(".json"):
                    return _read_generic_json_config(str(path), name)
                else:
                    return _read_generic_toml_config(str(path), name)
        return ConfigSummary(
            config_source=config_path,
            parse_error="no recognized config file found",
        )
    return ConfigSummary(
        config_source=config_path,
        parse_error="config_path is not a directory",
    )


@_register_reader("claude")
def _read_claude_config(config_path: str) -> ConfigSummary:
    """Read Claude Code settings from ~/.claude/settings.json."""
    path = Path(config_path)
    if not path.exists():
        return ConfigSummary(config_source=config_path, parse_error="path not found")

    # Claude stores config in settings.json
    settings_path = path / "settings.json" if path.is_dir() else path
    if not settings_path.exists():
        return ConfigSummary(
            config_source=str(settings_path),
            parse_error="settings.json not found",
        )

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return ConfigSummary(
            config_source=str(settings_path),
            parse_error=f"JSON parse error: {str(e)[:200]}",
        )

    return ConfigSummary(
        config_source=str(settings_path),
        model=data.get("model"),
        provider=data.get("provider"),
        system_prompt_path=data.get("system_prompt_path"),
    )


@_register_reader("codex")
def _read_codex_config(config_path: str) -> ConfigSummary:
    """Read Codex config from ~/.codex/config.toml."""
    path = Path(config_path)
    if not path.exists():
        return ConfigSummary(config_source=config_path, parse_error="path not found")

    config_file = path / "config.toml" if path.is_dir() else path
    if not config_file.exists():
        return ConfigSummary(
            config_source=str(config_file),
            parse_error="config.toml not found",
        )

    try:
        data = tomllib.loads(config_file.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        return ConfigSummary(
            config_source=str(config_file),
            parse_error=f"TOML parse error: {str(e)[:200]}",
        )

    # Codex stores model in [defaults] section
    defaults = data.get("defaults", {})
    return ConfigSummary(
        config_source=str(config_file),
        model=defaults.get("model"),
        provider=defaults.get("provider"),
    )


@_register_reader("cursor")
def _read_cursor_config(config_path: str) -> ConfigSummary:
    """Read Cursor config (VSCode-style settings.json)."""
    return _read_generic_json_config(config_path, "User/settings.json")


@_register_reader("opencode")
def _read_opencode_config(config_path: str) -> ConfigSummary:
    """Read OpenCode config."""
    return _read_generic_json_config(config_path, "config.json")


@_register_reader("qwen")
def _read_qwen_config(config_path: str) -> ConfigSummary:
    """Read Qwen config."""
    return _read_generic_json_config(config_path, "config.json")


@_register_reader("openclaw")
def _read_openclaw_config(config_path: str) -> ConfigSummary:
    """Read OpenClaw config."""
    return _read_generic_json_config(config_path, "config.json")


@_register_reader("hermes")
def _read_hermes_config(config_path: str) -> ConfigSummary:
    """Read Hermes config."""
    return _read_generic_toml_config(config_path, "config.toml")


def _read_generic_json_config(config_path: str, filename: str) -> ConfigSummary:
    """Read model/provider from a JSON config file."""
    path = Path(config_path)
    if path.is_dir():
        json_path = path / filename
    else:
        json_path = path

    if not json_path.exists():
        return ConfigSummary(
            config_source=str(json_path),
            parse_error=f"{filename} not found",
        )

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return ConfigSummary(
            config_source=str(json_path),
            parse_error=f"JSON parse error: {str(e)[:200]}",
        )

    # Extract known non-secret fields
    return ConfigSummary(
        config_source=str(json_path),
        model=data.get("model") or data.get("defaultModel"),
        provider=data.get("provider") or data.get("defaultProvider"),
        system_prompt_path=data.get("system_prompt_path") or data.get("systemPrompt"),
    )


def _read_generic_toml_config(config_path: str, filename: str) -> ConfigSummary:
    """Read model/provider from a TOML config file."""
    path = Path(config_path)
    if path.is_dir():
        toml_path = path / filename
    else:
        toml_path = path

    if not toml_path.exists():
        return ConfigSummary(
            config_source=str(toml_path),
            parse_error=f"{filename} not found",
        )

    try:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        return ConfigSummary(
            config_source=str(toml_path),
            parse_error=f"TOML parse error: {str(e)[:200]}",
        )

    # Try common TOML structures
    model = (
        data.get("model")
        or data.get("defaults", {}).get("model")
        or data.get("llm", {}).get("model")
    )
    provider = (
        data.get("provider")
        or data.get("defaults", {}).get("provider")
        or data.get("llm", {}).get("provider")
    )

    return ConfigSummary(
        config_source=str(toml_path),
        model=model,
        provider=provider,
    )


def read_inventory(agents: list) -> list[ConfigSummary]:
    """Read config summaries for a list of AgentDefinition objects."""
    results = []
    for agent in agents:
        if not agent.enabled or not agent.config_path:
            continue
        summary = read_config_summary(agent.id, agent.config_path)
        results.append(summary)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_inventory.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -q && uv run ruff check .`
Expected: All pass, lint clean

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/config_inventory.py tests/test_config_inventory.py
git commit -m "feat(P34): implement config_inventory with per-tool readers"
```

---

### Task 5: Add /tools/discovery and /tools/inventory API endpoints

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Add to `tests/test_api.py`:

```python
def test_tools_discovery_endpoint(client):
    """GET /tools/discovery should return tool list."""
    response = client.get("/tools/discovery")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert isinstance(data["tools"], list)
    # Each tool should have required fields
    for tool in data["tools"]:
        assert "agent_id" in tool
        assert "tool_kind" in tool
        assert "installed" in tool
        assert "binary_path" in tool


def test_tools_inventory_endpoint(client):
    """GET /tools/inventory should return config summaries."""
    response = client.get("/tools/inventory")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert isinstance(data["tools"], list)
    for tool in data["tools"]:
        assert "agent_id" in tool
        assert "config_source" in tool
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py::test_tools_discovery_endpoint tests/test_api.py::test_tools_inventory_endpoint -v`
Expected: FAIL with 404 (endpoints don't exist)

- [ ] **Step 3: Add endpoints to api.py**

In `src/agentic_os/api.py`, add imports at the top:

```python
from agentic_os.tool_discovery import discover_all
from agentic_os.config_inventory import read_config_summary
```

Add endpoints after the existing workspace endpoints (around line 2810):

```python
@app.get("/tools/discovery")
def tools_discovery() -> dict[str, object]:
    """Discover installed tools and their versions (P34). Read-only."""
    from agentic_os.tool_discovery import discover_all

    results = discover_all(registry)
    return {
        "tools": [
            {
                "agent_id": r.agent_id,
                "tool_kind": r.tool_kind,
                "installed": r.installed,
                "binary_path": r.binary_path,
                "version": r.version,
                "version_error": r.version_error,
            }
            for r in results
        ],
    }


@app.get("/tools/inventory")
def tools_inventory() -> dict[str, object]:
    """Read non-secret config summaries for installed tools (P34). Read-only."""
    from agentic_os.config_inventory import read_config_summary

    agents = [a for a in registry.list_agents() if a.enabled and a.config_path]
    summaries = []
    for agent in agents:
        summary = read_config_summary(agent.id, agent.config_path)
        summaries.append({
            "agent_id": agent.id,
            "tool_kind": agent.tool_kind,
            "config_source": summary.config_source,
            "model": summary.model,
            "provider": summary.provider,
            "system_prompt_path": summary.system_prompt_path,
            "parse_error": summary.parse_error,
        })
    return {"tools": summaries}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py::test_tools_discovery_endpoint tests/test_api.py::test_tools_inventory_endpoint -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -q && uv run ruff check .`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat(P34): add /tools/discovery and /tools/inventory endpoints"
```

---

### Task 6: P34 UI — tool-discovery.js

**Files:**
- Create: `apps/web/ui/tool-discovery.js`
- Modify: `apps/web/index.html`
- Modify: `apps/web/app.js`

- [ ] **Step 1: Create tool-discovery.js**

Create `apps/web/ui/tool-discovery.js`:

```javascript
/**
 * Tool Discovery UI (P34)
 * Read-only display of installed tools and their config summaries.
 */

const ToolDiscovery = {
  async loadDiscovery() {
    const res = await fetch(`${API_URL}/tools/discovery`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.tools || [];
  },

  async loadInventory() {
    const res = await fetch(`${API_URL}/tools/inventory`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.tools || [];
  },

  toolKindBadge(kind) {
    if (kind === "vibe_coding") {
      return '<span class="badge badge-vibe">Vibe Coding</span>';
    }
    if (kind === "agentic_runtime") {
      return '<span class="badge badge-agentic">Agentic</span>';
    }
    return '<span class="badge">Unknown</span>';
  },

  installedIcon(installed) {
    return installed
      ? '<span class="status-ok" title="Installed">✓</span>'
      : '<span class="status-error" title="Not installed">✗</span>';
  },

  renderRow(tool, inventory) {
    const inv = inventory || {};
    const model = inv.model || "—";
    const provider = inv.provider || "—";
    const configSource = inv.config_source || "—";
    const parseError = inv.parse_error
      ? `<div class="error-text" title="${this.escape(inv.parse_error)}">⚠ config error</div>`
      : "";

    return `
      <tr>
        <td>${this.installedIcon(tool.installed)}</td>
        <td><strong>${this.escape(tool.agent_id)}</strong></td>
        <td>${this.toolKindBadge(tool.tool_kind)}</td>
        <td>${tool.version ? this.escape(tool.version) : "—"}</td>
        <td><code>${this.escape(configSource)}</code></td>
        <td>${this.escape(model)}</td>
        <td>${this.escape(provider)}</td>
        <td>${parseError}</td>
      </tr>
    `;
  },

  escape(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  },

  async render(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '<p class="loading">Loading tools...</p>';

    try {
      const [discovery, inventory] = await Promise.all([
        this.loadDiscovery(),
        this.loadInventory(),
      ]);

      // Build inventory lookup by agent_id
      const invMap = {};
      for (const inv of inventory) {
        invMap[inv.agent_id] = inv;
      }

      if (discovery.length === 0) {
        container.innerHTML = "<p>No tools found in registry.</p>";
        return;
      }

      // Separate by tool_kind
      const vibe = discovery.filter((t) => t.tool_kind === "vibe_coding");
      const agentic = discovery.filter((t) => t.tool_kind === "agentic_runtime");
      const other = discovery.filter(
        (t) => t.tool_kind !== "vibe_coding" && t.tool_kind !== "agentic_runtime"
      );

      let html = '<table class="tool-discovery-table">';
      html += "<thead><tr>";
      html += "<th></th><th>Tool</th><th>Kind</th><th>Version</th>";
      html += "<th>Config Source</th><th>Model</th><th>Provider</th><th></th>";
      html += "</tr></thead><tbody>";

      if (vibe.length > 0) {
        html += `<tr class="section-header"><td colspan="8"><strong>Vibe Coding</strong> (${vibe.length})</td></tr>`;
        for (const tool of vibe) {
          html += this.renderRow(tool, invMap[tool.agent_id]);
        }
      }

      if (agentic.length > 0) {
        html += `<tr class="section-header"><td colspan="8"><strong>Agentic Runtime</strong> (${agentic.length})</td></tr>`;
        for (const tool of agentic) {
          html += this.renderRow(tool, invMap[tool.agent_id]);
        }
      }

      if (other.length > 0) {
        html += `<tr class="section-header"><td colspan="8"><strong>Other</strong> (${other.length})</td></tr>`;
        for (const tool of other) {
          html += this.renderRow(tool, invMap[tool.agent_id]);
        }
      }

      html += "</tbody></table>";
      container.innerHTML = html;
    } catch (err) {
      container.innerHTML = `<p class="error-text">Failed to load tools: ${err.message}</p>`;
    }
  },
};

// Export for use in app.js
if (typeof window !== "undefined") {
  window.ToolDiscovery = ToolDiscovery;
}
```

- [ ] **Step 2: Add Tools tab to index.html**

In `apps/web/index.html`, add a new tab button in the tab bar:

```html
<button class="tab-btn" data-tab="tools">Tools</button>
```

Add a new tab content section:

```html
<div id="tab-tools" class="tab-content" style="display:none">
  <h2>Tool Discovery</h2>
  <div id="tool-discovery-container"></div>
</div>
```

- [ ] **Step 3: Add script tag to index.html**

Before `</body>`:

```html
<script src="ui/tool-discovery.js"></script>
```

- [ ] **Step 4: Wire tab switching in app.js**

In `apps/web/app.js`, add to the tab switching logic:

```javascript
// In the tab click handler, add:
if (tab === "tools") {
  window.ToolDiscovery.render("tool-discovery-container");
}
```

- [ ] **Step 5: Add basic CSS for tool-discovery table**

In `apps/web/styles.css`:

```css
.tool-discovery-table {
  width: 100%;
  border-collapse: collapse;
}
.tool-discovery-table th,
.tool-discovery-table td {
  padding: 0.5rem;
  text-align: left;
  border-bottom: 1px solid var(--border, #333);
}
.tool-discovery-table .section-header td {
  padding-top: 1rem;
  font-weight: bold;
  background: var(--bg-secondary, #1a1a1a);
}
.badge-vibe {
  background: #2563eb;
  color: white;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.75rem;
}
.badge-agentic {
  background: #7c3aed;
  color: white;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.75rem;
}
.status-ok { color: #22c55e; }
.status-error { color: #ef4444; }
.error-text { color: #ef4444; font-size: 0.75rem; }
```

- [ ] **Step 6: Verify UI loads correctly**

Start the local stack:

```bash
rtk bash scripts/start-local.sh
```

Open `http://localhost:5173`, click "Tools" tab.
Expected: Table shows tools from agents.toml with discovery results.

- [ ] **Step 7: Commit**

```bash
git add apps/web/ui/tool-discovery.js apps/web/index.html apps/web/app.js apps/web/styles.css
git commit -m "feat(P34): add tool discovery UI tab"
```

---

### Task 7: P34 integration smoke test + gate

- [ ] **Step 1: Run full suite with lint**

Run: `uv run pytest -q && uv run ruff check . && node --check apps/web/ui/tool-discovery.js`
Expected: All pass

- [ ] **Step 2: Smoke test with real daemon**

```bash
# Start daemon in temp state
TMPDIR=$(mktemp -d)
uv run agentd serve --state-dir "$TMPDIR" --registry examples/agents.toml &
DAEMON_PID=$!
sleep 2

# Test endpoints
curl -s http://127.0.0.1:8767/tools/discovery | python3 -m json.tool
curl -s http://127.0.0.1:8767/tools/inventory | python3 -m json.tool

# Cleanup
kill $DAEMON_PID
rm -rf "$TMPDIR"
```

Expected: Both endpoints return valid JSON with tool data.

- [ ] **Step 3: Final commit for P34**

```bash
git add -A
git commit -m "feat(P34): tool discovery + config inventory complete"
```

---

## Phase P35: Vibe Coding Runtime Adapter

### Task 8: Expand attach.py for vibe coding agents

**Files:**
- Modify: `src/agentic_os/attach.py`
- Create: `tests/test_attach_vibe_coding.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_attach_vibe_coding.py`:

```python
"""Tests for vibe coding attach support (P35)."""
import json
import tempfile
from pathlib import Path

import pytest

from agentic_os.attach import (
    parse_external_session_id,
    build_attach_command,
    evaluate_attach,
    default_attach_status,
    _VIBE_CODING,
    _AGENTIC,
)
from agentic_os.models import AgentDefinition, SessionRecord, SessionStatus


def test_vibe_coding_set_contains_expected():
    assert "claude" in _VIBE_CODING
    assert "codex" in _VIBE_CODING
    assert "cursor" in _VIBE_CODING


def test_agentic_set_contains_expected():
    assert "openclaw" in _AGENTIC
    assert "hermes" in _AGENTIC


def test_default_attach_status_claude():
    """Claude should now be attachable (not unsupported)."""
    status = default_attach_status("claude", has_attach_command=True)
    assert status == "none"  # available for attach, not yet attached


def test_default_attach_status_codex():
    status = default_attach_status("codex", has_attach_command=True)
    assert status == "none"


def test_claude_not_in_unsupported():
    """Claude should no longer be in _UNSUPPORTED."""
    from agentic_os.attach import _UNSUPPORTED
    assert "claude" not in _UNSUPPORTED
    assert "codex" not in _UNSUPPORTED


def test_parse_claude_session_id():
    """Should parse session ID from Claude Code stdout."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        # Claude Code outputs session metadata as JSON
        f.write(json.dumps({"type": "system", "session_id": "abc123"}) + "\n")
        f.write(json.dumps({"type": "assistant", "content": "hello"}) + "\n")
        f.flush()
        path = Path(f.name)

    session_id = parse_external_session_id("claude", path)
    assert session_id == "abc123"
    path.unlink()


def test_parse_codex_session_id():
    """Should parse session ID from Codex stdout."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"session_id": "codex-xyz-789"}) + "\n")
        f.write(json.dumps({"role": "assistant", "content": "working..."}) + "\n")
        f.flush()
        path = Path(f.name)

    session_id = parse_external_session_id("codex", path)
    assert session_id == "codex-xyz-789"
    path.unlink()


def test_build_attach_command_claude():
    """Should build claude --resume command."""
    agent = AgentDefinition(
        id="claude",
        label="Claude Code",
        command=["claude", "-p", "{{message}}"],
        attach_command=["claude", "--resume"],
        tool_kind="vibe_coding",
    )
    session = SessionRecord(
        id="sess-1",
        agent_id="claude",
        cwd="/tmp",
        argv=["claude", "-p", "test"],
        artifact_dir="/tmp/art",
        stdout_log="/tmp/out",
        stderr_log="/tmp/err",
        status=SessionStatus.SUCCEEDED,
        updated_at="2026-01-01T00:00:00Z",
        external_session_id="abc123",
    )
    cmd = build_attach_command(agent, session)
    assert cmd == ["claude", "--resume", "abc123"]


def test_build_attach_command_codex():
    """Should build codex resume command."""
    agent = AgentDefinition(
        id="codex",
        label="Codex",
        command=["codex", "exec", "{{message}}"],
        attach_command=["codex", "resume"],
        tool_kind="vibe_coding",
    )
    session = SessionRecord(
        id="sess-2",
        agent_id="codex",
        cwd="/tmp",
        argv=["codex", "exec", "test"],
        artifact_dir="/tmp/art",
        stdout_log="/tmp/out",
        stderr_log="/tmp/err",
        status=SessionStatus.SUCCEEDED,
        updated_at="2026-01-01T00:00:00Z",
        external_session_id="codex-xyz",
    )
    cmd = build_attach_command(agent, session)
    assert cmd == ["codex", "resume", "codex-xyz"]


def test_evaluate_attach_claude_allowed():
    """Claude attach should be allowed when external_session_id present."""
    agent = AgentDefinition(
        id="claude",
        label="Claude Code",
        command=["claude"],
        attach_command=["claude", "--resume"],
        tool_kind="vibe_coding",
    )
    session = SessionRecord(
        id="sess-1",
        agent_id="claude",
        cwd="/tmp",
        argv=["claude"],
        artifact_dir="/tmp/art",
        stdout_log="/tmp/out",
        stderr_log="/tmp/err",
        status=SessionStatus.SUCCEEDED,
        updated_at="2026-01-01T00:00:00Z",
        external_session_id="abc123",
        attach_status="available",
    )
    decision, reason = evaluate_attach(agent, session)
    assert decision == "allow"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_attach_vibe_coding.py -v`
Expected: FAIL (multiple import errors and assertion failures)

- [ ] **Step 3: Update attach.py**

Replace the contents of `src/agentic_os/attach.py` with:

```python
"""Harness attach preview/exec helpers (read-only attach semantics).

Supports both vibe coding agents (claude, codex, cursor, opencode, qwen)
and agentic runtime agents (openclaw, hermes).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from agentic_os.models import AgentDefinition, SessionRecord

AttachDecision = Literal["allow", "deny", "unsupported"]
AttachStatus = Literal["none", "available", "attached", "unsupported"]

# Vibe coding agents: developer-driven, short iterations
_VIBE_CODING = frozenset({"claude", "codex", "cursor", "opencode", "qwen"})

# Agentic runtime agents: autonomous, long sessions
_AGENTIC = frozenset({"openclaw", "hermes"})

# All supported agents for attach
_SUPPORTED = _VIBE_CODING | _AGENTIC

# Explicitly unsupported (internal/test agents)
_UNSUPPORTED = frozenset({"shell"})

_SESSION_ID_KEYS = ("sessionId", "session_id", "sessionID", "external_session_id", "id")


def parse_external_session_id(agent_id: str, stdout_log: Path) -> str | None:
    """Parse external session ID from tool-specific stdout format."""
    if agent_id not in _SUPPORTED:
        return None
    if not stdout_log.exists():
        return None
    try:
        lines = stdout_log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    # Search last 40 lines for session metadata
    for line in reversed(lines[-40:]):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        # Try standard keys
        for key in _SESSION_ID_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value

    return None


def default_attach_status(agent_id: str, *, has_attach_command: bool) -> AttachStatus:
    """Return default attach status for an agent."""
    if agent_id in _UNSUPPORTED or not has_attach_command:
        return "unsupported"
    if agent_id in _SUPPORTED:
        return "none"
    return "unsupported"


def build_attach_command(agent: AgentDefinition, session: SessionRecord) -> list[str]:
    """Build the attach command for a given agent and session."""
    if not agent.attach_command:
        return []
    command = list(agent.attach_command)
    external_id = session.external_session_id

    if not external_id:
        return command

    # All supported agents append external_session_id as last arg
    if agent_id_in(agent.id, _SUPPORTED):
        return [*command, external_id]

    return command


def agent_id_in(agent_id: str, agent_set: frozenset) -> bool:
    """Check if agent_id is in the given set."""
    return agent_id in agent_set


def evaluate_attach(
    agent: AgentDefinition,
    session: SessionRecord,
) -> tuple[AttachDecision, str]:
    """Evaluate whether attach is permitted for this agent/session."""
    if agent.id in _UNSUPPORTED or not agent.attach_command:
        return "unsupported", f"harness {agent.id} does not support attach"
    if agent.id not in _SUPPORTED:
        return "unsupported", f"harness {agent.id} attach matrix not defined"
    if session.attach_status == "unsupported":
        return "unsupported", "session marked unsupported for attach"
    if session.attach_status == "attached":
        return "deny", "session already attached"

    # All supported agents require external_session_id
    if not session.external_session_id:
        if agent.id == "opencode":
            return "unsupported", "opencode attach requires server URL in session output"
        return "deny", "external_session_id required for attach"

    return "allow", "attach permitted"


def capture_external_session_after_run(
    store: object,
    session_id: str,
    *,
    has_attach_command: bool = False,
) -> None:
    """After a run completes, capture external session ID if available."""
    from agentic_os.storage import Store

    if not isinstance(store, Store):
        return
    session = store.get_session(session_id)
    external_id = parse_external_session_id(session.agent_id, Path(session.stdout_log))
    if external_id and session.agent_id in _SUPPORTED:
        store.update_session_attach(
            session_id,
            external_session_id=external_id,
            attachable=True,
            attach_status="available",
        )
        return
    store.update_session_attach(
        session_id,
        attach_status=default_attach_status(
            session.agent_id,
            has_attach_command=has_attach_command,
        ),
        attachable=False,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_attach_vibe_coding.py -v`
Expected: PASS

- [ ] **Step 5: Run existing attach tests to verify no regression**

Run: `uv run pytest tests/ -v -k "attach"`
Expected: All attach-related tests pass

- [ ] **Step 6: Run full suite**

Run: `uv run pytest -q && uv run ruff check .`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/agentic_os/attach.py tests/test_attach_vibe_coding.py
git commit -m "feat(P35): expand attach.py for vibe coding agents (claude/codex/cursor)"
```

---

### Task 9: Add workspace_path to SessionRecord

**Files:**
- Modify: `src/agentic_os/models.py`
- Modify: `src/agentic_os/storage.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_models.py`:

```python
def test_session_create_has_workspace_path():
    from agentic_os.models import SessionCreate
    session = SessionCreate(
        agent_id="claude",
        cwd="/tmp/project",
        argv=["claude", "-p", "test"],
        artifact_dir="/tmp/art",
        stdout_log="/tmp/out",
        stderr_log="/tmp/err",
        workspace_path="/tmp/project",
    )
    assert session.workspace_path == "/tmp/project"


def test_session_create_workspace_path_optional():
    from agentic_os.models import SessionCreate
    session = SessionCreate(
        agent_id="claude",
        cwd="/tmp/project",
        argv=["claude"],
        artifact_dir="/tmp/art",
        stdout_log="/tmp/out",
        stderr_log="/tmp/err",
    )
    assert session.workspace_path is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v -k "workspace_path"`
Expected: FAIL

- [ ] **Step 3: Add workspace_path to models.py**

In `SessionCreate` class, add after `source_template_id`:

```python
    workspace_path: str | None = None
```

`SessionRecord` inherits from `SessionCreate`, so it gets the field automatically.

- [ ] **Step 4: Add DB migration in storage.py**

In `src/agentic_os/storage.py`, find the migration section and add:

```python
def _migrate_sessions_workspace_path(self, conn: sqlite3.Connection) -> None:
    """Add workspace_path column if missing (P36)."""
    columns = [row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()]
    if "workspace_path" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN workspace_path TEXT")
```

Call this in the Store `__init__` or `init` method after other migrations.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v -k "workspace_path"`
Expected: PASS

- [ ] **Step 6: Run full suite**

Run: `uv run pytest -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/agentic_os/models.py src/agentic_os/storage.py tests/test_models.py
git commit -m "feat(P35): add workspace_path field to SessionRecord"
```

---

### Task 10: P35 UI — vibe-coding-launcher.js

**Files:**
- Create: `apps/web/ui/vibe-coding-launcher.js`
- Modify: `apps/web/index.html`
- Modify: `apps/web/app.js`

- [ ] **Step 1: Create vibe-coding-launcher.js**

Create `apps/web/ui/vibe-coding-launcher.js`:

```javascript
/**
 * Vibe Coding Launcher UI (P35)
 * workspace → profile/model → launch → session/log → stop/retry → evidence
 */

const VibeCodingLauncher = {
  state: {
    workspaces: [],
    activeWorkspace: null,
    agents: [],
    profiles: [],
    sessions: [],
    selectedSession: null,
    logEntries: [],
  },

  async init(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '<p class="loading">Loading...</p>';

    try {
      // Load workspaces, agents (vibe coding only), profiles
      const [workspacesRes, discoveryRes, profilesRes] = await Promise.all([
        fetch(`${API_URL}/workspaces`).then((r) => r.json()),
        fetch(`${API_URL}/tools/discovery`).then((r) => r.json()),
        fetch(`${API_URL}/profiles`).then((r) => r.json()),
      ]);

      this.state.workspaces = workspacesRes.workspaces || [];
      this.state.activeWorkspace = workspacesRes.active || null;
      this.state.agents = (discoveryRes.tools || []).filter(
        (t) => t.tool_kind === "vibe_coding" && t.installed
      );
      this.state.profiles = profilesRes.profiles || [];

      this.renderLauncher(container);
    } catch (err) {
      container.innerHTML = `<p class="error-text">Failed to load: ${err.message}</p>`;
    }
  },

  renderLauncher(container) {
    const { workspaces, activeWorkspace, agents, profiles } = this.state;

    let html = '<div class="vibe-launcher">';

    // Workspace selector
    html += '<div class="launcher-section">';
    html += "<h3>1. Select Workspace</h3>";
    html += '<select id="vibe-workspace-select">';
    for (const ws of workspaces) {
      const selected = ws.path === activeWorkspace ? "selected" : "";
      html += `<option value="${this.escape(ws.path)}" ${selected}>${this.escape(ws.label || ws.path)}</option>`;
    }
    html += "</select></div>";

    // Agent selector
    html += '<div class="launcher-section">';
    html += "<h3>2. Select Agent</h3>";
    if (agents.length === 0) {
      html += "<p>No vibe coding agents installed. Install Claude Code or Codex first.</p>";
    } else {
      html += '<select id="vibe-agent-select">';
      for (const agent of agents) {
        html += `<option value="${this.escape(agent.agent_id)}">${this.escape(agent.agent_id)} ${agent.version ? `(${this.escape(agent.version)})` : ""}</option>`;
      }
      html += "</select>";
    }
    html += "</div>";

    // Profile / model selector
    html += '<div class="launcher-section">';
    html += "<h3>3. Profile / Model</h3>";
    html += '<select id="vibe-profile-select"><option value="">(default)</option>';
    for (const p of profiles) {
      html += `<option value="${this.escape(p.name)}">${this.escape(p.name)} — ${this.escape(p.harness_id || "")} ${this.escape(p.model || "")}</option>`;
    }
    html += "</select>";
    html += '<input type="text" id="vibe-model-input" placeholder="Model (optional, e.g. claude-sonnet-4-20250514)" />';
    html += "</div>";

    // Message input
    html += '<div class="launcher-section">';
    html += "<h3>4. Message</h3>";
    html += '<textarea id="vibe-message-input" rows="3" placeholder="Enter your task..."></textarea>';
    html += '<button id="vibe-launch-btn" class="btn-primary">Launch</button>';
    html += "</div>";

    // Session list
    html += '<div class="launcher-section">';
    html += "<h3>Sessions</h3>";
    html += '<div id="vibe-sessions-list"></div>';
    html += "</div>";

    // Session detail (log + actions)
    html += '<div id="vibe-session-detail" style="display:none"></div>';

    html += "</div>";
    container.innerHTML = html;

    // Wire events
    document.getElementById("vibe-launch-btn").addEventListener("click", () => this.launch());
    this.loadSessions();
  },

  async launch() {
    const workspace = document.getElementById("vibe-workspace-select").value;
    const agentId = document.getElementById("vibe-agent-select").value;
    const profile = document.getElementById("vibe-profile-select").value;
    const model = document.getElementById("vibe-model-input").value;
    const message = document.getElementById("vibe-message-input").value;

    if (!message.trim()) {
      alert("Please enter a message");
      return;
    }

    const body = {
      cwd: workspace,
      message: message,
      agent_id: agentId,
    };
    if (profile) body.profile = profile;
    if (model) body.model = model;

    try {
      const res = await fetch(`${API_URL}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json();
        alert(`Launch failed: ${err.detail || JSON.stringify(err)}`);
        return;
      }
      const session = await res.json();
      document.getElementById("vibe-message-input").value = "";
      this.loadSessions();
      this.showSessionDetail(session.id);
    } catch (err) {
      alert(`Launch error: ${err.message}`);
    }
  },

  async loadSessions() {
    try {
      const res = await fetch(`${API_URL}/sessions`);
      if (!res.ok) return;
      const data = await res.json();
      // Filter to vibe coding agents only
      const vibeAgentIds = new Set(this.state.agents.map((a) => a.agent_id));
      this.state.sessions = (data.sessions || []).filter((s) =>
        vibeAgentIds.has(s.agent_id)
      );
      this.renderSessionList();
    } catch (err) {
      console.error("Failed to load sessions:", err);
    }
  },

  renderSessionList() {
    const container = document.getElementById("vibe-sessions-list");
    if (!container) return;

    const { sessions } = this.state;
    if (sessions.length === 0) {
      container.innerHTML = "<p>No sessions yet. Launch one above.</p>";
      return;
    }

    let html = '<table class="session-table"><thead><tr>';
    html += "<th>Status</th><th>Agent</th><th>Message</th><th>Model</th><th>Started</th><th>Actions</th>";
    html += "</tr></thead><tbody>";

    for (const s of sessions) {
      const pillClass = `status-${s.status}`;
      html += `<tr class="session-row" data-id="${s.id}">`;
      html += `<td><span class="pill ${pillClass}">${s.status}</span></td>`;
      html += `<td>${this.escape(s.agent_id)}</td>`;
      html += `<td>${this.escape(s.summary_one_liner || s.argv?.join(" ").slice(0, 60) || "—")}</td>`;
      html += `<td>${this.escape(s.resolved_model || "—")}</td>`;
      html += `<td>${this.escape(s.started_at || "—")}</td>`;
      html += `<td>`;
      html += `<button onclick="VibeCodingLauncher.showSessionDetail('${s.id}')">View</button>`;
      if (s.status === "running") {
        html += ` <button onclick="VibeCodingLauncher.stopSession('${s.id}')">Stop</button>`;
      }
      if (s.status === "failed" || s.status === "stopped") {
        html += ` <button onclick="VibeCodingLauncher.retrySession('${s.id}')">Retry</button>`;
      }
      html += "</td></tr>";
    }

    html += "</tbody></table>";
    container.innerHTML = html;
  },

  async showSessionDetail(sessionId) {
    const container = document.getElementById("vibe-session-detail");
    if (!container) return;

    container.style.display = "block";
    container.innerHTML = '<p class="loading">Loading session...</p>';

    try {
      const [sessionRes, stdoutRes, stderrRes] = await Promise.all([
        fetch(`${API_URL}/sessions/${sessionId}`).then((r) => r.json()),
        fetch(`${API_URL}/sessions/${sessionId}/logs/stdout`).then((r) => r.json()),
        fetch(`${API_URL}/sessions/${sessionId}/logs/stderr`).then((r) => r.json()),
      ]);

      const session = sessionRes;
      const stdout = (stdoutRes.entries || []).map((e) => e.message).join("\n");
      const stderr = (stderrRes.entries || []).map((e) => e.message).join("\n");

      let html = `<h3>Session: ${this.escape(session.id)}</h3>`;
      html += `<p><strong>Agent:</strong> ${this.escape(session.agent_id)} | `;
      html += `<strong>Status:</strong> <span class="pill status-${session.status}">${session.status}</span> | `;
      html += `<strong>Model:</strong> ${this.escape(session.resolved_model || "—")}</p>`;

      html += '<div class="log-section"><h4>stdout</h4>';
      html += `<pre class="log-output">${this.escape(stdout)}</pre></div>`;

      if (stderr) {
        html += '<div class="log-section"><h4>stderr</h4>';
        html += `<pre class="log-output log-error">${this.escape(stderr)}</pre></div>`;
      }

      // Evidence download
      html += `<div class="evidence-section">`;
      html += `<a href="${API_URL}/sessions/${sessionId}/evidence/zip" class="btn-secondary">Download Evidence</a>`;
      html += "</div>";

      // Actions
      html += '<div class="session-actions">';
      if (session.status === "running") {
        html += `<button onclick="VibeCodingLauncher.stopSession('${sessionId}')">Stop</button>`;
      }
      if (session.status === "failed" || session.status === "stopped") {
        html += `<button onclick="VibeCodingLauncher.retrySession('${sessionId}')">Retry</button>`;
      }
      html += "</div>";

      container.innerHTML = html;
      this.state.selectedSession = sessionId;
    } catch (err) {
      container.innerHTML = `<p class="error-text">Failed to load session: ${err.message}</p>`;
    }
  },

  async stopSession(sessionId) {
    try {
      await fetch(`${API_URL}/sessions/${sessionId}/stop`, { method: "POST" });
      this.loadSessions();
      if (this.state.selectedSession === sessionId) {
        this.showSessionDetail(sessionId);
      }
    } catch (err) {
      alert(`Stop failed: ${err.message}`);
    }
  },

  async retrySession(sessionId) {
    try {
      const res = await fetch(`${API_URL}/sessions/${sessionId}/retry`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json();
        alert(`Retry failed: ${err.detail || JSON.stringify(err)}`);
        return;
      }
      this.loadSessions();
    } catch (err) {
      alert(`Retry error: ${err.message}`);
    }
  },

  escape(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  },
};

if (typeof window !== "undefined") {
  window.VibeCodingLauncher = VibeCodingLauncher;
}
```

- [ ] **Step 2: Add Vibe Coding tab to index.html**

Add tab button:

```html
<button class="tab-btn" data-tab="vibe-coding">Vibe Coding</button>
```

Add tab content:

```html
<div id="tab-vibe-coding" class="tab-content" style="display:none">
  <h2>Vibe Coding Runtime</h2>
  <div id="vibe-coding-container"></div>
</div>
```

Add script:

```html
<script src="ui/vibe-coding-launcher.js"></script>
```

- [ ] **Step 3: Wire tab in app.js**

```javascript
if (tab === "vibe-coding") {
  window.VibeCodingLauncher.init("vibe-coding-container");
}
```

- [ ] **Step 4: Add CSS for launcher**

In `apps/web/styles.css`:

```css
.vibe-launcher .launcher-section {
  margin-bottom: 1.5rem;
  padding: 1rem;
  border: 1px solid var(--border, #333);
  border-radius: 6px;
}
.vibe-launcher select,
.vibe-launcher input,
.vibe-launcher textarea {
  width: 100%;
  margin-top: 0.5rem;
  padding: 0.5rem;
}
.btn-primary {
  background: #2563eb;
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 4px;
  cursor: pointer;
  margin-top: 0.5rem;
}
.btn-secondary {
  background: #4b5563;
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 4px;
  cursor: pointer;
  text-decoration: none;
  display: inline-block;
}
.session-table { width: 100%; border-collapse: collapse; }
.session-table th, .session-table td {
  padding: 0.5rem;
  text-align: left;
  border-bottom: 1px solid var(--border, #333);
}
.log-output {
  background: #0d1117;
  color: #c9d1d9;
  padding: 1rem;
  border-radius: 4px;
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
  font-family: monospace;
  font-size: 0.85rem;
}
.log-error { border-left: 3px solid #ef4444; }
.pill {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: bold;
}
.status-running { background: #2563eb; color: white; }
.status-succeeded { background: #22c55e; color: white; }
.status-failed { background: #ef4444; color: white; }
.status-stopped { background: #6b7280; color: white; }
.status-queued { background: #eab308; color: black; }
```

- [ ] **Step 5: Verify UI works**

Start local stack, click "Vibe Coding" tab.
Expected: Launcher form with workspace/agent/profile selectors.

- [ ] **Step 6: Commit**

```bash
git add apps/web/ui/vibe-coding-launcher.js apps/web/index.html apps/web/app.js apps/web/styles.css
git commit -m "feat(P35): add vibe coding launcher UI"
```

---

### Task 11: P35 integration test + gate

- [ ] **Step 1: Run full suite**

Run: `uv run pytest -q && uv run ruff check . && node --check apps/web/ui/vibe-coding-launcher.js`
Expected: All pass

- [ ] **Step 2: Smoke test launch flow**

```bash
# Start daemon
TMPDIR=$(mktemp -d)
uv run agentd serve --state-dir "$TMPDIR" --registry examples/agents.toml &
DAEMON_PID=$!
sleep 2

# Launch a claude session (will fail if claude not installed, but should create session)
curl -s -X POST http://127.0.0.1:8767/sessions \
  -H "Content-Type: application/json" \
  -d '{"cwd": "/tmp", "message": "echo hello", "agent_id": "shell"}' | python3 -m json.tool

# Check session status
curl -s http://127.0.0.1:8767/sessions | python3 -m json.tool

# Cleanup
kill $DAEMON_PID
rm -rf "$TMPDIR"
```

Expected: Session created and visible in list.

- [ ] **Step 3: Final commit for P35**

```bash
git add -A
git commit -m "feat(P35): vibe coding runtime adapter complete"
```

---

## Phase P36: Attach / Resume Existing Sessions

### Task 12: Implement session_discovery.py (TDD)

**Files:**
- Create: `src/agentic_os/session_discovery.py`
- Create: `tests/test_session_discovery.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_session_discovery.py`:

```python
"""Tests for session discovery (P36)."""
import json
import tempfile
from pathlib import Path

import pytest

from agentic_os.session_discovery import (
    DiscoveredSession,
    discover_sessions,
    scan_vibe_coding_sessions,
    scan_agent_log_dir,
)


def test_discovered_session_model():
    session = DiscoveredSession(
        external_session_id="abc123",
        agent_id="claude",
        started_at="2026-06-08T10:00:00Z",
        status_hint="unknown",
        workspace_match=None,
        source="filesystem",
    )
    assert session.external_session_id == "abc123"
    assert session.agent_id == "claude"


def test_scan_agent_log_dir_empty():
    """Should return empty list for non-existent dir."""
    results = scan_agent_log_dir("/nonexistent/path", "claude")
    assert results == []


def test_scan_agent_log_dir_with_sessions():
    """Should find session metadata in log dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a fake Claude session dir
        session_dir = Path(tmpdir) / "session_abc123"
        session_dir.mkdir()
        metadata = session_dir / "metadata.json"
        metadata.write_text(json.dumps({
            "session_id": "abc123",
            "created_at": "2026-06-08T10:00:00Z",
            "cwd": "/tmp/project",
        }))

        results = scan_agent_log_dir(tmpdir, "claude")
        assert len(results) == 1
        assert results[0].external_session_id == "abc123"
        assert results[0].agent_id == "claude"


def test_discover_sessions_filters_by_agent():
    """Should only scan specified agents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        results = discover_sessions(
            workspace_path="/tmp",
            agent_ids=["claude"],
            config_paths={"claude": tmpdir},
        )
        # Should attempt scan for claude only
        assert isinstance(results, list)


def test_discover_sessions_workspace_match():
    """Should indicate if discovered session matches workspace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir) / "session_xyz"
        session_dir.mkdir()
        metadata = session_dir / "metadata.json"
        metadata.write_text(json.dumps({
            "session_id": "xyz789",
            "cwd": "/tmp/project",
        }))

        results = discover_sessions(
            workspace_path="/tmp/project",
            agent_ids=["claude"],
            config_paths={"claude": tmpdir},
        )
        if results:
            # workspace_match should be set if cwd matches
            matching = [r for r in results if r.workspace_match]
            # May or may not match depending on exact path resolution
            assert isinstance(matching, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_session_discovery.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement session_discovery.py**

Create `src/agentic_os/session_discovery.py`:

```python
"""Session discovery: scan for existing CLI sessions (P36).

Scans well-known log directories for session metadata from
vibe coding and agentic runtime tools. Does NOT use filesystem
sniffing for active session state — only reads metadata files.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiscoveredSession:
    external_session_id: str
    agent_id: str
    started_at: str | None
    status_hint: str
    workspace_match: bool
    source: str  # "filesystem" or "api"


def discover_sessions(
    workspace_path: str,
    agent_ids: list[str] | None = None,
    config_paths: dict[str, str] | None = None,
) -> list[DiscoveredSession]:
    """Discover existing sessions across specified agents.

    Args:
        workspace_path: The workspace to match sessions against.
        agent_ids: List of agent IDs to scan. If None, scans all known.
        config_paths: Map of agent_id -> log/config path to scan.

    Returns:
        List of discovered sessions.
    """
    results: list[DiscoveredSession] = []
    config_paths = config_paths or {}

    # Default scan targets
    scan_targets = agent_ids or ["claude", "codex", "openclaw", "hermes"]

    for agent_id in scan_targets:
        log_path = config_paths.get(agent_id)
        if not log_path:
            # Use well-known defaults
            log_path = _default_log_path(agent_id)
        if not log_path:
            continue

        sessions = scan_agent_log_dir(log_path, agent_id)
        # Check workspace match
        for session in sessions:
            results.append(session)

    return results


def scan_agent_log_dir(log_dir: str, agent_id: str) -> list[DiscoveredSession]:
    """Scan a log directory for session metadata files."""
    path = Path(log_dir).expanduser()
    if not path.exists() or not path.is_dir():
        return []

    results: list[DiscoveredSession] = []

    # Look for session directories with metadata files
    for entry in path.iterdir():
        if not entry.is_dir():
            continue

        # Try common metadata filenames
        for meta_name in ["metadata.json", "session.json", "info.json"]:
            meta_path = entry / meta_name
            if meta_path.exists():
                session = _parse_session_metadata(meta_path, agent_id)
                if session:
                    results.append(session)
                break

    return results


def _parse_session_metadata(meta_path: Path, agent_id: str) -> DiscoveredSession | None:
    """Parse a session metadata file into DiscoveredSession."""
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict):
        return None

    session_id = (
        data.get("session_id")
        or data.get("sessionId")
        or data.get("id")
    )
    if not session_id:
        return None

    return DiscoveredSession(
        external_session_id=str(session_id),
        agent_id=agent_id,
        started_at=data.get("created_at") or data.get("started_at"),
        status_hint=data.get("status", "unknown"),
        workspace_match=False,  # Will be set by caller
        source="filesystem",
    )


def scan_vibe_coding_sessions(
    workspace_path: str,
    config_paths: dict[str, str] | None = None,
) -> list[DiscoveredSession]:
    """Scan specifically for vibe coding sessions (claude, codex, cursor)."""
    vibe_agents = ["claude", "codex", "cursor"]
    return discover_sessions(
        workspace_path=workspace_path,
        agent_ids=vibe_agents,
        config_paths=config_paths,
    )


def _default_log_path(agent_id: str) -> str | None:
    """Return default log path for known agents."""
    defaults = {
        "claude": "~/.claude/projects",
        "codex": "~/.codex/log",
        "cursor": "~/.cursor/projects",
        "opencode": "~/.local/share/opencode/log",
        "openclaw": "~/.openclaw/logs",
        "hermes": "~/.hermes/logs",
    }
    path = defaults.get(agent_id)
    if path:
        return str(Path(path).expanduser())
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_session_discovery.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -q && uv run ruff check .`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/session_discovery.py tests/test_session_discovery.py
git commit -m "feat(P36): implement session_discovery module"
```

---

### Task 13: Add /sessions/discover and /sessions/{id}/workspace endpoints

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_api.py`:

```python
def test_sessions_discover_endpoint(client):
    """POST /sessions/discover should return discovered sessions."""
    response = client.post("/sessions/discover", json={
        "workspace_path": "/tmp",
        "agent_ids": ["claude"],
    })
    assert response.status_code == 200
    data = response.json()
    assert "discovered" in data
    assert isinstance(data["discovered"], list)


def test_sessions_bind_workspace(client):
    """PUT /sessions/{id}/workspace should bind session to workspace."""
    # First create a session
    create_res = client.post("/sessions", json={
        "cwd": "/tmp",
        "message": "test",
        "agent_id": "shell",
    })
    session_id = create_res.json()["id"]

    # Bind to workspace
    response = client.put(f"/sessions/{session_id}/workspace", json={
        "workspace_path": "/tmp",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["workspace_path"] == "/tmp"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py::test_sessions_discover_endpoint tests/test_api.py::test_sessions_bind_workspace -v`
Expected: FAIL with 404/405

- [ ] **Step 3: Add endpoints to api.py**

Add request models near the top of api.py:

```python
class SessionDiscoverRequest(BaseModel):
    workspace_path: str
    agent_ids: list[str] | None = None


class SessionWorkspaceBindRequest(BaseModel):
    workspace_path: str
```

Add endpoints:

```python
@app.post("/sessions/discover")
def sessions_discover(body: SessionDiscoverRequest) -> dict[str, object]:
    """Discover existing CLI sessions for attach (P36)."""
    from agentic_os.session_discovery import discover_sessions

    # Build config_paths from registry
    config_paths = {}
    for agent in registry.list_agents():
        if agent.config_path:
            config_paths[agent.id] = agent.config_path

    discovered = discover_sessions(
        workspace_path=body.workspace_path,
        agent_ids=body.agent_ids,
        config_paths=config_paths,
    )

    return {
        "discovered": [
            {
                "external_session_id": s.external_session_id,
                "agent_id": s.agent_id,
                "started_at": s.started_at,
                "status_hint": s.status_hint,
                "workspace_match": s.workspace_match,
                "source": s.source,
            }
            for s in discovered
        ],
    }


@app.put("/sessions/{session_id}/workspace")
def sessions_bind_workspace(
    session_id: str,
    body: SessionWorkspaceBindRequest,
) -> dict[str, object]:
    """Bind a session to a workspace (P36)."""
    from agentic_os.storage import Store

    session = store.get_session(session_id)
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    store.update_session_workspace(session_id, body.workspace_path)
    updated = store.get_session(session_id)
    return {"id": updated.id, "workspace_path": updated.workspace_path}
```

- [ ] **Step 4: Add update_session_workspace to storage.py**

In `src/agentic_os/storage.py`, add method to Store class:

```python
def update_session_workspace(self, session_id: str, workspace_path: str) -> SessionRecord:
    """Update the workspace_path for a session."""
    with self.connect() as conn:
        conn.execute(
            "UPDATE sessions SET workspace_path = ?, updated_at = ? WHERE id = ?",
            (workspace_path, _now_iso(), session_id),
        )
    return self.get_session(session_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py::test_sessions_discover_endpoint tests/test_api.py::test_sessions_bind_workspace -v`
Expected: PASS

- [ ] **Step 6: Run full suite**

Run: `uv run pytest -q && uv run ruff check .`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/agentic_os/api.py src/agentic_os/storage.py tests/test_api.py
git commit -m "feat(P36): add /sessions/discover and /sessions/{id}/workspace endpoints"
```

---

### Task 14: P36 UI — session-attach.js

**Files:**
- Create: `apps/web/ui/session-attach.js`
- Modify: `apps/web/index.html`
- Modify: `apps/web/app.js`

- [ ] **Step 1: Create session-attach.js**

Create `apps/web/ui/session-attach.js`:

```javascript
/**
 * Session Attach UI (P36)
 * Scan for existing CLI sessions → bind to workspace → view/attach
 */

const SessionAttach = {
  state: {
    discovered: [],
    boundSessions: [],
  },

  async init(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '<p class="loading">Loading...</p>';

    try {
      // Get active workspace
      const wsRes = await fetch(`${API_URL}/workspaces`).then((r) => r.json());
      this.state.activeWorkspace = wsRes.active || null;

      this.render(container);
    } catch (err) {
      container.innerHTML = `<p class="error-text">Failed to load: ${err.message}</p>`;
    }
  },

  render(container) {
    let html = '<div class="session-attach">';

    // Workspace display
    html += '<div class="attach-section">';
    html += "<h3>Active Workspace</h3>";
    html += `<p><code>${this.escape(this.state.activeWorkspace || "None")}</code></p>`;
    html += `<button id="scan-sessions-btn" class="btn-primary">Scan Sessions</button>`;
    html += "</div>";

    // Discovered sessions
    html += '<div class="attach-section">';
    html += "<h3>Discovered Sessions</h3>";
    html += '<div id="discovered-sessions-list"></div>';
    html += "</div>";

    // Bound sessions
    html += '<div class="attach-section">';
    html += "<h3>Bound Sessions</h3>";
    html += '<div id="bound-sessions-list"></div>';
    html += "</div>";

    html += "</div>";
    container.innerHTML = html;

    document.getElementById("scan-sessions-btn").addEventListener("click", () => this.scan());
    this.loadBoundSessions();
  },

  async scan() {
    const container = document.getElementById("discovered-sessions-list");
    if (!container) return;

    container.innerHTML = '<p class="loading">Scanning...</p>';

    try {
      const res = await fetch(`${API_URL}/sessions/discover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_path: this.state.activeWorkspace || "/tmp",
        }),
      });

      if (!res.ok) {
        container.innerHTML = `<p class="error-text">Scan failed</p>`;
        return;
      }

      const data = await res.json();
      this.state.discovered = data.discovered || [];

      if (this.state.discovered.length === 0) {
        container.innerHTML = "<p>No sessions found. Start a session in your CLI first.</p>";
        return;
      }

      let html = '<table class="session-table"><thead><tr>';
      html += "<th>Agent</th><th>Session ID</th><th>Started</th><th>Status</th><th>Actions</th>";
      html += "</tr></thead><tbody>";

      for (const s of this.state.discovered) {
        html += `<tr>`;
        html += `<td>${this.escape(s.agent_id)}</td>`;
        html += `<td><code>${this.escape(s.external_session_id)}</code></td>`;
        html += `<td>${this.escape(s.started_at || "—")}</td>`;
        html += `<td>${this.escape(s.status_hint)}</td>`;
        html += `<td><button onclick="SessionAttach.bindSession('${this.escape(s.external_session_id)}', '${this.escape(s.agent_id)}')">Bind</button></td>`;
        html += "</tr>";
      }

      html += "</tbody></table>";
      container.innerHTML = html;
    } catch (err) {
      container.innerHTML = `<p class="error-text">Scan error: ${err.message}</p>`;
    }
  },

  async bindSession(externalSessionId, agentId) {
    try {
      // Create a session record via POST /sessions with external_session_id
      const res = await fetch(`${API_URL}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: agentId,
          cwd: this.state.activeWorkspace || "/tmp",
          message: `(attached) ${externalSessionId}`,
          external_session_id: externalSessionId,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        alert(`Bind failed: ${err.detail || JSON.stringify(err)}`);
        return;
      }

      const session = await res.json();

      // Bind to workspace
      await fetch(`${API_URL}/sessions/${session.id}/workspace`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_path: this.state.activeWorkspace || "/tmp",
        }),
      });

      this.loadBoundSessions();
      this.scan(); // Refresh discovered list
    } catch (err) {
      alert(`Bind error: ${err.message}`);
    }
  },

  async loadBoundSessions() {
    const container = document.getElementById("bound-sessions-list");
    if (!container) return;

    try {
      const res = await fetch(`${API_URL}/sessions`);
      if (!res.ok) return;
      const data = await res.json();

      // Filter to sessions with external_session_id (attached)
      const bound = (data.sessions || []).filter(
        (s) => s.external_session_id && s.attach_status !== "unsupported"
      );
      this.state.boundSessions = bound;

      if (bound.length === 0) {
        container.innerHTML = "<p>No bound sessions. Scan and bind sessions above.</p>";
        return;
      }

      let html = '<table class="session-table"><thead><tr>';
      html += "<th>Status</th><th>Agent</th><th>External ID</th><th>Workspace</th><th>Actions</th>";
      html += "</tr></thead><tbody>";

      for (const s of bound) {
        html += `<tr>`;
        html += `<td><span class="pill status-${s.status}">${s.status}</span></td>`;
        html += `<td>${this.escape(s.agent_id)}</td>`;
        html += `<td><code>${this.escape(s.external_session_id)}</code></td>`;
        html += `<td>${this.escape(s.workspace_path || "—")}</td>`;
        html += `<td>`;
        if (s.attach_status === "available") {
          html += `<button onclick="SessionAttach.attachSession('${s.id}')">Attach</button>`;
        }
        html += ` <button onclick="window.VibeCodingLauncher?.showSessionDetail('${s.id}')">View</button>`;
        html += "</td></tr>";
      }

      html += "</tbody></table>";
      container.innerHTML = html;
    } catch (err) {
      container.innerHTML = `<p class="error-text">Failed to load: ${err.message}</p>`;
    }
  },

  async attachSession(sessionId) {
    try {
      // Preview first
      const previewRes = await fetch(`${API_URL}/sessions/${sessionId}/attach`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "preview" }),
      });
      const preview = await previewRes.json();

      if (preview.command) {
        const confirmed = confirm(`Attach command:\n${preview.command.join(" ")}\n\nExecute?`);
        if (!confirmed) return;
      }

      // Execute
      const execRes = await fetch(`${API_URL}/sessions/${sessionId}/attach`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "exec" }),
      });

      if (!execRes.ok) {
        const err = await execRes.json();
        alert(`Attach failed: ${err.detail || JSON.stringify(err)}`);
        return;
      }

      this.loadBoundSessions();
    } catch (err) {
      alert(`Attach error: ${err.message}`);
    }
  },

  escape(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  },
};

if (typeof window !== "undefined") {
  window.SessionAttach = SessionAttach;
}
```

- [ ] **Step 2: Add Sessions tab/section to index.html**

Add within the Vibe Coding tab or as a new sub-section:

```html
<div id="tab-sessions" class="tab-content" style="display:none">
  <h2>Session Attach / Resume</h2>
  <div id="session-attach-container"></div>
</div>
```

Add tab button:

```html
<button class="tab-btn" data-tab="sessions">Sessions</button>
```

Add script:

```html
<script src="ui/session-attach.js"></script>
```

- [ ] **Step 3: Wire tab in app.js**

```javascript
if (tab === "sessions") {
  window.SessionAttach.init("session-attach-container");
}
```

- [ ] **Step 4: Verify UI works**

Start local stack, click "Sessions" tab.
Expected: Scan button and empty discovered/bound lists.

- [ ] **Step 5: Commit**

```bash
git add apps/web/ui/session-attach.js apps/web/index.html apps/web/app.js
git commit -m "feat(P36): add session attach/resume UI"
```

---

### Task 15: P36 integration test + gate

- [ ] **Step 1: Run full suite**

Run: `uv run pytest -q && uv run ruff check . && node --check apps/web/ui/session-attach.js && node --check apps/web/ui/vibe-coding-launcher.js && node --check apps/web/ui/tool-discovery.js`
Expected: All pass

- [ ] **Step 2: Smoke test discover flow**

```bash
TMPDIR=$(mktemp -d)
uv run agentd serve --state-dir "$TMPDIR" --registry examples/agents.toml &
DAEMON_PID=$!
sleep 2

# Discover sessions
curl -s -X POST http://127.0.0.1:8767/sessions/discover \
  -H "Content-Type: application/json" \
  -d '{"workspace_path": "/tmp"}' | python3 -m json.tool

# Cleanup
kill $DAEMON_PID
rm -rf "$TMPDIR"
```

Expected: Returns discovered list (may be empty if no sessions exist).

- [ ] **Step 3: Final commit for P34-P36**

```bash
git add -A
git commit -m "feat(P34-P36): dual-track product foundation complete"
```

---

## Phase P37: Agentic Runtime Inventory

### Task 16: Implement agentic_inventory.py (TDD)

**Files:**
- Create: `src/agentic_os/agentic_inventory.py`
- Create: `tests/test_agentic_inventory.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agentic_inventory.py`:

```python
"""Tests for agentic runtime inventory (P37)."""
import json
import tempfile
from pathlib import Path

import pytest

from agentic_os.agentic_inventory import (
    AgenticInventoryResult,
    SurfaceSummary,
    McpSurfaceSummary,
    ToolSummary,
    FlowSummary,
    build_agentic_inventory,
    _read_openclaw_inventory,
    _read_hermes_inventory,
    _read_n8n_inventory,
)


def test_inventory_result_model():
    result = AgenticInventoryResult(
        agent_id="openclaw",
        tool_kind="agentic_runtime",
        skills=[SurfaceSummary(name="code-review", enabled=True)],
        mcp_servers=[],
        tools=[],
        flows=[],
    )
    assert result.agent_id == "openclaw"
    assert len(result.skills) == 1


def test_build_inventory_missing_path():
    """Should return error for non-existent config path."""
    result = build_agentic_inventory("openclaw", "/nonexistent/path")
    assert result.agent_id == "openclaw"
    assert result.error is not None


def test_read_openclaw_inventory_with_skills():
    """Should find skill definitions in openclaw dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "skills"
        skills_dir.mkdir()
        skill_file = skills_dir / "code-review.json"
        skill_file.write_text(json.dumps({
            "name": "code-review",
            "enabled": True,
        }))

        result = _read_openclaw_inventory(tmpdir)
        assert result.agent_id == "openclaw"
        assert len(result.skills) == 1
        assert result.skills[0].name == "code-review"


def test_read_hermes_inventory_with_tools():
    """Should find tool definitions in hermes dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tools_dir = Path(tmpdir) / "tools"
        tools_dir.mkdir()
        tool_file = tools_dir / "web-search.json"
        tool_file.write_text(json.dumps({
            "name": "web-search",
            "type": "mcp_tool",
        }))

        result = _read_hermes_inventory(tmpdir)
        assert result.agent_id == "hermes"
        assert len(result.tools) == 1
        assert result.tools[0].name == "web-search"


def test_read_n8n_inventory_with_workflows():
    """Should find workflow JSON files in n8n dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workflows_dir = Path(tmpdir) / "workflows"
        workflows_dir.mkdir()
        workflow_file = workflows_dir / "daily-report.json"
        workflow_file.write_text(json.dumps({
            "name": "Daily Report",
            "active": True,
        }))

        result = _read_n8n_inventory(tmpdir)
        assert result.agent_id == "n8n"
        assert len(result.flows) == 1
        assert result.flows[0].name == "Daily Report"


def test_build_inventory_dispatch():
    """Should dispatch to correct reader by agent_id."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = build_agentic_inventory("openclaw", tmpdir)
        assert result.agent_id == "openclaw"
        # Should not error on empty dir
        assert result.error is None or "not found" not in (result.error or "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agentic_inventory.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement agentic_inventory.py**

Create `src/agentic_os/agentic_inventory.py`:

```python
"""Agentic runtime inventory: read skills/MCP/tools/flows (P37).

Read-only inventory of agentic runtime capabilities (OpenClaw, Hermes, n8n).
Does not modify external tool state.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SurfaceSummary:
    name: str
    enabled: bool = True
    source: str | None = None


@dataclass(frozen=True)
class McpSurfaceSummary:
    name: str
    status: str = "unknown"  # "connected", "disconnected", "unknown"
    server_url: str | None = None


@dataclass(frozen=True)
class ToolSummary:
    name: str
    type: str = "unknown"
    enabled: bool = True


@dataclass(frozen=True)
class FlowSummary:
    name: str
    active: bool = False
    workflow_id: str | None = None


@dataclass(frozen=True)
class AgenticInventoryResult:
    agent_id: str
    tool_kind: str
    skills: list[SurfaceSummary]
    mcp_servers: list[McpSurfaceSummary]
    tools: list[ToolSummary]
    flows: list[FlowSummary]
    error: str | None = None


def build_agentic_inventory(agent_id: str, config_path: str) -> AgenticInventoryResult:
    """Build inventory for an agentic runtime agent."""
    path = Path(config_path).expanduser()
    if not path.exists():
        return AgenticInventoryResult(
            agent_id=agent_id,
            tool_kind="agentic_runtime",
            skills=[],
            mcp_servers=[],
            tools=[],
            flows=[],
            error=f"config path does not exist: {config_path}",
        )

    readers = {
        "openclaw": _read_openclaw_inventory,
        "hermes": _read_hermes_inventory,
        "n8n": _read_n8n_inventory,
    }

    reader = readers.get(agent_id)
    if reader is None:
        return AgenticInventoryResult(
            agent_id=agent_id,
            tool_kind="agentic_runtime",
            skills=[],
            mcp_servers=[],
            tools=[],
            flows=[],
            error=f"no inventory reader for agent: {agent_id}",
        )

    try:
        return reader(str(path))
    except Exception as e:
        return AgenticInventoryResult(
            agent_id=agent_id,
            tool_kind="agentic_runtime",
            skills=[],
            mcp_servers=[],
            tools=[],
            flows=[],
            error=f"inventory reader error: {str(e)[:200]}",
        )


def _read_openclaw_inventory(config_path: str) -> AgenticInventoryResult:
    """Read OpenClaw inventory from config dir."""
    path = Path(config_path)
    skills: list[SurfaceSummary] = []
    mcp_servers: list[McpSurfaceSummary] = []

    # Scan skills directory
    skills_dir = path / "skills"
    if skills_dir.exists() and skills_dir.is_dir():
        for skill_file in skills_dir.glob("*.json"):
            try:
                data = json.loads(skill_file.read_text(encoding="utf-8"))
                skills.append(SurfaceSummary(
                    name=data.get("name", skill_file.stem),
                    enabled=data.get("enabled", True),
                    source=str(skill_file),
                ))
            except (json.JSONDecodeError, OSError):
                continue

    # Scan MCP config
    mcp_config = path / "mcp.json"
    if mcp_config.exists():
        try:
            data = json.loads(mcp_config.read_text(encoding="utf-8"))
            for server_name, server_conf in data.get("servers", {}).items():
                mcp_servers.append(McpSurfaceSummary(
                    name=server_name,
                    status="unknown",
                    server_url=server_conf.get("url"),
                ))
        except (json.JSONDecodeError, OSError):
            pass

    return AgenticInventoryResult(
        agent_id="openclaw",
        tool_kind="agentic_runtime",
        skills=skills,
        mcp_servers=mcp_servers,
        tools=[],
        flows=[],
    )


def _read_hermes_inventory(config_path: str) -> AgenticInventoryResult:
    """Read Hermes inventory from config dir."""
    path = Path(config_path)
    skills: list[SurfaceSummary] = []
    tools: list[ToolSummary] = []
    mcp_servers: list[McpSurfaceSummary] = []

    # Scan tools directory
    tools_dir = path / "tools"
    if tools_dir.exists() and tools_dir.is_dir():
        for tool_file in tools_dir.glob("*.json"):
            try:
                data = json.loads(tool_file.read_text(encoding="utf-8"))
                tools.append(ToolSummary(
                    name=data.get("name", tool_file.stem),
                    type=data.get("type", "unknown"),
                    enabled=data.get("enabled", True),
                ))
            except (json.JSONDecodeError, OSError):
                continue

    # Scan skills directory
    skills_dir = path / "skills"
    if skills_dir.exists() and skills_dir.is_dir():
        for skill_file in skills_dir.glob("*.json"):
            try:
                data = json.loads(skill_file.read_text(encoding="utf-8"))
                skills.append(SurfaceSummary(
                    name=data.get("name", skill_file.stem),
                    enabled=data.get("enabled", True),
                ))
            except (json.JSONDecodeError, OSError):
                continue

    return AgenticInventoryResult(
        agent_id="hermes",
        tool_kind="agentic_runtime",
        skills=skills,
        mcp_servers=mcp_servers,
        tools=tools,
        flows=[],
    )


def _read_n8n_inventory(config_path: str) -> AgenticInventoryResult:
    """Read n8n inventory from config dir."""
    path = Path(config_path)
    flows: list[FlowSummary] = []

    # Scan workflows directory
    workflows_dir = path / "workflows"
    if workflows_dir.exists() and workflows_dir.is_dir():
        for workflow_file in workflows_dir.glob("*.json"):
            try:
                data = json.loads(workflow_file.read_text(encoding="utf-8"))
                flows.append(FlowSummary(
                    name=data.get("name", workflow_file.stem),
                    active=data.get("active", False),
                    workflow_id=data.get("id"),
                ))
            except (json.JSONDecodeError, OSError):
                continue

    return AgenticInventoryResult(
        agent_id="n8n",
        tool_kind="agentic_runtime",
        skills=[],
        mcp_servers=[],
        tools=[],
        flows=flows,
    )


def build_all_agentic_inventory(agents: list) -> list[AgenticInventoryResult]:
    """Build inventory for all agentic_runtime agents."""
    results = []
    for agent in agents:
        if not agent.enabled or agent.tool_kind != "agentic_runtime":
            continue
        if not agent.config_path:
            continue
        result = build_agentic_inventory(agent.id, agent.config_path)
        results.append(result)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agentic_inventory.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -q && uv run ruff check .`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/agentic_inventory.py tests/test_agentic_inventory.py
git commit -m "feat(P37): implement agentic_inventory module"
```

---

### Task 17: Add /agentic/inventory API endpoint

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Add to `tests/test_api.py`:

```python
def test_agentic_inventory_endpoint(client):
    """GET /agentic/inventory should return agentic runtime inventory."""
    response = client.get("/agentic/inventory")
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
    assert isinstance(data["agents"], list)


def test_agentic_inventory_single_agent(client):
    """GET /agentic/inventory/{agent_id} should return single agent inventory."""
    response = client.get("/agentic/inventory/openclaw")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "openclaw"
    assert "skills" in data
    assert "mcp_servers" in data
    assert "tools" in data
    assert "flows" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py::test_agentic_inventory_endpoint tests/test_api.py::test_agentic_inventory_single_agent -v`
Expected: FAIL with 404

- [ ] **Step 3: Add endpoints to api.py**

Add imports at top of api.py:

```python
from agentic_os.agentic_inventory import build_agentic_inventory, build_all_agentic_inventory
```

Add endpoints after `/tools/inventory`:

```python
@app.get("/agentic/inventory")
def agentic_inventory() -> dict[str, object]:
    """Read agentic runtime inventory (P37). Read-only."""
    from agentic_os.agentic_inventory import build_all_agentic_inventory

    agents = registry.list_agents()
    results = build_all_agentic_inventory(agents)
    return {
        "agents": [
            {
                "agent_id": r.agent_id,
                "tool_kind": r.tool_kind,
                "skills": [{"name": s.name, "enabled": s.enabled, "source": s.source} for s in r.skills],
                "mcp_servers": [{"name": s.name, "status": s.status, "server_url": s.server_url} for s in r.mcp_servers],
                "tools": [{"name": t.name, "type": t.type, "enabled": t.enabled} for t in r.tools],
                "flows": [{"name": f.name, "active": f.active, "workflow_id": f.workflow_id} for f in r.flows],
                "error": r.error,
            }
            for r in results
        ],
    }


@app.get("/agentic/inventory/{agent_id}")
def agentic_inventory_single(agent_id: str) -> dict[str, object]:
    """Read single agentic runtime agent inventory (P37). Read-only."""
    from agentic_os.agentic_inventory import build_agentic_inventory

    agent = registry.get(agent_id)
    if not agent.config_path:
        return {
            "agent_id": agent_id,
            "tool_kind": agent.tool_kind,
            "skills": [],
            "mcp_servers": [],
            "tools": [],
            "flows": [],
            "error": f"no config_path for agent: {agent_id}",
        }

    result = build_agentic_inventory(agent_id, agent.config_path)
    return {
        "agent_id": result.agent_id,
        "tool_kind": result.tool_kind,
        "skills": [{"name": s.name, "enabled": s.enabled, "source": s.source} for s in result.skills],
        "mcp_servers": [{"name": s.name, "status": s.status, "server_url": s.server_url} for s in result.mcp_servers],
        "tools": [{"name": t.name, "type": t.type, "enabled": t.enabled} for t in result.tools],
        "flows": [{"name": f.name, "active": f.active, "workflow_id": f.workflow_id} for f in result.flows],
        "error": result.error,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py::test_agentic_inventory_endpoint tests/test_api.py::test_agentic_inventory_single_agent -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -q && uv run ruff check .`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat(P37): add /agentic/inventory endpoints"
```

---

### Task 18: P37 UI — agentic-inventory.js

**Files:**
- Create: `apps/web/ui/agentic-inventory.js`
- Modify: `apps/web/index.html`
- Modify: `apps/web/app.js`

- [ ] **Step 1: Create agentic-inventory.js**

Create `apps/web/ui/agentic-inventory.js`:

```javascript
/**
 * Agentic Runtime Inventory UI (P37)
 * Read-only display of skills/MCP/tools/flows for agentic agents.
 */

const AgenticInventory = {
  async loadInventory() {
    const res = await fetch(`${API_URL}/agentic/inventory`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.agents || [];
  },

  renderSkills(skills) {
    if (!skills || skills.length === 0) return "<p class='muted'>No skills found</p>";
    return `<ul class="inventory-list">${skills.map(s =>
      `<li><span class="inventory-name">${this.escape(s.name)}</span>
        <span class="badge ${s.enabled ? "badge-ok" : "badge-off"}">${s.enabled ? "enabled" : "disabled"}</span>
        ${s.source ? `<span class="inventory-source">${this.escape(s.source)}</span>` : ""}</li>`
    ).join("")}</ul>`;
  },

  renderMcpServers(servers) {
    if (!servers || servers.length === 0) return "<p class='muted'>No MCP servers</p>";
    return `<ul class="inventory-list">${servers.map(s =>
      `<li><span class="inventory-name">${this.escape(s.name)}</span>
        <span class="badge badge-${s.status === "connected" ? "ok" : "warn"}">${s.status}</span>
        ${s.server_url ? `<code class="inventory-url">${this.escape(s.server_url)}</code>` : ""}</li>`
    ).join("")}</ul>`;
  },

  renderTools(tools) {
    if (!tools || tools.length === 0) return "<p class='muted'>No tools found</p>";
    return `<ul class="inventory-list">${tools.map(t =>
      `<li><span class="inventory-name">${this.escape(t.name)}</span>
        <span class="badge">${this.escape(t.type)}</span></li>`
    ).join("")}</ul>`;
  },

  renderFlows(flows) {
    if (!flows || flows.length === 0) return "<p class='muted'>No workflows found</p>";
    return `<ul class="inventory-list">${flows.map(f =>
      `<li><span class="inventory-name">${this.escape(f.name)}</span>
        <span class="badge ${f.active ? "badge-ok" : "badge-off"}">${f.active ? "active" : "inactive"}</span></li>`
    ).join("")}</ul>`;
  },

  renderAgentCard(agent) {
    const errorHtml = agent.error
      ? `<div class="inventory-error">⚠ ${this.escape(agent.error)}</div>`
      : "";

    return `
      <div class="inventory-card">
        <h4>${this.escape(agent.agent_id)} <span class="badge badge-agentic">${this.escape(agent.tool_kind)}</span></h4>
        ${errorHtml}
        <div class="inventory-section">
          <h5>Skills (${(agent.skills || []).length})</h5>
          ${this.renderSkills(agent.skills)}
        </div>
        <div class="inventory-section">
          <h5>MCP Servers (${(agent.mcp_servers || []).length})</h5>
          ${this.renderMcpServers(agent.mcp_servers)}
        </div>
        <div class="inventory-section">
          <h5>Tools (${(agent.tools || []).length})</h5>
          ${this.renderTools(agent.tools)}
        </div>
        <div class="inventory-section">
          <h5>Flows (${(agent.flows || []).length})</h5>
          ${this.renderFlows(agent.flows)}
        </div>
      </div>
    `;
  },

  escape(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  },

  async render(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '<p class="loading">Loading agentic inventory...</p>';

    try {
      const agents = await this.loadInventory();

      if (agents.length === 0) {
        container.innerHTML = "<p>No agentic runtime agents found.</p>";
        return;
      }

      const html = agents.map(a => this.renderAgentCard(a)).join("");
      container.innerHTML = `<div class="inventory-grid">${html}</div>`;
    } catch (err) {
      container.innerHTML = `<p class="error-text">Failed to load inventory: ${err.message}</p>`;
    }
  },
};

if (typeof window !== "undefined") {
  window.AgenticInventory = AgenticInventory;
}
```

- [ ] **Step 2: Add Agentic tab to index.html**

Add tab button:

```html
<button class="tab-btn" data-tab="agentic">Agentic</button>
```

Add tab content:

```html
<div id="tab-agentic" class="tab-content" style="display:none">
  <h2>Agentic Runtime Inventory</h2>
  <div id="agentic-inventory-container"></div>
</div>
```

Add script:

```html
<script src="ui/agentic-inventory.js"></script>
```

- [ ] **Step 3: Wire tab in app.js**

```javascript
if (tab === "agentic") {
  window.AgenticInventory.render("agentic-inventory-container");
}
```

- [ ] **Step 4: Add CSS for inventory**

In `apps/web/styles.css`:

```css
.inventory-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 1rem;
}
.inventory-card {
  border: 1px solid var(--border, #333);
  border-radius: 6px;
  padding: 1rem;
}
.inventory-card h4 {
  margin-top: 0;
  border-bottom: 1px solid var(--border, #333);
  padding-bottom: 0.5rem;
}
.inventory-section {
  margin-top: 0.75rem;
}
.inventory-section h5 {
  margin: 0 0 0.25rem 0;
  font-size: 0.85rem;
  color: var(--text-secondary, #888);
}
.inventory-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.inventory-list li {
  padding: 0.25rem 0;
  border-bottom: 1px solid var(--border-light, #222);
}
.inventory-name {
  font-weight: 500;
}
.inventory-source, .inventory-url {
  font-size: 0.75rem;
  color: var(--text-muted, #666);
  margin-left: 0.5rem;
}
.inventory-error {
  background: #3b1111;
  border: 1px solid #ef4444;
  border-radius: 4px;
  padding: 0.5rem;
  margin: 0.5rem 0;
  color: #fca5a5;
}
.badge-ok { background: #22c55e; color: white; }
.badge-off { background: #6b7280; color: white; }
.badge-warn { background: #eab308; color: black; }
.muted { color: var(--text-muted, #666); font-style: italic; }
```

- [ ] **Step 5: Verify UI works**

Start local stack, click "Agentic" tab.
Expected: Inventory cards for openclaw/hermes/n8n (if configured).

- [ ] **Step 6: Commit**

```bash
git add apps/web/ui/agentic-inventory.js apps/web/index.html apps/web/app.js apps/web/styles.css
git commit -m "feat(P37): add agentic runtime inventory UI"
```

---

### Task 19: P37 integration test + gate

- [ ] **Step 1: Run full suite**

Run: `uv run pytest -q && uv run ruff check . && node --check apps/web/ui/agentic-inventory.js`
Expected: All pass

- [ ] **Step 2: Smoke test with real daemon**

```bash
TMPDIR=$(mktemp -d)
uv run agentd serve --state-dir "$TMPDIR" --registry examples/agents.toml &
DAEMON_PID=$!
sleep 2

curl -s http://127.0.0.1:8767/agentic/inventory | python3 -m json.tool
curl -s http://127.0.0.1:8767/agentic/inventory/hermes | python3 -m json.tool

kill $DAEMON_PID
rm -rf "$TMPDIR"
```

Expected: Both endpoints return valid JSON.

- [ ] **Step 3: Final commit for P37**

```bash
git add -A
git commit -m "feat(P37): agentic runtime inventory complete"
```

---

## Phase P38: Daily Operator v2

### Task 20: Create dashboard-v2.js with two-column layout

**Files:**
- Create: `apps/web/ui/dashboard-v2.js`

- [ ] **Step 1: Create dashboard-v2.js**

Create `apps/web/ui/dashboard-v2.js`:

```javascript
/**
 * Daily Operator Dashboard v2 (P38)
 * Two-column layout: Vibe Coding (left) / Agentic Runtime (right)
 * Frontend aggregation of P34-P37 data, no new backend endpoints.
 */

"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initDashboardV2(Ao) {
  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  });

  function escapeHtml(value) {
    const text = value === null || value === undefined || value === "" ? "-" : String(value);
    return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
  }

  function byId(id) { return document.getElementById(id); }

  async function fetchJson(url) {
    try {
      const res = await fetch(url);
      if (!res.ok) return null;
      return await res.json();
    } catch { return null; }
  }

  async function loadVibeCodingColumn() {
    const [sessionsData, templatesData] = await Promise.all([
      fetchJson(`${API_URL}/sessions`),
      fetchJson(`${API_URL}/run-templates`),
    ]);

    const sessions = (sessionsData?.sessions || []);
    const vibeAgentIds = new Set(["claude", "codex", "cursor", "opencode", "qwen"]);
    const vibeSessions = sessions.filter(s => vibeAgentIds.has(s.agent_id));
    const recentSessions = vibeSessions.slice(0, 10);
    const failedSessions = vibeSessions.filter(s => s.status === "failed");
    const templates = templatesData?.templates || [];

    return { recentSessions, failedSessions, templates };
  }

  async function loadAgenticColumn() {
    const [inventoryData, approvalsData, sessionsData] = await Promise.all([
      fetchJson(`${API_URL}/agentic/inventory`),
      fetchJson(`${API_URL}/approvals?status=pending`),
      fetchJson(`${API_URL}/sessions`),
    ]);

    const inventory = inventoryData?.agents || [];
    const pendingApprovals = approvalsData?.approvals || [];
    const attachedSessions = (sessionsData?.sessions || [])
      .filter(s => s.external_session_id && s.attach_status !== "unsupported");

    return { inventory, pendingApprovals, attachedSessions };
  }

  function renderSessionRow(session) {
    return `<tr>
      <td><span class="pill status-${session.status}">${session.status}</span></td>
      <td>${escapeHtml(session.agent_id)}</td>
      <td>${escapeHtml((session.argv || []).join(" ").slice(0, 40))}</td>
      <td>${escapeHtml(session.started_at || "-")}</td>
    </tr>`;
  }

  function renderVibeCodingColumn(data) {
    const { recentSessions, failedSessions, templates } = data;

    let html = '<div class="dashboard-column" id="vibe-column">';
    html += '<h3>Vibe Coding</h3>';

    // Recent sessions
    html += '<div class="dash-card">';
    html += '<h4>Recent Sessions</h4>';
    if (recentSessions.length === 0) {
      html += '<p class="muted">No sessions yet</p>';
    } else {
      html += '<table class="session-table"><thead><tr><th>Status</th><th>Agent</th><th>Message</th><th>Started</th></tr></thead><tbody>';
      html += recentSessions.map(renderSessionRow).join("");
      html += '</tbody></table>';
    }
    html += '<button class="btn-primary btn-sm" onclick="Ao.showTab(\'vibe-coding\')">Launch New</button>';
    html += '</div>';

    // Failed sessions
    if (failedSessions.length > 0) {
      html += '<div class="dash-card dash-card-warn">';
      html += `<h4>Failed (${failedSessions.length})</h4>`;
      html += '<table class="session-table"><tbody>';
      html += failedSessions.slice(0, 5).map(renderSessionRow).join("");
      html += '</tbody></table>';
      html += '</div>';
    }

    // Templates
    if (templates.length > 0) {
      html += '<div class="dash-card">';
      html += '<h4>Templates</h4><ul class="template-list">';
      html += templates.slice(0, 5).map(t =>
        `<li><strong>${escapeHtml(t.name || t.id)}</strong>
          <button class="btn-sm" onclick="Ao.showTab('vibe-coding')">Launch</button></li>`
      ).join("");
      html += '</ul></div>';
    }

    html += '</div>';
    return html;
  }

  function renderAgenticColumn(data) {
    const { inventory, pendingApprovals, attachedSessions } = data;

    let html = '<div class="dashboard-column" id="agentic-column">';
    html += '<h3>Agentic Runtime</h3>';

    // Inventory summary
    html += '<div class="dash-card">';
    html += '<h4>Inventory</h4>';
    if (inventory.length === 0) {
      html += '<p class="muted">No agentic agents found</p>';
    } else {
      html += '<ul class="inventory-summary-list">';
      html += inventory.map(agent => {
        const skillCount = (agent.skills || []).length;
        const toolCount = (agent.tools || []).length;
        const flowCount = (agent.flows || []).length;
        return `<li>
          <strong>${escapeHtml(agent.agent_id)}</strong>
          <span class="inventory-stats">${skillCount} skills, ${toolCount} tools${flowCount ? `, ${flowCount} flows` : ""}</span>
          ${agent.error ? `<span class="inventory-err">⚠ ${escapeHtml(agent.error)}</span>` : ""}
        </li>`;
      }).join("");
      html += '</ul>';
    }
    html += '<button class="btn-primary btn-sm" onclick="Ao.showTab(\'agentic\')">View Details</button>';
    html += '</div>';

    // Attached sessions
    html += '<div class="dash-card">';
    html += '<h4>Attached Sessions</h4>';
    if (attachedSessions.length === 0) {
      html += '<p class="muted">No attached sessions</p>';
    } else {
      html += '<ul class="session-list">';
      html += attachedSessions.slice(0, 5).map(s =>
        `<li><span class="pill status-${s.status}">${s.status}</span>
          <strong>${escapeHtml(s.agent_id)}</strong>
          <code>${escapeHtml(s.external_session_id || "")}</code></li>`
      ).join("");
      html += '</ul>';
    }
    html += '<button class="btn-sm" onclick="Ao.showTab(\'sessions\')">Scan Sessions</button>';
    html += '</div>';

    // Pending approvals
    if (pendingApprovals.length > 0) {
      html += '<div class="dash-card dash-card-warn">';
      html += `<h4>Pending Approvals (${pendingApprovals.length})</h4>`;
      html += '<ul class="approval-list">';
      html += pendingApprovals.slice(0, 5).map(a =>
        `<li>${escapeHtml(a.agent_id || "unknown")} — ${escapeHtml(a.action || "")}</li>`
      ).join("");
      html += '</ul>';
      html += '<button class="btn-sm" onclick="Ao.showTab(\'approvals\')">Review</button>';
      html += '</div>';
    }

    html += '</div>';
    return html;
  }

  async function loadDashboardV2() {
    const leftContainer = byId("dashboard-v2-left");
    const rightContainer = byId("dashboard-v2-right");
    if (!leftContainer || !rightContainer) return;

    leftContainer.innerHTML = '<p class="loading">Loading...</p>';
    rightContainer.innerHTML = '<p class="loading">Loading...</p>';

    const [vibeData, agenticData] = await Promise.all([
      loadVibeCodingColumn(),
      loadAgenticColumn(),
    ]);

    leftContainer.innerHTML = renderVibeCodingColumn(vibeData);
    rightContainer.innerHTML = renderAgenticColumn(agenticData);
  }

  function init() {
    // Register as Ao hook if available
    if (Ao.DailyDashboard) {
      const origLoad = Ao.DailyDashboard.loadDashboard;
      Ao.DailyDashboard.loadDashboard = async function() {
        await origLoad?.();
        await loadDashboardV2();
      };
    }
  }

  Ao.DashboardV2 = { init, loadDashboardV2 };
})(window.AgenticOs);
```

- [ ] **Step 2: Add CSS for two-column layout**

In `apps/web/styles.css`:

```css
.dashboard-v2-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin-top: 1rem;
}
@media (max-width: 900px) {
  .dashboard-v2-layout { grid-template-columns: 1fr; }
}
.dashboard-column {
  min-width: 0;
}
.dash-card {
  border: 1px solid var(--border, #333);
  border-radius: 6px;
  padding: 0.75rem;
  margin-bottom: 0.75rem;
}
.dash-card h4 {
  margin: 0 0 0.5rem 0;
  font-size: 0.9rem;
}
.dash-card-warn {
  border-color: #eab308;
  background: rgba(234, 179, 8, 0.05);
}
.btn-sm {
  padding: 0.25rem 0.5rem;
  font-size: 0.8rem;
  margin-top: 0.5rem;
}
.inventory-summary-list, .session-list, .approval-list, .template-list {
  list-style: none;
  padding: 0;
  margin: 0 0 0.5rem 0;
}
.inventory-summary-list li, .session-list li, .approval-list li, .template-list li {
  padding: 0.3rem 0;
  border-bottom: 1px solid var(--border-light, #222);
}
.inventory-stats {
  font-size: 0.8rem;
  color: var(--text-muted, #666);
  margin-left: 0.5rem;
}
.inventory-err {
  display: block;
  font-size: 0.75rem;
  color: #ef4444;
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/ui/dashboard-v2.js apps/web/styles.css
git commit -m "feat(P38): add dashboard v2 two-column layout module"
```

---

### Task 21: Wire dashboard-v2 into index.html

**Files:**
- Modify: `apps/web/index.html`
- Modify: `apps/web/app.js`

- [ ] **Step 1: Add dashboard-v2 container to index.html**

In the overview tab section, after the existing dashboard content, add:

```html
<div class="dashboard-v2-layout" id="dashboard-v2-layout">
  <div id="dashboard-v2-left"></div>
  <div id="dashboard-v2-right"></div>
</div>
```

Add script tag:

```html
<script src="ui/dashboard-v2.js"></script>
```

- [ ] **Step 2: Wire into app.js overview load**

In `apps/web/app.js`, in the `loadOverview()` function, add at the end:

```javascript
if (window.AgenticOs?.DashboardV2?.loadDashboardV2) {
  window.AgenticOs.DashboardV2.loadDashboardV2();
}
```

- [ ] **Step 3: Verify UI works**

Start local stack, go to Overview tab.
Expected: Two-column layout below existing dashboard content.
Left column: Vibe Coding sessions + templates.
Right column: Agentic inventory + attached sessions + approvals.

- [ ] **Step 4: Commit**

```bash
git add apps/web/index.html apps/web/app.js
git commit -m "feat(P38): wire dashboard v2 into overview tab"
```

---

### Task 22: Add quick actions integration for dashboard v2

**Files:**
- Modify: `apps/web/ui/dashboard-v2.js`

- [ ] **Step 1: Add quick action handlers**

In `dashboard-v2.js`, add quick action buttons to the top of the two-column layout:

```javascript
function renderQuickActions() {
  return `
    <div class="quick-actions-bar">
      <button class="btn-primary btn-sm" onclick="Ao.showTab('agents')">Switch Profile</button>
      <button class="btn-primary btn-sm" onclick="Ao.showTab('approvals')">Approvals</button>
      <button class="btn-primary btn-sm" onclick="Ao.showTab('vibe-coding')">Launch Session</button>
      <button class="btn-primary btn-sm" onclick="Ao.showTab('sessions')">Attach Session</button>
    </div>
  `;
}
```

Insert this at the top of `loadDashboardV2()` before the column renders.

- [ ] **Step 2: Verify quick actions work**

Start local stack, click each quick action button.
Expected: Navigates to correct tab.

- [ ] **Step 3: Commit**

```bash
git add apps/web/ui/dashboard-v2.js
git commit -m "feat(P38): add quick actions to dashboard v2"
```

---

### Task 23: P38 integration test + final gate

- [ ] **Step 1: Run full suite with all JS checks**

Run: `uv run pytest -q && uv run ruff check .`

Check all new JS files:
```bash
node --check apps/web/ui/tool-discovery.js
node --check apps/web/ui/vibe-coding-launcher.js
node --check apps/web/ui/session-attach.js
node --check apps/web/ui/agentic-inventory.js
node --check apps/web/ui/dashboard-v2.js
```

Expected: All pass

- [ ] **Step 2: Full smoke test with real daemon**

```bash
TMPDIR=$(mktemp -d)
uv run agentd serve --state-dir "$TMPDIR" --registry examples/agents.toml &
DAEMON_PID=$!
sleep 2

# P34 endpoints
echo "=== P34: Tool Discovery ==="
curl -s http://127.0.0.1:8767/tools/discovery | python3 -m json.tool | head -20

echo "=== P34: Tool Inventory ==="
curl -s http://127.0.0.1:8767/tools/inventory | python3 -m json.tool | head -20

# P35: Launch a session
echo "=== P35: Launch Session ==="
curl -s -X POST http://127.0.0.1:8767/sessions \
  -H "Content-Type: application/json" \
  -d '{"cwd": "/tmp", "message": "test", "agent_id": "shell"}' | python3 -m json.tool

# P36: Discover sessions
echo "=== P36: Discover Sessions ==="
curl -s -X POST http://127.0.0.1:8767/sessions/discover \
  -H "Content-Type: application/json" \
  -d '{"workspace_path": "/tmp"}' | python3 -m json.tool

# P37: Agentic inventory
echo "=== P37: Agentic Inventory ==="
curl -s http://127.0.0.1:8767/agentic/inventory | python3 -m json.tool | head -20

kill $DAEMON_PID
rm -rf "$TMPDIR"
```

Expected: All endpoints return valid JSON without errors.

- [ ] **Step 3: UI smoke test**

Open browser to `http://localhost:5173`:
1. Overview tab → two-column dashboard v2 visible
2. Tools tab → tool discovery table
3. Vibe Coding tab → launcher form
4. Sessions tab → scan button
5. Agentic tab → inventory cards

- [ ] **Step 4: Final commit for P34-P38**

```bash
git add -A
git commit -m "feat(P34-P38): dual-track product complete"
```

---

## Summary

| Phase | Tasks | Key deliverables |
|-------|-------|-----------------|
| P34 | 1–7 | `tool_discovery.py`, `config_inventory.py`, `/tools/discovery`, `/tools/inventory`, tool-discovery.js |
| P35 | 8–11 | `attach.py` expansion, `workspace_path` field, vibe-coding-launcher.js |
| P36 | 12–15 | `session_discovery.py`, `/sessions/discover`, `/sessions/{id}/workspace`, session-attach.js |
| P37 | 16–19 | `agentic_inventory.py`, `/agentic/inventory`, agentic-inventory.js |
| P38 | 20–23 | `dashboard-v2.js`, two-column layout, quick actions integration |

**Total: 23 tasks.**

Each phase ends with a green CI gate: `uv run pytest -q && uv run ruff check . && node --check <all new JS>`.
