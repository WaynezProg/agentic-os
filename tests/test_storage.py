import sqlite3
from pathlib import Path

import pytest

from agentic_os.models import SessionCreate, SessionStatus
from agentic_os.storage import Store


def _session_create(tmp_path: Path, env: dict[str, str] | None = None) -> SessionCreate:
    return SessionCreate(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=["/bin/echo", "OK"],
        artifact_dir=str(tmp_path / "sessions" / "s_1"),
        stdout_log=str(tmp_path / "sessions" / "s_1" / "stdout.jsonl"),
        stderr_log=str(tmp_path / "sessions" / "s_1" / "stderr.jsonl"),
        env=env or {},
    )


def _create_old_sessions_db_without_status_check(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (
              id TEXT PRIMARY KEY,
              agent_id TEXT NOT NULL,
              cwd TEXT NOT NULL,
              argv_json TEXT NOT NULL,
              status TEXT NOT NULL,
              pid INTEGER,
              pgid INTEGER,
              exit_code INTEGER,
              artifact_dir TEXT NOT NULL,
              stdout_log TEXT NOT NULL,
              stderr_log TEXT NOT NULL,
              summary_one_liner TEXT NOT NULL DEFAULT '',
              started_at TEXT,
              ended_at TEXT,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            INSERT INTO sessions (
              id, agent_id, cwd, argv_json, status, artifact_dir,
              stdout_log, stderr_log, updated_at
            )
            VALUES (
              's_valid', 'shell', '/tmp', '["/bin/echo", "OK"]', 'queued',
              '/tmp/sessions/s_valid', '/tmp/sessions/s_valid/stdout.jsonl',
              '/tmp/sessions/s_valid/stderr.jsonl', CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO sessions (
              id, agent_id, cwd, argv_json, status, artifact_dir,
              stdout_log, stderr_log, updated_at
            )
            VALUES (
              's_bogus', 'shell', '/tmp', '["/bin/echo", "OK"]', 'bogus',
              '/tmp/sessions/s_bogus', '/tmp/sessions/s_bogus/stdout.jsonl',
              '/tmp/sessions/s_bogus/stderr.jsonl', CURRENT_TIMESTAMP
            )
            """
        )


def _create_current_sessions_db_without_env_json(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (
              id TEXT PRIMARY KEY,
              agent_id TEXT NOT NULL,
              cwd TEXT NOT NULL,
              argv_json TEXT NOT NULL,
              status TEXT NOT NULL CHECK (
                status IN ('queued', 'running', 'stopping', 'succeeded', 'failed', 'stopped')
              ),
              pid INTEGER,
              pgid INTEGER,
              exit_code INTEGER,
              artifact_dir TEXT NOT NULL,
              stdout_log TEXT NOT NULL,
              stderr_log TEXT NOT NULL,
              summary_one_liner TEXT NOT NULL DEFAULT '',
              started_at TEXT,
              ended_at TEXT,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              message TEXT NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            """
            INSERT INTO sessions (
              id, agent_id, cwd, argv_json, status, artifact_dir,
              stdout_log, stderr_log, updated_at
            )
            VALUES (
              's_envless', 'shell', '/tmp', '["/bin/echo", "OK"]', 'queued',
              '/tmp/sessions/s_envless', '/tmp/sessions/s_envless/stdout.jsonl',
              '/tmp/sessions/s_envless/stderr.jsonl', CURRENT_TIMESTAMP
            )
            """
        )


def test_store_persists_session_workspace_path(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()

    request = _session_create(tmp_path)
    request = request.model_copy(update={"workspace_path": "/tmp/workspace-alpha"})

    created = store.create_session(request)

    fetched = store.get_session(created.id)
    assert fetched.workspace_path == "/tmp/workspace-alpha"


def test_store_persists_null_workspace_path(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()

    request = _session_create(tmp_path)

    created = store.create_session(request)

    fetched = store.get_session(created.id)
    assert fetched.workspace_path is None


def test_init_adds_workspace_path_to_existing_sessions_table(tmp_path: Path) -> None:
    db_path = tmp_path / "agentic-os.db"
    _create_current_sessions_db_without_env_json(db_path)

    Store(db_path).init()

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
    assert "workspace_path" in columns


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


def test_store_persists_session_env(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()

    session = store.create_session(
        _session_create(tmp_path, env={"AGENTIC_OS_ENV_PROBE": "stored"})
    )

    assert session.env == {"AGENTIC_OS_ENV_PROBE": "stored"}
    assert store.get_session(session.id).env == {"AGENTIC_OS_ENV_PROBE": "stored"}


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
    store.mark_running(session.id, pid=123, pgid=123)
    store.mark_finished(session.id, exit_code=0)

    with pytest.raises(ValueError):
        store.mark_running(session.id, pid=456, pgid=456)

    stored = store.get_session(session.id)
    assert stored.status == SessionStatus.SUCCEEDED
    assert stored.exit_code == 0
    assert stored.pid == 123
    assert stored.pgid == 123


def test_nonzero_exit_marks_session_failed(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()
    session = store.create_session(_session_create(tmp_path))

    finished = store.mark_finished(session.id, exit_code=7)

    assert finished.status == SessionStatus.FAILED
    assert finished.exit_code == 7


def test_init_migrates_old_events_table_without_foreign_key(tmp_path: Path) -> None:
    db_path = tmp_path / "agentic-os.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (
              id TEXT PRIMARY KEY,
              agent_id TEXT NOT NULL,
              cwd TEXT NOT NULL,
              argv_json TEXT NOT NULL,
              status TEXT NOT NULL,
              pid INTEGER,
              pgid INTEGER,
              exit_code INTEGER,
              artifact_dir TEXT NOT NULL,
              stdout_log TEXT NOT NULL,
              stderr_log TEXT NOT NULL,
              summary_one_liner TEXT NOT NULL DEFAULT '',
              started_at TEXT,
              ended_at TEXT,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              message TEXT NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            INSERT INTO sessions (
              id, agent_id, cwd, argv_json, status, artifact_dir,
              stdout_log, stderr_log, updated_at
            )
            VALUES (
              's_valid', 'shell', '/tmp', '["/bin/echo", "OK"]', 'queued',
              '/tmp/sessions/s_valid', '/tmp/sessions/s_valid/stdout.jsonl',
              '/tmp/sessions/s_valid/stderr.jsonl', CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO events (session_id, event_type, message, metadata_json)
            VALUES ('s_valid', 'launch_failed', 'valid event', '{"valid": true}')
            """
        )
        conn.execute(
            """
            INSERT INTO events (session_id, event_type, message, metadata_json)
            VALUES ('missing-session', 'launch_failed', 'orphan event', '{}')
            """
        )

    store = Store(db_path)
    store.init()

    with sqlite3.connect(db_path) as conn:
        foreign_keys = conn.execute("PRAGMA foreign_key_list(events)").fetchall()

    assert foreign_keys
    assert len(store.list_events("s_valid")) == 1
    assert store.list_events("missing-session") == []
    with pytest.raises(sqlite3.IntegrityError):
        store.record_event("missing-session", "launch_failed", "missing executable")


def test_init_migrates_old_sessions_table_without_status_check(tmp_path: Path) -> None:
    db_path = tmp_path / "agentic-os.db"
    _create_old_sessions_db_without_status_check(db_path)
    Store(db_path).init()

    with sqlite3.connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO sessions (
                  id, agent_id, cwd, argv_json, status, artifact_dir,
                  stdout_log, stderr_log
                )
                VALUES (
                  's_new_bogus', 'shell', '/tmp', '["/bin/echo", "OK"]', 'bogus',
                  '/tmp/sessions/s_new_bogus', '/tmp/sessions/s_new_bogus/stdout.jsonl',
                  '/tmp/sessions/s_new_bogus/stderr.jsonl'
                )
                """
            )


def test_init_preserves_valid_old_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "agentic-os.db"
    _create_old_sessions_db_without_status_check(db_path)
    store = Store(db_path)
    store.init()

    session = store.get_session("s_valid")

    assert session.status == SessionStatus.QUEUED
    assert session.argv == ["/bin/echo", "OK"]
    assert session.env == {}


def test_init_adds_env_json_to_existing_sessions_table(tmp_path: Path) -> None:
    db_path = tmp_path / "agentic-os.db"
    _create_current_sessions_db_without_env_json(db_path)
    store = Store(db_path)
    store.init()

    session = store.get_session("s_envless")

    assert session.env == {}
    with sqlite3.connect(db_path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()]
    assert "env_json" in columns


def test_init_drops_invalid_old_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "agentic-os.db"
    _create_old_sessions_db_without_status_check(db_path)
    store = Store(db_path)
    store.init()

    with pytest.raises(KeyError):
        store.get_session("s_bogus")

    assert [session.id for session in store.list_sessions()] == ["s_valid"]


def test_stopping_session_cannot_be_marked_running_again(tmp_path: Path) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()
    session = store.create_session(_session_create(tmp_path))
    store.mark_running(session.id, pid=123, pgid=123)
    store.mark_stopping(session.id)

    with pytest.raises(ValueError):
        store.mark_running(session.id, pid=456, pgid=456)

    assert store.get_session(session.id).status == SessionStatus.STOPPING


@pytest.mark.parametrize("terminal_status", [SessionStatus.FAILED, SessionStatus.STOPPED])
def test_terminal_sessions_cannot_be_marked_running_again(
    tmp_path: Path, terminal_status: SessionStatus
) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()
    session = store.create_session(_session_create(tmp_path))

    if terminal_status == SessionStatus.FAILED:
        store.mark_finished(session.id, exit_code=7)
    else:
        store.mark_running(session.id, pid=123, pgid=123)
        store.mark_stopped(session.id)

    with pytest.raises(ValueError):
        store.mark_running(session.id, pid=456, pgid=456)

    assert store.get_session(session.id).status == terminal_status


def test_mark_running_rejects_interleaved_terminal_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "agentic-os.db")
    store.init()
    session = store.create_session(_session_create(tmp_path))
    original_transition = getattr(store, "_transition_session", None)

    def interleaving_transition(*args: object, **kwargs: object) -> object:
        with store.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, exit_code = ?, ended_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (SessionStatus.FAILED.value, 7, session.id),
            )
        if original_transition is None:
            raise AssertionError("Store did not use an atomic transition update")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(store, "_transition_session", interleaving_transition, raising=False)

    with pytest.raises(ValueError):
        store.mark_running(session.id, pid=456, pgid=456)

    stored = store.get_session(session.id)
    assert stored.status == SessionStatus.FAILED
    assert stored.exit_code == 7
    assert stored.pid is None
    assert stored.pgid is None
