from __future__ import annotations

import json
import threading
from pathlib import Path

from agentic_os.jsonio import atomic_write_json


def test_atomic_write_json_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "metadata.json"
    atomic_write_json(target, {"b": 2, "a": 1})

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {"a": 1, "b": 2}
    # keys are sorted and the file is pretty-printed with a trailing newline.
    assert target.read_text(encoding="utf-8").endswith("\n")
    assert list(data.keys()) == ["a", "b"]


def test_atomic_write_json_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "metadata.json"
    atomic_write_json(target, {"value": 1})
    assert list(tmp_path.glob(".*.tmp")) == []


def test_concurrent_writers_do_not_collide(tmp_path: Path) -> None:
    """Concurrent writers to the same path must never race on the temp file.

    A fixed temp-file name made two threads share ``.metadata.json.tmp``; one
    would rename it away and the other's ``replace`` raised FileNotFoundError.
    """
    target = tmp_path / "metadata.json"
    errors: list[BaseException] = []

    def worker(worker_id: int) -> None:
        for index in range(100):
            try:
                atomic_write_json(target, {"worker": worker_id, "index": index})
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    # The target always holds a complete, parseable document (atomic replace).
    json.loads(target.read_text(encoding="utf-8"))
    # No staging files leak from the concurrent writes.
    assert list(tmp_path.glob(".*.tmp")) == []
