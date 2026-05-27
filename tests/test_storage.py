import sqlite3
from pathlib import Path

import pytest

from agentic_os.models import SessionCreate, SessionStatus
from agentic_os.storage import Store


def _session_create(tmp_path: Path) -> SessionCreate:
    return SessionCreate(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=["/bin/echo", "OK"],
        artifact_dir=str(tmp_path / "sessions" / "s_1"),
        stdout_log=str(tmp_path / "sessions" / "s_1" / "stdout.jsonl"),
        stderr_log=str(tmp_path / "sessions" / "s_1" / "stderr.jsonl"),
    )


def test_store_creates_and_updates_session(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()

    session = store.create_session(_session_create(tmp_path))

    assert session.id.startswith("s_")
    assert session.status == SessionStatus.QUEUED

    updated = store.mark_running(session.id, pid=123, pgid=123)
    assert updated.status == SessionStatus.RUNNING
    assert updated.pid == 123
    assert updated.pgid == 123

    finished = store.mark_finished(session.id, exit_code=0)
    assert finished.status == SessionStatus.SUCCEEDED
    assert finished.exit_code == 0


def test_store_records_events(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()
    session = store.create_session(_session_create(tmp_path))

    store.record_event(session.id, "launch_failed", "missing executable", {"argv": ["missing"]})

    events = store.list_events(session.id)
    assert len(events) == 1
    assert events[0].event_type == "launch_failed"
    assert events[0].metadata == {"argv": ["missing"]}


def test_store_rejects_event_for_missing_session(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()

    with pytest.raises(sqlite3.IntegrityError):
        store.record_event("missing-session", "launch_failed", "missing executable")

    assert store.list_events("missing-session") == []


def test_succeeded_session_cannot_be_marked_running_again(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()
    session = store.create_session(_session_create(tmp_path))
    store.mark_finished(session.id, exit_code=0)

    with pytest.raises(ValueError):
        store.mark_running(session.id, pid=456, pgid=456)

    stored = store.get_session(session.id)
    assert stored.status == SessionStatus.SUCCEEDED
    assert stored.exit_code == 0
    assert stored.pid is None
    assert stored.pgid is None


def test_nonzero_exit_marks_session_failed(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()
    session = store.create_session(_session_create(tmp_path))

    finished = store.mark_finished(session.id, exit_code=7)

    assert finished.status == SessionStatus.FAILED
    assert finished.exit_code == 7
