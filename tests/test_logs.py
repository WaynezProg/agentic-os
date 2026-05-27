from pathlib import Path

from agentic_os.logs import JsonlLogStore


def test_log_store_appends_and_reads_lines(tmp_path: Path) -> None:
    store = JsonlLogStore()
    path = tmp_path / "stdout.jsonl"

    store.append(path, session_id="s_1", stream="stdout", line="hello")
    store.append(path, session_id="s_1", stream="stdout", line="world")

    entries = store.read(path)
    assert [entry.line for entry in entries] == ["hello", "world"]
    assert entries[0].stream == "stdout"


def test_log_store_filters_after_cursor(tmp_path: Path) -> None:
    store = JsonlLogStore()
    path = tmp_path / "stdout.jsonl"

    store.append(path, session_id="s_1", stream="stdout", line="one")
    store.append(path, session_id="s_1", stream="stdout", line="two")

    entries = store.read(path, after=1)
    assert [entry.line for entry in entries] == ["two"]
