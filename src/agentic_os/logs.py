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
                raw = json.loads(line)
                entries.append(
                    LogEntry(
                        ts=raw["ts"],
                        stream=raw["stream"],
                        session_id=raw["session_id"],
                        line=raw["line"],
                        index=index + 1,
                    )
                )
        return ReadResult(entries=entries, truncated=truncated)

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
