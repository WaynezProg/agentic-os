from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


StreamName = Literal["stdout", "stderr"]


class LogEntry(BaseModel):
    ts: str
    stream: StreamName
    session_id: str
    line: str
    index: int


@dataclass(frozen=True)
class ReadResult:
    entries: list[LogEntry]
    truncated: bool


class JsonlLogStore:
    def append(self, path: Path, session_id: str, stream: StreamName, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stream": stream,
            "session_id": session_id,
            "line": line,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def read(self, path: Path, after: int = 0, max_lines: int = 5000) -> ReadResult:
        if not path.exists():
            return ReadResult(entries=[], truncated=False)
        entries: list[LogEntry] = []
        truncated = False
        with path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index < after:
                    continue
                if len(entries) >= max_lines:
                    truncated = True
                    break
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict):
                    continue
                stream = raw.get("stream")
                if not isinstance(stream, str) or stream not in {"stdout", "stderr"}:
                    continue
                session_id = raw.get("session_id")
                line = raw.get("line")
                ts = raw.get("ts")
                if not isinstance(session_id, str) or not isinstance(line, str) or not isinstance(ts, str):
                    continue
                entries.append(
                    LogEntry(
                        ts=ts,
                        stream=stream,
                        session_id=session_id,
                        line=line,
                        index=index + 1,
                    )
                )
        return ReadResult(entries=entries, truncated=truncated)

    def read_tail(self, path: Path, max_lines: int = 20) -> list[LogEntry]:
        if not path.exists() or max_lines <= 0:
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return []
        tail_lines = lines[-max_lines:]
        start_index = len(lines) - len(tail_lines)
        entries: list[LogEntry] = []
        for offset, line in enumerate(tail_lines):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            stream = raw.get("stream")
            if not isinstance(stream, str) or stream not in {"stdout", "stderr"}:
                continue
            session_id = raw.get("session_id")
            content = raw.get("line")
            ts = raw.get("ts")
            if not isinstance(session_id, str) or not isinstance(content, str) or not isinstance(ts, str):
                continue
            entries.append(
                LogEntry(
                    ts=ts,
                    stream=stream,
                    session_id=session_id,
                    line=content,
                    index=start_index + offset + 1,
                )
            )
        return entries

    def read_merged(
        self,
        stdout_path: Path,
        stderr_path: Path,
        stream: StreamName | None = None,
        after: int = 0,
        max_lines: int = 5000,
    ) -> ReadResult:
        if stream == "stdout":
            return self.read(stdout_path, after=after, max_lines=max_lines)
        if stream == "stderr":
            return self.read(stderr_path, after=after, max_lines=max_lines)
        stdout_result = self.read(stdout_path, max_lines=max_lines)
        stderr_result = self.read(stderr_path, max_lines=max_lines)
        entries = [*stdout_result.entries, *stderr_result.entries]
        entries.sort(key=lambda entry: entry.ts)
        merged_entries = [
            entry.model_copy(update={"index": index})
            for index, entry in enumerate(entries, start=1)
        ]
        filtered = [entry for entry in merged_entries if entry.index > after]
        truncated = stdout_result.truncated or stderr_result.truncated or len(filtered) > max_lines
        return ReadResult(entries=filtered[:max_lines], truncated=truncated)
