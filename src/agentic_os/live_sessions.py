"""Read-only scanners over real vibe coding session stores (P39).

Observes session files written by external tools (Claude Code, Codex)
without launching, modifying, or attaching to them. All file IO is
bounded: stat-based mtime pruning before open, head reads capped by
byte and object budgets.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_HEAD_BYTES = 512 * 1024
_MAX_HEAD_OBJECTS = 200
_ACTIVE_WINDOW_SECONDS = 300
_TITLE_MAX_CHARS = 120

_CLAUDE_DEFAULT_ROOT = "~/.claude/projects"
_CODEX_DEFAULT_ROOT = "~/.codex/sessions"

_RESUME_ARGV = {
    "claude": ("claude", "--resume"),
    "codex": ("codex", "resume"),
}
_SESSION_ID_RE = re.compile(r"^[0-9A-Za-z._-]{4,128}$")
_SKIP_TITLE_PREFIXES = ("<", "Caveat:", "# AGENTS.md")


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


def _read_head_objects(path: Path) -> list[dict[str, object]]:
    """Parse JSONL objects from the file head under byte + object budgets.

    Single giant lines (codex session_meta with embedded instructions)
    consume the byte budget but never unbounded memory across files.
    """
    objs: list[dict[str, object]] = []
    read_chars = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                read_chars += len(line)
                stripped = line.strip()
                if stripped.startswith("{"):
                    try:
                        payload = json.loads(stripped)
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict):
                        objs.append(payload)
                if len(objs) >= _MAX_HEAD_OBJECTS or read_chars >= _HEAD_BYTES:
                    break
    except OSError:
        return objs
    return objs


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


def _is_hidden_workspace(workspace: str) -> bool:
    # Sessions run inside dot-directories (~/.claude-mem, ~/.cache, ...)
    # are infrastructure runs, not user vibe coding work.
    return any(part.startswith(".") for part in Path(workspace).parts)


# --- Claude Code (~/.claude/projects/<encoded-cwd>/<session>.jsonl) ---


def _decode_claude_project_dir(name: str) -> str:
    # Dir name encodes cwd with "/" and "." replaced by "-"; lossy for
    # dashed paths, so only used when no cwd key is in the JSONL head.
    # "--" marks a hidden dir ("/.") so the hidden-workspace filter
    # still applies to fallback-decoded paths.
    if not name.startswith("-"):
        return name
    return "/" + name[1:].replace("--", "/.").replace("-", "/")


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
            objs = _read_head_objects(jsonl)
            if not objs:
                continue
            session_id = _first_str(objs, "sessionId") or jsonl.stem
            workspace = _first_str(objs, "cwd") or _decode_claude_project_dir(project_dir.name)
            if _is_hidden_workspace(workspace):
                continue
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
        objs = _read_head_objects(jsonl)
        meta: dict[str, object] | None = None
        for obj in objs:
            payload = obj.get("payload")
            if obj.get("type") == "session_meta" and isinstance(payload, dict):
                meta = payload
                break
        if meta is None:
            continue
        raw_id = meta.get("id")
        session_id = raw_id if isinstance(raw_id, str) and raw_id else jsonl.stem
        raw_cwd = meta.get("cwd")
        workspace = raw_cwd if isinstance(raw_cwd, str) and raw_cwd else "?"
        if _is_hidden_workspace(workspace):
            continue
        source: str | None = None
        for key in ("originator", "source"):
            value = meta.get(key)
            if isinstance(value, str) and value:
                source = value
                break
        raw_started = meta.get("timestamp")
        started_at = raw_started if isinstance(raw_started, str) else None
        results.append(
            LiveSession(
                tool="codex",
                session_id=session_id,
                workspace=workspace,
                title=_codex_title(objs),
                started_at=started_at,
                last_activity_at=_iso(stat.st_mtime),
                active=(now_ts - stat.st_mtime) < _ACTIVE_WINDOW_SECONDS,
                source=source,
                log_path=str(jsonl),
                resume_command=_resume_command("codex", workspace, session_id),
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


# --- Transcript tail preview (P41) ---

_TAIL_BYTES = 256 * 1024
_TRANSCRIPT_TEXT_MAX = 2000


def _clip(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) <= _TRANSCRIPT_TEXT_MAX:
        return cleaned
    return cleaned[: _TRANSCRIPT_TEXT_MAX - 1] + "…"


def _read_tail_objects(path: Path) -> list[dict[str, object]]:
    try:
        size = path.stat().st_size
        offset = max(0, size - _TAIL_BYTES)
        with path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read(_TAIL_BYTES)
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if offset > 0 and lines:
        lines = lines[1:]  # drop the line cut by the seek offset
    objs: list[dict[str, object]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            objs.append(payload)
    return objs


def _message_text(content: object) -> str | None:
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "text":
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return None


def _claude_transcript(objs: list[dict[str, object]]) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for obj in objs:
        role = obj.get("type")
        if role not in {"user", "assistant"}:
            continue
        message = obj.get("message")
        if not isinstance(message, dict):
            continue
        text = _message_text(message.get("content"))
        if text is None:
            continue
        if role == "user" and not _is_real_prompt(text):
            continue
        messages.append(
            {"role": role, "text": _clip(text), "timestamp": obj.get("timestamp")}
        )
    return messages


def _codex_transcript(objs: list[dict[str, object]]) -> list[dict[str, object]]:
    # event_msg carries both sides; response_item duplicates them, so it
    # is intentionally ignored here to avoid double entries.
    messages: list[dict[str, object]] = []
    for obj in objs:
        if obj.get("type") != "event_msg":
            continue
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue
        kind = payload.get("type")
        text = payload.get("message")
        if not isinstance(text, str) or not text.strip():
            continue
        if kind == "user_message" and _is_real_prompt(text):
            role = "user"
        elif kind == "agent_message":
            role = "assistant"
        else:
            continue
        messages.append(
            {"role": role, "text": _clip(text), "timestamp": obj.get("timestamp")}
        )
    return messages


def read_transcript_tail(path: Path, tool: str, limit: int = 50) -> list[dict[str, object]]:
    """Parse the last messages of a session transcript. Read-only, tail-bounded."""
    objs = _read_tail_objects(path)
    if tool == "claude":
        messages = _claude_transcript(objs)
    elif tool == "codex":
        messages = _codex_transcript(objs)
    else:
        return []
    return messages[-limit:]


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

    Fire-and-forget: osascript can block on the one-time macOS
    Automation permission prompt, so the daemon must not wait for it.
    Raises ValueError for invalid input, RuntimeError when osascript
    cannot launch or fails instantly.
    """
    argv = build_open_terminal_command(tool, session_id, workspace)
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise RuntimeError(f"failed to launch osascript: {exc}") from exc
    try:
        returncode = proc.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        return  # still running — likely waiting on Terminal/permission UI
    if returncode != 0:
        raise RuntimeError(f"osascript exited with {returncode}")
