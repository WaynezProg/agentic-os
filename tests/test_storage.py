from pathlib import Path

from agentic_os.models import SessionCreate, SessionStatus
from agentic_os.storage import Store


def test_store_creates_and_updates_session(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()

    session = store.create_session(
        SessionCreate(
            agent_id="shell",
            cwd=str(tmp_path),
            argv=["/bin/echo", "OK"],
            artifact_dir=str(tmp_path / "sessions" / "s_1"),
            stdout_log=str(tmp_path / "sessions" / "s_1" / "stdout.jsonl"),
            stderr_log=str(tmp_path / "sessions" / "s_1" / "stderr.jsonl"),
        )
    )

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
    session = store.create_session(
        SessionCreate(
            agent_id="shell",
            cwd=str(tmp_path),
            argv=["/bin/echo", "OK"],
            artifact_dir=str(tmp_path / "sessions" / "s_1"),
            stdout_log=str(tmp_path / "sessions" / "s_1" / "stdout.jsonl"),
            stderr_log=str(tmp_path / "sessions" / "s_1" / "stderr.jsonl"),
        )
    )

    store.record_event(session.id, "launch_failed", "missing executable", {"argv": ["missing"]})

    events = store.list_events(session.id)
    assert len(events) == 1
    assert events[0].event_type == "launch_failed"
    assert events[0].metadata == {"argv": ["missing"]}
