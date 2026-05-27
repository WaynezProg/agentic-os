from pathlib import Path

import pytest

from agentic_os.logs import LogEntry
from agentic_os.memory import build_session_summary
from agentic_os.memory_store import MemoryStore
from agentic_os.models import SessionRecord, SessionStatus


def _session(
    tmp_path: Path,
    *,
    session_id: str = "s_1",
    agent_id: str = "shell",
    status: SessionStatus = SessionStatus.SUCCEEDED,
    ended_at: str | None = None,
) -> SessionRecord:
    return SessionRecord(
        id=session_id,
        agent_id=agent_id,
        cwd=str(tmp_path),
        argv=["/bin/echo", "OK"],
        env={},
        artifact_dir=str(tmp_path / "sessions" / session_id),
        stdout_log=str(tmp_path / "sessions" / session_id / "stdout.jsonl"),
        stderr_log=str(tmp_path / "sessions" / session_id / "stderr.jsonl"),
        summary_one_liner="",
        status=status,
        pid=None,
        pgid=None,
        exit_code=0 if status == SessionStatus.SUCCEEDED else 1,
        started_at="2026-05-28T00:00:00+00:00",
        ended_at=ended_at,
        updated_at="2026-05-28T00:00:01+00:00",
    )


def _entry(stream: str, line: str, index: int = 1) -> LogEntry:
    return LogEntry(
        ts=f"2026-05-28T00:00:0{index}+00:00",
        stream=stream,
        session_id="s_1",
        line=line,
        index=index,
    )


def test_summary_text_from_successful_stdout_logs(tmp_path: Path) -> None:
    summary = build_session_summary(
        _session(tmp_path),
        [
            _entry("stderr", "warning before output", index=1),
            _entry("stdout", "  completed checkout  ", index=2),
            _entry("stdout", "ignored second line", index=3),
        ],
    )

    assert summary.one_liner == "completed checkout"
    assert summary.last_task == "completed checkout"
    assert summary.last_branch == ""
    assert summary.stopped_at is None
    assert summary.stdout_lines == 2
    assert summary.stderr_lines == 1
    assert summary.error_lines == 0


def test_summary_text_from_failed_stderr_logs(tmp_path: Path) -> None:
    summary = build_session_summary(
        _session(tmp_path, status=SessionStatus.FAILED),
        [
            _entry("stderr", "  failed to run tests  ", index=1),
            _entry("stderr", "error: assertion failed", index=2),
        ],
    )

    assert summary.one_liner == "failed to run tests"
    assert summary.last_task == "failed to run tests"
    assert summary.stopped_at is None
    assert summary.stdout_lines == 0
    assert summary.stderr_lines == 2
    assert summary.error_lines == 2


def test_summary_falls_back_for_empty_logs(tmp_path: Path) -> None:
    summary = build_session_summary(
        _session(
            tmp_path,
            agent_id="worker",
            status=SessionStatus.STOPPED,
            ended_at="2026-05-28T00:05:00+00:00",
        ),
        [],
    )

    assert summary.one_liner == "worker session stopped"
    assert summary.last_task == "worker session stopped"
    assert summary.stopped_at == "2026-05-28T00:05:00+00:00"
    assert summary.stdout_lines == 0
    assert summary.stderr_lines == 0
    assert summary.error_lines == 0


def test_summary_creation_is_idempotent_per_session(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "agentic-os.db")
    store.init()
    session = _session(tmp_path)
    built = build_session_summary(session, [_entry("stdout", "done")])

    first = store.upsert_summary(session, built)
    second = store.upsert_summary(session, built)

    assert second.id == first.id
    assert second.session_id == session.id
    assert store.get_summary(session.id).id == first.id


def test_review_item_create_and_list_are_idempotent_for_active_item(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "agentic-os.db")
    store.init()
    summary = store.upsert_summary(
        _session(tmp_path),
        build_session_summary(_session(tmp_path), [_entry("stdout", "ship memory store")]),
    )

    first = store.create_review_item(summary)
    second = store.create_review_item(summary)

    assert second.id == first.id
    assert second.status == "pending"
    assert second.kind == "project_memory"
    assert second.title == "ship memory store"
    assert [item.id for item in store.list_review_items()] == [first.id]


def test_approve_creates_one_memory_and_prevents_duplicate_memory(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "agentic-os.db")
    store.init()
    summary = store.upsert_summary(
        _session(tmp_path),
        build_session_summary(_session(tmp_path), [_entry("stdout", "approved memory text")]),
    )
    item = store.create_review_item(summary)

    memory = store.approve_review_item(item.id)

    assert memory.review_item_id == item.id
    assert memory.title == "approved memory text"
    assert len(store.list_memories()) == 1
    with pytest.raises(ValueError):
        store.approve_review_item(item.id)
    assert len(store.list_memories()) == 1


def test_reject_creates_no_memory(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "agentic-os.db")
    store.init()
    summary = store.upsert_summary(
        _session(tmp_path),
        build_session_summary(_session(tmp_path), [_entry("stdout", "reject me")]),
    )
    item = store.create_review_item(summary)

    rejected = store.reject_review_item(item.id)

    assert rejected.status == "rejected"
    assert store.list_memories() == []
    with pytest.raises(ValueError):
        store.reject_review_item(item.id)


def test_search_returns_approved_memories_only(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "agentic-os.db")
    store.init()
    approved_summary = store.upsert_summary(
        _session(tmp_path, session_id="s_approved"),
        build_session_summary(
            _session(tmp_path, session_id="s_approved"),
            [_entry("stdout", "remember alpha release")],
        ),
    )
    pending_summary = store.upsert_summary(
        _session(tmp_path, session_id="s_pending"),
        build_session_summary(
            _session(tmp_path, session_id="s_pending"),
            [_entry("stdout", "remember beta draft")],
        ),
    )

    store.approve_review_item(store.create_review_item(approved_summary).id)
    store.create_review_item(pending_summary)

    assert [memory.title for memory in store.search_memories("alpha")] == [
        "remember alpha release"
    ]
    assert store.search_memories("beta") == []
