from __future__ import annotations

from dataclasses import dataclass

from agentic_os.logs import LogEntry
from agentic_os.models import SessionRecord, SessionStatus


SUMMARY_MAX_CHARS = 160


@dataclass(frozen=True)
class BuiltSummary:
    one_liner: str
    last_task: str
    last_branch: str
    stopped_at: str | None
    stdout_lines: int
    stderr_lines: int
    error_lines: int


def build_session_summary(session: SessionRecord, entries: list[LogEntry]) -> BuiltSummary:
    stdout = _useful_lines(entries, "stdout")
    stderr = _useful_lines(entries, "stderr")
    first_signal = stdout[0] if stdout else (stderr[0] if stderr else "")
    one_liner = _shorten(first_signal) if first_signal else f"{session.agent_id} session {session.status.value}"
    stopped_at = session.ended_at if session.status == SessionStatus.STOPPED else None

    return BuiltSummary(
        one_liner=one_liner,
        last_task=one_liner,
        last_branch="",
        stopped_at=stopped_at,
        stdout_lines=len(stdout),
        stderr_lines=len(stderr),
        error_lines=sum(1 for line in stderr if _is_error_line(line)),
    )


def _useful_lines(entries: list[LogEntry], stream: str) -> list[str]:
    return [entry.line.strip() for entry in entries if entry.stream == stream and entry.line.strip()]


def _shorten(value: str) -> str:
    return value[:SUMMARY_MAX_CHARS]


def _is_error_line(line: str) -> bool:
    normalized = line.lower()
    return "error" in normalized or "failed" in normalized
