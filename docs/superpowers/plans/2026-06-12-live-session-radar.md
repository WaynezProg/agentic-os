# P39 Live Session Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the user's real Claude Code / Codex sessions (written by the actual tools into `~/.claude/projects` and `~/.codex/sessions`) in the dashboard with resume actions, flipping the product from launch-first to observe-first.

**Architecture:** New read-only scanner module `live_sessions.py` (bounded 64KB head reads, mtime pruning) → `GET /sessions/live` endpoint (roots injectable for tests) → CLI `agentctl sessions live` → dashboard-v2 "Live Sessions" card with copy-resume + open-in-Terminal (macOS osascript, server-side command construction only).

**Tech Stack:** Python 3.12 / FastAPI / Typer (existing), static no-build JS UI, pytest.

**Spec:** `docs/superpowers/specs/2026-06-12-live-session-radar-design.md`

---

## File map

- Create: `src/agentic_os/live_sessions.py` — scanners + LiveSession dataclass + open-terminal command builder
- Create: `tests/test_live_sessions.py` — unit tests with fixture JSONL
- Modify: `src/agentic_os/api.py` — `create_app(..., live_session_roots=None)`, `GET /sessions/live` (register BEFORE `GET /sessions/{session_id}` at ~line 872), `POST /sessions/live/open-terminal`
- Modify: `tests/test_api.py` — endpoint tests
- Modify: `src/agentic_os/client.py` — `list_live_sessions()`
- Modify: `src/agentic_os/cli.py` — `agentctl sessions live`
- Modify: `tests/test_cli.py` — FakeClient method + test
- Modify: `apps/web/api.js` — `liveSessions`, `liveOpenTerminal` endpoints
- Modify: `apps/web/ui/dashboard-v2.js` — Live Sessions card, rename own-DB card to "Managed Runs"
- Modify: `apps/web/styles.css` — dots/badges
- Modify: `tests/test_web.py` — marker assertions
- Create: `specs/059-live-session-radar.md`; Modify: `README.md`, `CLAUDE.md`

---

### Task 1: `live_sessions.py` scanners (TDD)

**Files:** Create `src/agentic_os/live_sessions.py`, `tests/test_live_sessions.py`

- [ ] **Step 1.1: Write failing tests**

```python
"""Tests for the P39 live session radar scanners."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentic_os.live_sessions import (
    LiveSession,
    build_open_terminal_command,
    scan_claude_sessions,
    scan_codex_sessions,
    scan_live_sessions,
)

NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)


def _touch(path: Path, *, hours_ago: float) -> None:
    ts = NOW.timestamp() - hours_ago * 3600
    os.utime(path, (ts, ts))


def _write_claude_session(
    root: Path,
    *,
    project: str = "-Users-w-proj",
    session_id: str = "abc-123",
    cwd: str | None = "/Users/w/proj",
    title: str = "fix the bug",
    hours_ago: float = 0.01,
    extra_lines: list[str] | None = None,
) -> Path:
    project_dir = root / project
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{session_id}.jsonl"
    user_obj: dict[str, object] = {
        "type": "user",
        "sessionId": session_id,
        "timestamp": "2026-06-12T10:00:00Z",
        "message": {"role": "user", "content": title},
    }
    if cwd is not None:
        user_obj["cwd"] = cwd
    lines = [json.dumps(user_obj)]
    if extra_lines:
        lines = extra_lines + lines
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _touch(path, hours_ago=hours_ago)
    return path


def _write_codex_session(
    root: Path,
    *,
    session_id: str = "019e-codex-1",
    cwd: str = "/Users/w/proj",
    title: str = "refactor pipeline",
    hours_ago: float = 0.01,
) -> Path:
    day_dir = root / "2026" / "06" / "12"
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"rollout-2026-06-12T10-00-00-{session_id}.jsonl"
    lines = [
        json.dumps(
            {
                "timestamp": "2026-06-12T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "timestamp": "2026-06-12T10:00:00Z",
                    "cwd": cwd,
                    "originator": "Codex Desktop",
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-06-12T10:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "<user_instructions>blob</user_instructions>"}],
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-06-12T10:00:02Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": title},
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _touch(path, hours_ago=hours_ago)
    return path


def test_scan_claude_basic(tmp_path: Path) -> None:
    _write_claude_session(tmp_path, hours_ago=0.01)
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.tool == "claude"
    assert s.session_id == "abc-123"
    assert s.workspace == "/Users/w/proj"
    assert s.title == "fix the bug"
    assert s.active is True
    assert s.resume_command == "cd /Users/w/proj && claude --resume abc-123"


def test_scan_claude_old_file_skipped(tmp_path: Path) -> None:
    _write_claude_session(tmp_path, hours_ago=100)
    assert scan_claude_sessions(tmp_path, within_hours=72, now=NOW) == []


def test_scan_claude_idle_not_active(tmp_path: Path) -> None:
    _write_claude_session(tmp_path, hours_ago=1)
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert sessions[0].active is False


def test_scan_claude_workspace_fallback_to_dir_name(tmp_path: Path) -> None:
    _write_claude_session(tmp_path, project="-Users-w-other", cwd=None)
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert sessions[0].workspace == "/Users/w/other"


def test_claude_title_prefers_summary(tmp_path: Path) -> None:
    summary = json.dumps({"type": "summary", "summary": "Radar design session"})
    _write_claude_session(tmp_path, extra_lines=[summary])
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert sessions[0].title == "Radar design session"


def test_claude_title_skips_command_and_caveat_messages(tmp_path: Path) -> None:
    project_dir = tmp_path / "-Users-w-proj"
    project_dir.mkdir(parents=True)
    path = project_dir / "xyz-1.jsonl"
    lines = [
        json.dumps(
            {
                "type": "user",
                "sessionId": "xyz-1",
                "cwd": "/Users/w/proj",
                "message": {"role": "user", "content": "<command-name>/foo</command-name>"},
            }
        ),
        json.dumps(
            {
                "type": "user",
                "sessionId": "xyz-1",
                "message": {"role": "user", "content": [{"type": "text", "text": "real prompt"}]},
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _touch(path, hours_ago=0.01)
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert sessions[0].title == "real prompt"


def test_scan_claude_skips_agent_sidechain_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "-Users-w-proj"
    project_dir.mkdir(parents=True)
    path = project_dir / "agent-123.jsonl"
    path.write_text(
        json.dumps({"type": "user", "sessionId": "agent-123", "cwd": "/Users/w/proj"}) + "\n",
        encoding="utf-8",
    )
    _touch(path, hours_ago=0.01)
    assert scan_claude_sessions(tmp_path, within_hours=72, now=NOW) == []


def test_scan_claude_garbage_does_not_crash(tmp_path: Path) -> None:
    project_dir = tmp_path / "-Users-w-proj"
    project_dir.mkdir(parents=True)
    bad = project_dir / "bad-1.jsonl"
    bad.write_bytes(b"\xff\xfenot json\n{broken\n")
    _touch(bad, hours_ago=0.01)
    assert scan_claude_sessions(tmp_path, within_hours=72, now=NOW) == []


def test_scan_claude_reads_only_head_of_huge_file(tmp_path: Path) -> None:
    path = _write_claude_session(tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        junk = json.dumps({"type": "assistant", "noise": "x" * 1000})
        for _ in range(5000):
            fh.write(junk + "\n")
    _touch(path, hours_ago=0.01)
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert sessions[0].session_id == "abc-123"


def test_scan_codex_basic(tmp_path: Path) -> None:
    _write_codex_session(tmp_path)
    sessions = scan_codex_sessions(tmp_path, within_hours=72, now=NOW)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.tool == "codex"
    assert s.session_id == "019e-codex-1"
    assert s.workspace == "/Users/w/proj"
    assert s.title == "refactor pipeline"
    assert s.source == "Codex Desktop"
    assert s.resume_command == "cd /Users/w/proj && codex resume 019e-codex-1"


def test_scan_codex_old_pruned(tmp_path: Path) -> None:
    _write_codex_session(tmp_path, hours_ago=100)
    assert scan_codex_sessions(tmp_path, within_hours=72, now=NOW) == []


def test_resume_command_quotes_workspace_with_spaces(tmp_path: Path) -> None:
    _write_claude_session(tmp_path, cwd="/Users/w/my proj")
    sessions = scan_claude_sessions(tmp_path, within_hours=72, now=NOW)
    assert "'/Users/w/my proj'" in sessions[0].resume_command


def test_scan_live_sessions_merges_sorts_limits(tmp_path: Path) -> None:
    claude_root = tmp_path / "claude"
    codex_root = tmp_path / "codex"
    _write_claude_session(claude_root, hours_ago=2)
    _write_codex_session(codex_root, hours_ago=1)
    sessions, errors = scan_live_sessions(
        {"claude": claude_root, "codex": codex_root}, within_hours=72, limit=1, now=NOW
    )
    assert errors == []
    assert len(sessions) == 1
    assert sessions[0].tool == "codex"  # newer first


def test_scan_live_sessions_missing_roots_ok(tmp_path: Path) -> None:
    sessions, errors = scan_live_sessions(
        {"claude": tmp_path / "nope", "codex": tmp_path / "nope2"},
        within_hours=72,
        now=NOW,
    )
    assert sessions == []
    assert errors == []


def test_build_open_terminal_command_valid(tmp_path: Path) -> None:
    argv = build_open_terminal_command("claude", "abc-123", str(tmp_path))
    assert argv[0] == "osascript"
    script = argv[2]
    assert "claude --resume abc-123" in script
    assert str(tmp_path) in script


def test_build_open_terminal_rejects_bad_tool(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_open_terminal_command("rm-rf", "abc-123", str(tmp_path))


def test_build_open_terminal_rejects_bad_session_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_open_terminal_command("claude", 'abc"; rm -rf /', str(tmp_path))


def test_build_open_terminal_rejects_missing_workspace(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_open_terminal_command("claude", "abc-123", str(tmp_path / "missing"))
```

- [ ] **Step 1.2: Run tests, verify they fail** — `uv run pytest tests/test_live_sessions.py -q` → ImportError (module missing)

- [ ] **Step 1.3: Implement `src/agentic_os/live_sessions.py`**

```python
"""Read-only scanners over real vibe coding session stores (P39).

Observes session files written by external tools (Claude Code, Codex)
without launching, modifying, or attaching to them. All file IO is
bounded: stat-based mtime pruning before open, 64KB head reads only.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_HEAD_BYTES = 65536
_ACTIVE_WINDOW_SECONDS = 300
_TITLE_MAX_CHARS = 120

_CLAUDE_DEFAULT_ROOT = "~/.claude/projects"
_CODEX_DEFAULT_ROOT = "~/.codex/sessions"

_RESUME_ARGV = {
    "claude": ("claude", "--resume"),
    "codex": ("codex", "resume"),
}
_SESSION_ID_RE = re.compile(r"^[0-9A-Za-z._-]{4,128}$")
_SKIP_TITLE_PREFIXES = ("<", "Caveat:")


@dataclass(frozen=True)
class LiveSession:
    tool: str
    session_id: str
    workspace: str
    title: str
    started_at: str | None
    last_activity_at: str
    active: bool
    source: str | None
    log_path: str
    resume_command: str


def live_session_dict(session: LiveSession) -> dict[str, object]:
    return asdict(session)


def default_roots() -> dict[str, Path]:
    return {
        "claude": Path(_CLAUDE_DEFAULT_ROOT).expanduser(),
        "codex": Path(_CODEX_DEFAULT_ROOT).expanduser(),
    }


def _now_ts(now: datetime | None) -> float:
    return (now or datetime.now(tz=timezone.utc)).timestamp()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _read_head_lines(path: Path) -> list[str]:
    try:
        with path.open("rb") as fh:
            head = fh.read(_HEAD_BYTES)
    except OSError:
        return []
    lines = head.decode("utf-8", errors="replace").splitlines()
    if len(head) == _HEAD_BYTES and lines:
        lines.pop()  # drop line truncated by the read budget
    return lines


def _iter_json_objects(lines: list[str]) -> Iterator[dict[str, object]]:
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield payload


def _truncate(text: str) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= _TITLE_MAX_CHARS:
        return cleaned
    return cleaned[: _TITLE_MAX_CHARS - 1] + "…"


def _is_real_prompt(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return not stripped.startswith(_SKIP_TITLE_PREFIXES)


def _resume_command(tool: str, workspace: str, session_id: str) -> str:
    binary, verb = _RESUME_ARGV[tool]
    return f"cd {shlex.quote(workspace)} && {binary} {verb} {shlex.quote(session_id)}"


def _first_str(objs: list[dict[str, object]], key: str) -> str | None:
    for obj in objs:
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
    return None


# --- Claude Code (~/.claude/projects/<encoded-cwd>/<session>.jsonl) ---


def _decode_claude_project_dir(name: str) -> str:
    # Dir name encodes cwd with "/" replaced by "-"; lossy for dashed
    # paths, so only used when no cwd key is present in the JSONL head.
    if not name.startswith("-"):
        return name
    return "/" + name[1:].replace("-", "/")


def _claude_title(objs: list[dict[str, object]]) -> str:
    for obj in objs:
        summary = obj.get("summary")
        if obj.get("type") == "summary" and isinstance(summary, str) and summary.strip():
            return _truncate(summary)
    for obj in objs:
        content = obj.get("content")
        if (
            obj.get("type") == "queue-operation"
            and isinstance(content, str)
            and _is_real_prompt(content)
        ):
            return _truncate(content)
    for obj in objs:
        if obj.get("type") != "user":
            continue
        message = obj.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str) and _is_real_prompt(content):
            return _truncate(content)
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "text":
                    continue
                text = part.get("text")
                if isinstance(text, str) and _is_real_prompt(text):
                    return _truncate(text)
    return "(untitled)"


def scan_claude_sessions(
    root: Path,
    *,
    within_hours: int = 72,
    now: datetime | None = None,
) -> list[LiveSession]:
    now_ts = _now_ts(now)
    cutoff = now_ts - within_hours * 3600
    results: list[LiveSession] = []
    if not root.is_dir():
        return results
    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        for jsonl in project_dir.glob("*.jsonl"):
            if jsonl.name.startswith("agent-"):
                continue  # subagent sidechain transcripts, not resumable sessions
            try:
                stat = jsonl.stat()
            except OSError:
                continue
            if stat.st_mtime < cutoff:
                continue
            objs = list(_iter_json_objects(_read_head_lines(jsonl)))
            if not objs:
                continue
            session_id = _first_str(objs, "sessionId") or jsonl.stem
            workspace = _first_str(objs, "cwd") or _decode_claude_project_dir(project_dir.name)
            results.append(
                LiveSession(
                    tool="claude",
                    session_id=session_id,
                    workspace=workspace,
                    title=_claude_title(objs),
                    started_at=_first_str(objs, "timestamp"),
                    last_activity_at=_iso(stat.st_mtime),
                    active=(now_ts - stat.st_mtime) < _ACTIVE_WINDOW_SECONDS,
                    source=None,
                    log_path=str(jsonl),
                    resume_command=_resume_command("claude", workspace, session_id),
                )
            )
    return results


# --- Codex (~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl) ---


def _codex_title(objs: list[dict[str, object]]) -> str:
    for obj in objs:
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue
        if obj.get("type") == "event_msg" and payload.get("type") == "user_message":
            message = payload.get("message")
            if isinstance(message, str) and _is_real_prompt(message):
                return _truncate(message)
        if (
            obj.get("type") == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") == "user"
        ):
            content = payload.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text = part.get("text")
                    if isinstance(text, str) and _is_real_prompt(text):
                        return _truncate(text)
    return "(untitled)"


def scan_codex_sessions(
    root: Path,
    *,
    within_hours: int = 72,
    now: datetime | None = None,
) -> list[LiveSession]:
    now_ts = _now_ts(now)
    cutoff = now_ts - within_hours * 3600
    results: list[LiveSession] = []
    if not root.is_dir():
        return results
    for jsonl in root.glob("*/*/*/rollout-*.jsonl"):
        try:
            stat = jsonl.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff:
            continue
        objs = list(_iter_json_objects(_read_head_lines(jsonl)))
        meta: dict[str, object] | None = None
        for obj in objs:
            payload = obj.get("payload")
            if obj.get("type") == "session_meta" and isinstance(payload, dict):
                meta = payload
                break
        if meta is None:
            continue
        session_id = meta.get("id") if isinstance(meta.get("id"), str) else jsonl.stem
        workspace = meta.get("cwd") if isinstance(meta.get("cwd"), str) else "?"
        source = None
        for key in ("originator", "source"):
            value = meta.get(key)
            if isinstance(value, str) and value:
                source = value
                break
        started_at = meta.get("timestamp") if isinstance(meta.get("timestamp"), str) else None
        results.append(
            LiveSession(
                tool="codex",
                session_id=str(session_id),
                workspace=str(workspace),
                title=_codex_title(objs),
                started_at=started_at,
                last_activity_at=_iso(stat.st_mtime),
                active=(now_ts - stat.st_mtime) < _ACTIVE_WINDOW_SECONDS,
                source=source,
                log_path=str(jsonl),
                resume_command=_resume_command("codex", str(workspace), str(session_id)),
            )
        )
    return results


# --- Aggregate ---

_SCANNERS = {
    "claude": scan_claude_sessions,
    "codex": scan_codex_sessions,
}


def scan_live_sessions(
    roots: dict[str, Path] | None = None,
    *,
    within_hours: int = 72,
    limit: int = 50,
    now: datetime | None = None,
) -> tuple[list[LiveSession], list[dict[str, str]]]:
    resolved = default_roots()
    if roots:
        resolved.update(roots)
    sessions: list[LiveSession] = []
    errors: list[dict[str, str]] = []
    for tool, scanner in _SCANNERS.items():
        root = resolved.get(tool)
        if root is None:
            continue
        try:
            sessions.extend(scanner(root, within_hours=within_hours, now=now))
        except Exception as exc:  # one bad store must not break the radar
            errors.append({"tool": tool, "error": str(exc)})
    sessions.sort(key=lambda s: s.last_activity_at, reverse=True)
    return sessions[:limit], errors


# --- Open-in-Terminal (macOS) ---


def _applescript_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def build_open_terminal_command(tool: str, session_id: str, workspace: str) -> list[str]:
    """Validate inputs and build the osascript argv.

    The shell command is reconstructed server-side from whitelisted
    parts; callers never supply a raw command string.
    """
    if tool not in _RESUME_ARGV:
        raise ValueError(f"unsupported tool: {tool}")
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError("invalid session_id")
    ws = Path(workspace).expanduser()
    if not ws.is_dir():
        raise ValueError(f"workspace does not exist: {workspace}")
    shell_cmd = _resume_command(tool, str(ws), session_id)
    script = (
        'tell application "Terminal"\n'
        "  activate\n"
        f'  do script "{_applescript_escape(shell_cmd)}"\n'
        "end tell"
    )
    return ["osascript", "-e", script]


def open_terminal(tool: str, session_id: str, workspace: str) -> None:
    """Open Terminal.app at the workspace running the resume command.

    Raises ValueError for invalid input, RuntimeError when osascript fails.
    """
    argv = build_open_terminal_command(tool, session_id, workspace)
    completed = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "osascript failed")
```

- [ ] **Step 1.4: Run tests** — `uv run pytest tests/test_live_sessions.py -q` → all PASS
- [ ] **Step 1.5: Lint + commit**

```bash
uv run ruff check src/agentic_os/live_sessions.py tests/test_live_sessions.py
git add src/agentic_os/live_sessions.py tests/test_live_sessions.py
git commit -m "feat(P39): live_sessions read-only scanners for claude/codex session stores"
```

### Task 2: `GET /sessions/live` + `POST /sessions/live/open-terminal` API

**Files:** Modify `src/agentic_os/api.py`, `tests/test_api.py`

- [ ] **Step 2.1: Write failing tests** (append to `tests/test_api.py`; reuse `_write_claude_session`-style fixture inline)

```python
def _make_live_client(tmp_path: Path) -> TestClient:
    registry = tmp_path / "agents.toml"
    write_registry(registry)
    claude_root = tmp_path / "claude-projects"
    codex_root = tmp_path / "codex-sessions"
    project_dir = claude_root / "-Users-w-proj"
    project_dir.mkdir(parents=True)
    (project_dir / "abc-123.jsonl").write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": "abc-123",
                "cwd": "/Users/w/proj",
                "timestamp": "2026-06-12T10:00:00Z",
                "message": {"role": "user", "content": "fix the bug"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return TestClient(
        create_app(
            state_dir=tmp_path / ".agentic-os",
            registry_path=registry,
            live_session_roots={"claude": claude_root, "codex": codex_root},
        )
    )


def test_live_sessions_endpoint(tmp_path: Path) -> None:
    client = _make_live_client(tmp_path)
    response = client.get("/sessions/live")
    assert response.status_code == 200
    body = response.json()
    assert body["errors"] == []
    assert len(body["sessions"]) == 1
    session = body["sessions"][0]
    assert session["tool"] == "claude"
    assert session["session_id"] == "abc-123"
    assert session["resume_command"].endswith("claude --resume abc-123")
    assert "generated_at" in body


def test_live_sessions_endpoint_clamps_params(tmp_path: Path) -> None:
    client = _make_live_client(tmp_path)
    response = client.get("/sessions/live", params={"within_hours": 999999, "limit": 0})
    assert response.status_code == 200


def test_live_open_terminal_rejects_bad_tool(tmp_path: Path) -> None:
    client = _make_live_client(tmp_path)
    response = client.post(
        "/sessions/live/open-terminal",
        json={"tool": "rm-rf", "session_id": "abc-123", "workspace": str(tmp_path)},
    )
    assert response.status_code == 400


def test_live_open_terminal_runs_osascript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_live_client(tmp_path)
    calls: list[list[str]] = []

    class FakeCompleted:
        returncode = 0
        stderr = ""

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return FakeCompleted()

    monkeypatch.setattr("agentic_os.live_sessions.subprocess.run", fake_run)
    monkeypatch.setattr("agentic_os.api.sys.platform", "darwin", raising=False)
    response = client.post(
        "/sessions/live/open-terminal",
        json={"tool": "claude", "session_id": "abc-123", "workspace": str(tmp_path)},
    )
    assert response.status_code == 200
    assert calls and calls[0][0] == "osascript"
```

Note: if `monkeypatch.setattr("agentic_os.api.sys.platform", ...)` proves awkward (sys is a shared module), gate the endpoint on a module-level `_PLATFORM = sys.platform` in `api.py` and patch `agentic_os.api._PLATFORM` instead.

- [ ] **Step 2.2: Run, verify failure** — `uv run pytest tests/test_api.py -k live -q` → TypeError (unexpected kwarg) / 404
- [ ] **Step 2.3: Implement in `api.py`**
  - Imports: `from agentic_os.live_sessions import live_session_dict, open_terminal, scan_live_sessions` (top of file, near other module imports).
  - Signature: `def create_app(state_dir: Path, registry_path: Path, live_session_roots: dict[str, Path] | None = None) -> FastAPI:`
  - Request model (top of file with other Pydantic models):

```python
class LiveOpenTerminalRequest(BaseModel):
    tool: str
    session_id: str
    workspace: str
```

  - Routes — register **immediately after `@app.get("/sessions")` and before `@app.get("/sessions/{session_id}")`** (route order matters: `live` must not be captured as a `session_id`):

```python
    @app.get("/sessions/live")
    def list_live_sessions(within_hours: int = 72, limit: int = 50) -> dict[str, object]:
        """Scan real external session stores (P39). Read-only."""
        within_hours = max(1, min(within_hours, 720))
        limit = max(1, min(limit, 200))
        live, errors = scan_live_sessions(
            live_session_roots, within_hours=within_hours, limit=limit
        )
        return {
            "sessions": [live_session_dict(s) for s in live],
            "errors": errors,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    @app.post("/sessions/live/open-terminal")
    def live_open_terminal(payload: LiveOpenTerminalRequest) -> dict[str, object]:
        """Open Terminal.app resuming a discovered session (P39, macOS only)."""
        if sys.platform != "darwin":
            raise HTTPException(status_code=501, detail="open-terminal is macOS-only")
        try:
            open_terminal(payload.tool, payload.session_id, payload.workspace)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"ok": True, "tool": payload.tool, "session_id": payload.session_id}
```

  Check existing imports in `api.py` for `datetime`/`timezone`/`sys`/`subprocess`; add only what's missing.
- [ ] **Step 2.4: Run** — `uv run pytest tests/test_api.py -k live -q` → PASS; then `uv run pytest tests/test_api.py -q` (no regressions)
- [ ] **Step 2.5: Commit** — `git commit -m "feat(P39): GET /sessions/live + open-terminal endpoints"`

### Task 3: client + CLI

**Files:** Modify `src/agentic_os/client.py`, `src/agentic_os/cli.py`, `tests/test_cli.py`

- [ ] **Step 3.1: Failing CLI test** (append to `tests/test_cli.py`; add FakeClient method alongside its peers)

```python
    def list_live_sessions(self, within_hours: int = 72, limit: int = 50) -> dict[str, object]:
        self.calls.append(("list_live_sessions", (), {"within_hours": within_hours, "limit": limit}))
        return {
            "sessions": [
                {
                    "tool": "claude",
                    "session_id": "abc-123",
                    "workspace": "/Users/w/proj",
                    "title": "fix the bug",
                    "last_activity_at": "2026-06-12T10:00:00+00:00",
                    "active": True,
                    "resume_command": "cd /Users/w/proj && claude --resume abc-123",
                }
            ],
            "errors": [],
        }
```

Test (follow the file's existing fake-client test style):

```python
def test_sessions_live_lists_external_sessions(runner_with_fake_client) -> None:
    runner, fake = runner_with_fake_client
    result = runner.invoke(cli.app, ["sessions", "live"])
    assert result.exit_code == 0
    assert "claude" in result.output
    assert "abc-123" in result.output
    assert ("list_live_sessions", (), {"within_hours": 72, "limit": 50}) in fake.calls
```

(Adapt fixture name to whatever `tests/test_cli.py` actually uses to inject FakeClient — mirror the nearest existing sessions test.)

- [ ] **Step 3.2: Verify failure**, then implement.

`client.py` (after `list_sessions`):

```python
    def list_live_sessions(self, within_hours: int = 72, limit: int = 50) -> dict[str, Any]:
        return self._get(
            "/sessions/live", params={"within_hours": within_hours, "limit": limit}
        )
```

`cli.py` (after `sessions_list`):

```python
@sessions.command("live")
def sessions_live(
    within_hours: int = typer.Option(72, "--within-hours", help="Scan window in hours."),
    limit: int = typer.Option(50, "--limit", help="Maximum sessions returned."),
    api: str | None = _api_option(),
) -> None:
    """List real external tool sessions discovered on this machine (P39)."""
    data = _run_api_call(
        lambda: make_client(api).list_live_sessions(within_hours=within_hours, limit=limit)
    )
    for session in data.get("sessions", []):
        marker = "ACTIVE" if session.get("active") else "idle"
        typer.echo(
            f"{marker}\t{session['tool']}\t{session['workspace']}\t"
            f"{session.get('title', '')}\t{session['last_activity_at']}\t{session['session_id']}"
        )
```

- [ ] **Step 3.3: Run** — `uv run pytest tests/test_cli.py -k live -q` → PASS
- [ ] **Step 3.4: Commit** — `git commit -m "feat(P39): agentctl sessions live CLI + client method"`

### Task 4: UI — dashboard-v2 Live Sessions card

**Files:** Modify `apps/web/api.js`, `apps/web/ui/dashboard-v2.js`, `apps/web/styles.css`, `tests/test_web.py`

- [ ] **Step 4.1: Failing web test** (append to `tests/test_web.py`, define `DASHBOARD_V2_JS = WEB_DIR / "ui" / "dashboard-v2.js"` near the other constants if absent)

```python
def test_live_session_radar_wired() -> None:
    api_js = API_JS.read_text(encoding="utf-8")
    assert 'liveSessions: "/sessions/live"' in api_js
    assert 'liveOpenTerminal: "/sessions/live/open-terminal"' in api_js
    dashboard = (WEB_DIR / "ui" / "dashboard-v2.js").read_text(encoding="utf-8")
    assert "loadLiveSessions" in dashboard
    assert "data-resume-command" in dashboard
    assert "Managed Runs" in dashboard
    styles = STYLES_CSS.read_text(encoding="utf-8")
    assert ".live-dot-active" in styles
    assert ".tool-badge" in styles
```

- [ ] **Step 4.2: Implement.** `api.js` ENDPOINTS additions (keep alphabetical-ish grouping near `sessions`):

```javascript
    liveSessions: "/sessions/live",
    liveOpenTerminal: "/sessions/live/open-terminal",
```

`dashboard-v2.js` — add functions and wire into the left column:

```javascript
  async function loadLiveSessions() {
    const data = await fetchJson(`${Ao.buildEndpoint("liveSessions")}?within_hours=24&limit=20`);
    return { sessions: data?.sessions || [], errors: data?.errors || [] };
  }

  function relativeTime(iso) {
    const then = Date.parse(iso);
    if (Number.isNaN(then)) return iso || "-";
    const minutes = Math.round((Date.now() - then) / 60000);
    if (minutes < 1) return "now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.round(hours / 24)}d ago`;
  }

  function renderLiveSessionRow(session) {
    const wsParts = String(session.workspace || "").split("/").filter(Boolean);
    const wsName = wsParts.length ? wsParts[wsParts.length - 1] : session.workspace;
    return `<tr>
      <td><span class="live-dot ${session.active ? "live-dot-active" : "live-dot-idle"}"></span></td>
      <td><span class="tool-badge tool-badge-${escapeHtml(session.tool)}">${escapeHtml(session.tool)}</span></td>
      <td title="${escapeHtml(session.workspace)}">${escapeHtml(wsName)}</td>
      <td class="live-title" title="${escapeHtml(session.title)}">${escapeHtml(session.title)}</td>
      <td>${escapeHtml(relativeTime(session.last_activity_at))}</td>
      <td>
        <button type="button" class="btn-sm" data-resume-command="${escapeHtml(session.resume_command)}">Copy resume</button>
        <button type="button" class="btn-sm" data-open-terminal data-tool="${escapeHtml(session.tool)}"
          data-session-id="${escapeHtml(session.session_id)}" data-workspace="${escapeHtml(session.workspace)}">Terminal</button>
      </td>
    </tr>`;
  }

  function renderLiveSessionsCard(live) {
    const activeCount = live.sessions.filter((s) => s.active).length;
    let html = '<div class="dash-card" id="live-sessions-card">';
    html += `<h4>Live Sessions <span class="muted">(real · ${activeCount} active)</span>
      <button type="button" class="btn-sm" id="live-sessions-refresh">↻</button></h4>`;
    if (live.sessions.length === 0) {
      html += '<p class="muted">No claude/codex sessions in the last 24h.</p>';
    } else {
      html += '<table class="session-table"><tbody>';
      html += live.sessions.map(renderLiveSessionRow).join("");
      html += "</tbody></table>";
    }
    html += "</div>";
    return html;
  }

  function bindLiveSessionActions(container) {
    container.querySelectorAll("[data-resume-command]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(button.dataset.resumeCommand);
          button.textContent = "Copied ✓";
          setTimeout(() => { button.textContent = "Copy resume"; }, 1500);
        } catch {
          window.prompt("Copy resume command:", button.dataset.resumeCommand);
        }
      });
    });
    container.querySelectorAll("[data-open-terminal]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await Ao.apiFetch(Ao.buildEndpoint("liveOpenTerminal"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              tool: button.dataset.tool,
              session_id: button.dataset.sessionId,
              workspace: button.dataset.workspace,
            }),
          });
          button.textContent = "Opened ✓";
        } catch (error) {
          button.textContent = "Failed";
          console.error("open-terminal failed", error);
        }
        setTimeout(() => { button.textContent = "Terminal"; }, 1500);
      });
    });
    const refresh = container.querySelector("#live-sessions-refresh");
    if (refresh) refresh.addEventListener("click", () => loadDashboardV2());
  }
```

In `renderVibeCodingColumn`, accept and render the live card first; rename own-DB card heading `Recent Sessions` → `Managed Runs`; in `loadDashboardV2`, fetch live data in the same `Promise.all` and call `bindLiveSessionActions(leftContainer)` after `innerHTML` assignment. (Check `Ao.apiFetch` signature in `api.js` for POST usage — mirror how other modules POST, e.g. `vibe-coding-launcher.js`.)

`styles.css` additions:

```css
.live-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
.live-dot-active { background: #22c55e; box-shadow: 0 0 4px #22c55e; }
.live-dot-idle { background: #94a3b8; }
.tool-badge { padding: 1px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.tool-badge-claude { background: rgba(124, 58, 237, 0.16); color: #a78bfa; }
.tool-badge-codex { background: rgba(14, 165, 233, 0.16); color: #38bdf8; }
.live-title { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
```

- [ ] **Step 4.3: Run** — `uv run pytest tests/test_web.py -q` → PASS
- [ ] **Step 4.4: Commit** — `git commit -m "feat(P39): live session radar card in dashboard-v2"`

### Task 5: Docs + spec

**Files:** Create `specs/059-live-session-radar.md`; Modify `README.md`, `CLAUDE.md`; commit pending `AGENTS.md`/`CLAUDE.md` working-tree changes.

- [ ] **Step 5.1:** Write `specs/059-live-session-radar.md`: owns (read-only scanners over `~/.claude/projects` + `~/.codex/sessions`, `GET /sessions/live`, open-terminal action, dashboard card); does not own (writing to external stores, gemini/qwen/opencode scanners, file watching, cross-machine). Include API contract and bounded-IO requirements from the design doc.
- [ ] **Step 5.2:** `CLAUDE.md` dual-track table: add P39 row. Module map: add `live_sessions.py` line. `README.md`: add P39 row/paragraph near P34–P38 wording (do NOT touch P0–P33 table wording — `test_web.py` asserts it).
- [ ] **Step 5.3:** Run `uv run pytest tests/test_web.py -q` (README wording assertions), commit docs together with the already-modified `AGENTS.md`/`CLAUDE.md`: `git commit -m "docs(P39): live session radar spec + dual-track docs refresh"`

### Task 6: Full verification

- [ ] **Step 6.1:** `uv run pytest -q` → all pass (~700+)
- [ ] **Step 6.2:** `uv run ruff check .` → clean; `uv run ruff format --check .` if used by repo
- [ ] **Step 6.3: Live verification against real data:**

```bash
uv run agentd serve --state-dir /tmp/p39-verify --registry examples/agents.toml &
sleep 2
curl -s "http://127.0.0.1:8767/sessions/live?within_hours=24" | python3 -m json.tool | head -50
# Expect: today's real claude/codex sessions, including this very session.
kill %1
```

- [ ] **Step 6.4:** Open the web UI, confirm the 總覽 tab renders the Live Sessions card with real rows; copy-resume puts a valid command on the clipboard.

### Task 7: Ship

- [ ] **Step 7.1:** `git push -u origin feat/p34-p38-dual-track-product`
- [ ] **Step 7.2:** `gh pr create` → base `main`, title covering P34–P39 dual-track + radar, body summarizing diagnosis → pivot → deliverables, link design doc + spec.

---

## Self-review notes

- Spec coverage: design §3.1→Task 1, §3.2→Task 2, §3.3→Task 3, §3.4→Task 4, §3.5→Tasks 1+2 (builder + endpoint), §4→Tasks 1–4 tests, §5→Task 6. No gaps.
- Route-order hazard called out in Task 2 (live before `{session_id}`).
- Types consistent: `scan_live_sessions` returns `(list[LiveSession], list[dict])` everywhere; `live_session_roots: dict[str, Path] | None`.
- Known adapt-points (flagged inline, not placeholders): test_cli fixture name, `Ao.apiFetch` POST signature, `agent-*` sidechain skip verified against real dir during Task 1.
