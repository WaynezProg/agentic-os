import json
from pathlib import Path

import pytest

from agentic_os.logs import JsonlLogStore, ReadResult


def test_log_store_appends_and_reads_lines(tmp_path: Path) -> None:
    store = JsonlLogStore()
    path = tmp_path / "stdout.jsonl"

    store.append(path, session_id="s_1", stream="stdout", line="hello")
    store.append(path, session_id="s_1", stream="stdout", line="world")

    result = store.read(path)
    entries = result.entries
    assert [entry.line for entry in entries] == ["hello", "world"]
    assert entries[0].stream == "stdout"


def test_log_store_filters_after_cursor(tmp_path: Path) -> None:
    store = JsonlLogStore()
    path = tmp_path / "stdout.jsonl"

    store.append(path, session_id="s_1", stream="stdout", line="one")
    store.append(path, session_id="s_1", stream="stdout", line="two")

    result = store.read(path, after=1)
    assert [entry.line for entry in result.entries] == ["two"]


def test_read_merged_returns_chronological_entries_with_global_indexes(tmp_path: Path) -> None:
    store = JsonlLogStore()
    stdout_path = tmp_path / "stdout.jsonl"
    stderr_path = tmp_path / "stderr.jsonl"
    _write_jsonl(
        stdout_path,
        [
            {
                "ts": "2026-05-27T00:00:01+00:00",
                "stream": "stdout",
                "session_id": "s_1",
                "line": "out-1",
            },
            {
                "ts": "2026-05-27T00:00:04+00:00",
                "stream": "stdout",
                "session_id": "s_1",
                "line": "out-2",
            },
        ],
    )
    _write_jsonl(
        stderr_path,
        [
            {
                "ts": "2026-05-27T00:00:02+00:00",
                "stream": "stderr",
                "session_id": "s_1",
                "line": "err-1",
            },
            {
                "ts": "2026-05-27T00:00:03+00:00",
                "stream": "stderr",
                "session_id": "s_1",
                "line": "err-2",
            },
        ],
    )

    result = store.read_merged(stdout_path, stderr_path)
    entries = result.entries

    assert [entry.line for entry in entries] == ["out-1", "err-1", "err-2", "out-2"]
    assert [entry.index for entry in entries] == [1, 2, 3, 4]
    assert [entry.ts for entry in entries] == sorted(entry.ts for entry in entries)


def test_read_merged_after_cursor_returns_only_newer_entries(tmp_path: Path) -> None:
    store = JsonlLogStore()
    stdout_path = tmp_path / "stdout.jsonl"
    stderr_path = tmp_path / "stderr.jsonl"
    _write_jsonl(
        stdout_path,
        [
            {
                "ts": "2026-05-27T00:00:01+00:00",
                "stream": "stdout",
                "session_id": "s_1",
                "line": "out-1",
            },
            {
                "ts": "2026-05-27T00:00:03+00:00",
                "stream": "stdout",
                "session_id": "s_1",
                "line": "out-2",
            },
        ],
    )
    _write_jsonl(
        stderr_path,
        [
            {
                "ts": "2026-05-27T00:00:02+00:00",
                "stream": "stderr",
                "session_id": "s_1",
                "line": "err-1",
            },
            {
                "ts": "2026-05-27T00:00:04+00:00",
                "stream": "stderr",
                "session_id": "s_1",
                "line": "err-2",
            },
        ],
    )

    result = store.read_merged(stdout_path, stderr_path)
    entries = result.entries
    next_result = store.read_merged(stdout_path, stderr_path, after=entries[1].index)
    next_entries = next_result.entries

    assert [entry.line for entry in next_entries] == ["out-2", "err-2"]
    assert [entry.index for entry in next_entries] == [3, 4]


def test_read_merged_stream_filter_keeps_per_file_indexes(tmp_path: Path) -> None:
    store = JsonlLogStore()
    stdout_path = tmp_path / "stdout.jsonl"
    stderr_path = tmp_path / "stderr.jsonl"
    _write_jsonl(
        stdout_path,
        [
            {
                "ts": "2026-05-27T00:00:01+00:00",
                "stream": "stdout",
                "session_id": "s_1",
                "line": "out-1",
            },
            {
                "ts": "2026-05-27T00:00:03+00:00",
                "stream": "stdout",
                "session_id": "s_1",
                "line": "out-2",
            },
        ],
    )
    _write_jsonl(
        stderr_path,
        [
            {
                "ts": "2026-05-27T00:00:02+00:00",
                "stream": "stderr",
                "session_id": "s_1",
                "line": "err-1",
            },
        ],
    )

    result = store.read_merged(stdout_path, stderr_path, stream="stdout")
    entries = result.entries

    assert [entry.stream for entry in entries] == ["stdout", "stdout"]
    assert [entry.line for entry in entries] == ["out-1", "out-2"]
    assert [entry.index for entry in entries] == [1, 2]


def test_log_store_malformed_jsonl_fails_fast(tmp_path: Path) -> None:
    store = JsonlLogStore()
    path = tmp_path / "stdout.jsonl"
    path.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        store.read(path)


def test_read_returns_read_result_with_truncated_false(tmp_path: Path) -> None:
    logs = JsonlLogStore()
    path = tmp_path / "test.jsonl"
    logs.append(path, "s_1", "stdout", "line1")
    logs.append(path, "s_1", "stdout", "line2")
    result = logs.read(path)
    assert isinstance(result, ReadResult)
    assert len(result.entries) == 2
    assert result.truncated is False


def test_read_truncates_at_max_lines(tmp_path: Path) -> None:
    logs = JsonlLogStore()
    path = tmp_path / "test.jsonl"
    for i in range(10):
        logs.append(path, "s_1", "stdout", f"line{i}")
    result = logs.read(path, max_lines=3)
    assert len(result.entries) == 3
    assert result.truncated is True


def test_read_merged_truncates_per_stream(tmp_path: Path) -> None:
    logs = JsonlLogStore()
    stdout = tmp_path / "stdout.jsonl"
    stderr = tmp_path / "stderr.jsonl"
    for i in range(10):
        logs.append(stdout, "s_1", "stdout", f"out{i}")
        logs.append(stderr, "s_1", "stderr", f"err{i}")
    result = logs.read_merged(stdout, stderr, max_lines=3)
    assert result.truncated is True
    assert len(result.entries) <= 6  # 3 per stream max


def _write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
