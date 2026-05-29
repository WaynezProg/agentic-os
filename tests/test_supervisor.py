import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from agentic_os.logs import JsonlLogStore
from agentic_os.models import SessionCreate, SessionRecord, SessionStatus
from agentic_os.storage import Store
from agentic_os.supervisor import ProcessSupervisor


def make_supervisor(tmp_path: Path) -> ProcessSupervisor:
    store = Store(tmp_path / "agentic-os.db")
    store.init()
    return ProcessSupervisor(store=store, logs=JsonlLogStore(), state_dir=tmp_path)


def wait_until_done(supervisor: ProcessSupervisor, session_id: str) -> None:
    for _ in range(50):
        session = supervisor.store.get_session(session_id)
        if session.status in {
            SessionStatus.SUCCEEDED,
            SessionStatus.FAILED,
            SessionStatus.STOPPED,
        }:
            return
        time.sleep(0.05)
    raise AssertionError("session did not finish")


def wait_until_pid_gone(pid: int, timeout_seconds: float = 2.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not pid_exists(pid):
            return
        time.sleep(0.02)
    raise AssertionError(f"pid {pid} is still alive")


def wait_until_process_group_gone(pgid: int, timeout_seconds: float = 2.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not process_group_exists(pgid):
            return
        time.sleep(0.02)
    raise AssertionError(f"process group {pgid} is still alive")


def wait_until_file_exists(path: Path, timeout_seconds: float = 2.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"{path} was not created")


def wait_until_session_status(
    supervisor: ProcessSupervisor,
    session_id: str,
    status: SessionStatus,
    timeout_seconds: float = 2.0,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if supervisor.store.get_session(session_id).status == status:
            return
        time.sleep(0.02)
    current = supervisor.store.get_session(session_id)
    raise AssertionError(f"session status is {current.status}, not {status}")


def wait_until_event_or_terminal(
    supervisor: ProcessSupervisor,
    session_id: str,
    event_type: str,
    timeout_seconds: float = 2.0,
) -> None:
    terminal_statuses = {
        SessionStatus.SUCCEEDED,
        SessionStatus.FAILED,
        SessionStatus.STOPPED,
    }
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        events = supervisor.store.list_events(session_id)
        if any(event.event_type == event_type for event in events):
            return
        if supervisor.store.get_session(session_id).status in terminal_statuses:
            return
        time.sleep(0.02)
    raise AssertionError(f"event {event_type} was not recorded")


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def cleanup_process_group(pgid: int | None, pid: int | None) -> None:
    if pgid is None:
        if pid is None or not pid_exists(pid):
            return
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        wait_until_pid_gone(pid)
        return

    if not process_group_exists(pgid):
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return
    wait_until_process_group_gone(pgid)


def child_ignores_sigterm_argv(ready_path: Path) -> list[str]:
    child_code = (
        "import pathlib, signal, sys, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path(sys.argv[1]).write_text('ready', encoding='utf-8'); "
        "time.sleep(10)"
    )
    parent_code = (
        "import pathlib, signal, subprocess, sys, time; "
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); "
        f"subprocess.Popen([{sys.executable!r}, '-c', {child_code!r}, sys.argv[1]], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "time.sleep(10)"
    )
    return [sys.executable, "-c", parent_code, str(ready_path)]


def orphaned_child_process_group(ready_path: Path) -> tuple[int, int]:
    child_code = (
        "import pathlib, signal, sys, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path(sys.argv[1]).write_text('ready', encoding='utf-8'); "
        "time.sleep(10)"
    )
    parent_code = (
        "import pathlib, subprocess, sys; "
        f"subprocess.Popen([{sys.executable!r}, '-c', {child_code!r}, sys.argv[1]], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", parent_code, str(ready_path)],
        start_new_session=True,
    )
    pgid = os.getpgid(process.pid)
    wait_until_file_exists(ready_path)
    process.wait(timeout=2.0)
    return process.pid, pgid


def orphaned_child_finishes_process_group(ready_path: Path) -> tuple[int, int]:
    child_code = (
        "import pathlib, sys, time; "
        "pathlib.Path(sys.argv[1]).write_text('ready', encoding='utf-8'); "
        "time.sleep(0.2)"
    )
    parent_code = (
        "import pathlib, subprocess, sys; "
        f"subprocess.Popen([{sys.executable!r}, '-c', {child_code!r}, sys.argv[1]], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", parent_code, str(ready_path)],
        start_new_session=True,
    )
    pgid = os.getpgid(process.pid)
    wait_until_file_exists(ready_path)
    process.wait(timeout=2.0)
    return process.pid, pgid


def parent_exits_child_stays_argv(ready_path: Path) -> list[str]:
    child_code = (
        "import pathlib, signal, sys, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path(sys.argv[1]).write_text('ready', encoding='utf-8'); "
        "time.sleep(10)"
    )
    parent_code = (
        "import subprocess, sys; "
        f"subprocess.Popen([{sys.executable!r}, '-c', {child_code!r}, sys.argv[1]], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
    )
    return [sys.executable, "-c", parent_code, str(ready_path)]


def parent_exits_child_finishes_argv(ready_path: Path, exit_code: int) -> list[str]:
    child_code = (
        "import pathlib, sys, time; "
        "pathlib.Path(sys.argv[1]).write_text('ready', encoding='utf-8'); "
        "time.sleep(0.2)"
    )
    parent_code = (
        "import subprocess, sys; "
        f"subprocess.Popen([{sys.executable!r}, '-c', {child_code!r}, sys.argv[1]], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        f"sys.exit({exit_code})"
    )
    return [sys.executable, "-c", parent_code, str(ready_path)]


def missing_process_id() -> int:
    for candidate in range(900_000, 901_000):
        if not pid_exists(candidate) and not process_group_exists(candidate):
            return candidate
    raise AssertionError("could not find missing pid/pgid candidate")


def create_running_session(
    store: Store,
    tmp_path: Path,
    *,
    pid: int,
    pgid: int,
    argv: list[str] | None = None,
) -> SessionRecord:
    session = store.create_session(
        SessionCreate(
            agent_id="shell",
            cwd=str(tmp_path),
            argv=argv or ["/bin/sh", "-lc", "sleep 10"],
            artifact_dir=str(tmp_path / "sessions" / "manual" / "artifacts"),
            stdout_log=str(tmp_path / "sessions" / "manual" / "stdout.jsonl"),
            stderr_log=str(tmp_path / "sessions" / "manual" / "stderr.jsonl"),
        )
    )
    return store.mark_running(session.id, pid=pid, pgid=pgid)


def test_supervisor_runs_successful_command(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=["/bin/sh", "-lc", "printf OK"],
    )
    wait_until_done(supervisor, session.id)

    finished = supervisor.store.get_session(session.id)
    assert finished.status == SessionStatus.SUCCEEDED
    assert finished.exit_code == 0
    assert Path(finished.artifact_dir).exists()
    assert supervisor.logs.read(Path(finished.stdout_log)).entries[0].line == "OK"


def test_supervisor_marks_failed_command(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=["/bin/sh", "-lc", "printf nope >&2; exit 7"],
    )
    wait_until_done(supervisor, session.id)

    finished = supervisor.store.get_session(session.id)
    assert finished.status == SessionStatus.FAILED
    assert finished.exit_code == 7
    assert supervisor.logs.read(Path(finished.stderr_log)).entries[0].line == "nope"


def test_supervisor_records_launch_failure_for_empty_argv(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start(agent_id="shell", cwd=str(tmp_path), argv=[])

    finished = supervisor.store.get_session(session.id)
    events = supervisor.store.list_events(session.id)
    stderr = supervisor.logs.read(Path(finished.stderr_log)).entries
    sessions = supervisor.store.list_sessions()

    assert finished.status == SessionStatus.FAILED
    assert all(stored.status != SessionStatus.QUEUED for stored in sessions)
    assert events[-1].event_type == "launch_failed"
    assert "empty argv" in events[-1].message
    assert "empty argv" in stderr[-1].line


def test_supervisor_writes_session_json_after_terminal_state(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=["/bin/sh", "-lc", "printf metadata"],
        env={"AGENTIC_OS_SECRETISH": "not-written"},
    )
    wait_until_done(supervisor, session.id)

    finished = supervisor.store.get_session(session.id)
    session_json = Path(finished.stdout_log).parent / "session.json"
    payload = json.loads(session_json.read_text(encoding="utf-8"))

    assert payload["id"] == finished.id
    assert payload["status"] == "succeeded"
    assert payload["artifact_dir"] == finished.artifact_dir
    assert payload["stdout_log"] == finished.stdout_log
    assert payload["stderr_log"] == finished.stderr_log
    assert payload["session_dir"] == str(session_json.parent)
    assert "env" not in payload


def test_supervisor_retries_session_with_same_command(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=["/bin/sh", "-lc", "printf retry"],
    )
    wait_until_done(supervisor, session.id)

    retried = supervisor.retry(session.id)
    wait_until_done(supervisor, retried.id)

    finished = supervisor.store.get_session(retried.id)
    assert retried.id != session.id
    assert finished.agent_id == session.agent_id
    assert finished.cwd == session.cwd
    assert finished.argv == session.argv
    assert finished.status == SessionStatus.SUCCEEDED
    assert supervisor.logs.read(Path(finished.stdout_log)).entries[0].line == "retry"


def test_supervisor_rejects_retry_for_active_sessions(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)
    missing = missing_process_id()
    running = create_running_session(supervisor.store, tmp_path, pid=missing, pgid=missing)

    try:
        supervisor.retry(running.id)
        raise AssertionError("retry should reject running sessions")
    except ValueError:
        pass

    stopping = supervisor.store.mark_stopping(running.id)
    try:
        supervisor.retry(stopping.id)
        raise AssertionError("retry should reject stopping sessions")
    except ValueError:
        pass


def test_supervisor_stops_process_group(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)
    ready_path = tmp_path / "child-ready"

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=child_ignores_sigterm_argv(ready_path),
    )
    wait_until_file_exists(ready_path)
    running = supervisor.store.get_session(session.id)
    assert running.status == SessionStatus.RUNNING
    assert running.pgid is not None

    try:
        stopped = supervisor.stop(session.id, timeout_seconds=0.1)

        assert stopped.status == SessionStatus.STOPPED
        wait_until_process_group_gone(running.pgid)
    finally:
        cleanup_process_group(running.pgid, running.pid)


def test_supervisor_rejects_repeated_stop_of_stopped_session(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)
    missing_id = missing_process_id()
    session = create_running_session(
        supervisor.store,
        tmp_path,
        pid=missing_id,
        pgid=missing_id,
    )
    stopped = supervisor.store.mark_stopped(session.id)
    assert stopped.status == SessionStatus.STOPPED

    with pytest.raises(ValueError, match="Cannot stop terminal session"):
        supervisor.stop(session.id, timeout_seconds=0.1)


def test_stop_does_not_mark_stopped_before_process_group_is_gone(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)
    ready_path = tmp_path / "child-ready"

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=child_ignores_sigterm_argv(ready_path),
    )
    wait_until_file_exists(ready_path)
    running = supervisor.store.get_session(session.id)
    assert running.pid is not None
    assert running.pgid is not None

    stop_results: list[SessionRecord] = []
    stop_errors: list[BaseException] = []

    def stop_session() -> None:
        try:
            stop_results.append(supervisor.stop(session.id, timeout_seconds=1.0))
        except BaseException as exc:
            stop_errors.append(exc)

    stop_thread = threading.Thread(target=stop_session)

    try:
        stop_thread.start()
        wait_until_pid_gone(running.pid)
        assert process_group_exists(running.pgid)
        wait_until_session_status(supervisor, session.id, SessionStatus.STOPPING)

        stop_thread.join(timeout=3.0)

        assert not stop_thread.is_alive()
        assert not stop_errors
        assert stop_results[0].status == SessionStatus.STOPPED
        wait_until_process_group_gone(running.pgid)
        assert supervisor.store.get_session(session.id).status == SessionStatus.STOPPED
    finally:
        cleanup_process_group(running.pgid, running.pid)
        stop_thread.join(timeout=3.0)


def test_waiter_keeps_session_running_when_root_exits_but_group_is_alive(
    tmp_path: Path,
) -> None:
    supervisor = make_supervisor(tmp_path)
    ready_path = tmp_path / "child-ready"

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=parent_exits_child_stays_argv(ready_path),
    )
    wait_until_file_exists(ready_path)
    running = supervisor.store.get_session(session.id)
    assert running.pid is not None
    assert running.pgid is not None

    try:
        wait_until_pid_gone(running.pid)
        wait_until_event_or_terminal(
            supervisor,
            session.id,
            "root_exited_but_group_alive",
        )

        observed = supervisor.store.get_session(session.id)
        events = supervisor.store.list_events(session.id)
        assert observed.status == SessionStatus.RUNNING
        assert process_group_exists(running.pgid)
        assert events[-1].event_type == "root_exited_but_group_alive"

        stopped = supervisor.stop(session.id, timeout_seconds=0.1)

        assert stopped.status == SessionStatus.STOPPED
        wait_until_process_group_gone(running.pgid)
    finally:
        cleanup_process_group(running.pgid, running.pid)


def test_waiter_settles_success_when_root_exits_and_child_later_exits(
    tmp_path: Path,
) -> None:
    supervisor = make_supervisor(tmp_path)
    ready_path = tmp_path / "child-ready"

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=parent_exits_child_finishes_argv(ready_path, exit_code=0),
    )
    wait_until_file_exists(ready_path)
    running = supervisor.store.get_session(session.id)
    assert running.pgid is not None

    try:
        wait_until_done(supervisor, session.id)

        finished = supervisor.store.get_session(session.id)
        assert finished.status == SessionStatus.SUCCEEDED
        assert finished.exit_code == 0
        wait_until_process_group_gone(running.pgid)

        supervisor.reconcile()

        reconciled = supervisor.store.get_session(session.id)
        assert reconciled.status == SessionStatus.SUCCEEDED
        assert reconciled.exit_code == 0
    finally:
        cleanup_process_group(running.pgid, running.pid)


def test_waiter_settles_failure_when_root_fails_and_child_later_exits(
    tmp_path: Path,
) -> None:
    supervisor = make_supervisor(tmp_path)
    ready_path = tmp_path / "child-ready"

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=parent_exits_child_finishes_argv(ready_path, exit_code=7),
    )
    wait_until_file_exists(ready_path)
    running = supervisor.store.get_session(session.id)
    assert running.pgid is not None

    try:
        wait_until_done(supervisor, session.id)

        finished = supervisor.store.get_session(session.id)
        assert finished.status == SessionStatus.FAILED
        assert finished.exit_code == 7
        wait_until_process_group_gone(running.pgid)

        supervisor.reconcile()

        reconciled = supervisor.store.get_session(session.id)
        assert reconciled.status == SessionStatus.FAILED
        assert reconciled.exit_code == 7
    finally:
        cleanup_process_group(running.pgid, running.pid)


def test_reconcile_marks_missing_running_session_failed(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)
    missing = missing_process_id()
    session = create_running_session(supervisor.store, tmp_path, pid=missing, pgid=missing)

    supervisor.reconcile()

    reconciled = supervisor.store.get_session(session.id)
    events = supervisor.store.list_events(session.id)
    assert reconciled.status == SessionStatus.FAILED
    assert events[-1].event_type == "daemon_reconciled_missing_process"


def test_reconcile_settles_recorded_root_exit_when_process_group_is_gone(
    tmp_path: Path,
) -> None:
    supervisor = make_supervisor(tmp_path)
    missing = missing_process_id()
    session = create_running_session(supervisor.store, tmp_path, pid=missing, pgid=missing)
    supervisor.store.record_root_exit(session.id, exit_code=7)

    supervisor.reconcile()

    reconciled = supervisor.store.get_session(session.id)
    events = supervisor.store.list_events(session.id)
    assert reconciled.status == SessionStatus.FAILED
    assert reconciled.exit_code == 7
    assert not events


def test_reconcile_keeps_running_session_when_pgid_is_alive(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)
    ready_path = tmp_path / "orphan-ready"
    pid, pgid = orphaned_child_process_group(ready_path)
    session = create_running_session(supervisor.store, tmp_path, pid=pid, pgid=pgid)

    try:
        supervisor.reconcile()

        reconciled = supervisor.store.get_session(session.id)
        assert reconciled.status == SessionStatus.RUNNING

        restarted_store = Store(tmp_path / "agentic-os.db")
        restarted_store.init()
        restarted = ProcessSupervisor(
            store=restarted_store,
            logs=JsonlLogStore(),
            state_dir=tmp_path,
        )
        stopped = restarted.stop(session.id, timeout_seconds=0.1)

        assert stopped.status == SessionStatus.STOPPED
        wait_until_process_group_gone(pgid)
    finally:
        cleanup_process_group(pgid, pid)


def test_reconcile_repairs_terminal_session_with_live_process_group(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)
    ready_path = tmp_path / "orphan-ready"
    pid, pgid = orphaned_child_process_group(ready_path)
    session = create_running_session(supervisor.store, tmp_path, pid=pid, pgid=pgid)
    supervisor.store.mark_finished(session.id, exit_code=0)

    try:
        supervisor.reconcile()

        repaired = supervisor.store.get_session(session.id)
        events = supervisor.store.list_events(session.id)
        assert repaired.status == SessionStatus.RUNNING
        assert process_group_exists(pgid)
        assert events[-1].event_type == "terminal_state_repaired_live_process_group"

        stopped = supervisor.stop(session.id, timeout_seconds=0.1)

        assert stopped.status == SessionStatus.STOPPED
        wait_until_process_group_gone(pgid)
    finally:
        cleanup_process_group(pgid, pid)


def test_reconcile_preserves_exit_code_when_repaired_group_later_exits(
    tmp_path: Path,
) -> None:
    supervisor = make_supervisor(tmp_path)
    ready_path = tmp_path / "orphan-ready"
    pid, pgid = orphaned_child_finishes_process_group(ready_path)
    session = create_running_session(supervisor.store, tmp_path, pid=pid, pgid=pgid)
    supervisor.store.mark_finished(session.id, exit_code=7)

    try:
        supervisor.reconcile()

        repaired = supervisor.store.get_session(session.id)
        assert repaired.status == SessionStatus.RUNNING
        assert repaired.exit_code == 7
        assert process_group_exists(pgid)

        wait_until_process_group_gone(pgid)
        supervisor.reconcile()

        settled = supervisor.store.get_session(session.id)
        assert settled.status == SessionStatus.FAILED
        assert settled.exit_code == 7
    finally:
        cleanup_process_group(pgid, pid)


def test_retry_rejects_stale_terminal_session_with_live_process_group(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)
    ready_path = tmp_path / "orphan-ready"
    pid, pgid = orphaned_child_process_group(ready_path)
    session = create_running_session(
        supervisor.store,
        tmp_path,
        pid=pid,
        pgid=pgid,
        argv=["/bin/sh", "-lc", "printf stale"],
    )
    supervisor.store.mark_finished(session.id, exit_code=0)
    session_ids_before = {stored.id for stored in supervisor.store.list_sessions()}

    try:
        try:
            supervisor.retry(session.id)
            raise AssertionError("retry should reject stale terminal live-pgid sessions")
        except ValueError:
            pass

        repaired = supervisor.store.get_session(session.id)
        session_ids_after = {stored.id for stored in supervisor.store.list_sessions()}
        assert repaired.status == SessionStatus.RUNNING
        assert session_ids_after == session_ids_before
        assert process_group_exists(pgid)
    finally:
        cleanup_process_group(pgid, pid)


def test_reconcile_keeps_stopping_session_when_pgid_is_alive(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)
    ready_path = tmp_path / "orphan-ready"
    pid, pgid = orphaned_child_process_group(ready_path)
    session = create_running_session(supervisor.store, tmp_path, pid=pid, pgid=pgid)
    supervisor.store.mark_stopping(session.id)

    try:
        supervisor.reconcile()

        reconciled = supervisor.store.get_session(session.id)
        assert reconciled.status == SessionStatus.STOPPING
        assert process_group_exists(pgid)

        restarted_store = Store(tmp_path / "agentic-os.db")
        restarted_store.init()
        restarted = ProcessSupervisor(
            store=restarted_store,
            logs=JsonlLogStore(),
            state_dir=tmp_path,
        )
        stopped = restarted.stop(session.id, timeout_seconds=0.1)

        assert stopped.status == SessionStatus.STOPPED
        wait_until_process_group_gone(pgid)
    finally:
        cleanup_process_group(pgid, pid)


def test_supervisor_stops_persisted_process_group_after_restart(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)
    ready_path = tmp_path / "child-ready"

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=child_ignores_sigterm_argv(ready_path),
    )
    wait_until_file_exists(ready_path)
    running = supervisor.store.get_session(session.id)
    assert running.status == SessionStatus.RUNNING
    assert running.pid is not None
    assert running.pgid is not None

    restarted_store = Store(tmp_path / "agentic-os.db")
    restarted_store.init()
    restarted = ProcessSupervisor(
        store=restarted_store,
        logs=JsonlLogStore(),
        state_dir=tmp_path,
    )

    try:
        stopped = restarted.stop(session.id, timeout_seconds=0.1)

        assert stopped.status == SessionStatus.STOPPED
        wait_until_process_group_gone(running.pgid)
    finally:
        cleanup_process_group(running.pgid, running.pid)
