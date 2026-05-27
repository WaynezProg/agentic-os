import os
import signal
import time
from pathlib import Path

from agentic_os.logs import JsonlLogStore
from agentic_os.models import SessionStatus
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


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def cleanup_process_group(pgid: int | None, pid: int | None) -> None:
    if pid is None or not pid_exists(pid):
        return
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    wait_until_pid_gone(pid)


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
    assert supervisor.logs.read(Path(finished.stdout_log))[0].line == "OK"


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
    assert supervisor.logs.read(Path(finished.stderr_log))[0].line == "nope"


def test_supervisor_stops_process_group(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=["/bin/sh", "-lc", "sleep 10"],
    )
    running = supervisor.store.get_session(session.id)
    assert running.status == SessionStatus.RUNNING

    try:
        stopped = supervisor.stop(session.id, timeout_seconds=0.1)

        assert stopped.status == SessionStatus.STOPPED
        assert running.pid is not None
        wait_until_pid_gone(running.pid)
    finally:
        cleanup_process_group(running.pgid, running.pid)


def test_supervisor_stops_persisted_process_group_after_restart(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)

    session = supervisor.start(
        agent_id="shell",
        cwd=str(tmp_path),
        argv=["/bin/sh", "-lc", "sleep 10"],
    )
    running = supervisor.store.get_session(session.id)
    assert running.status == SessionStatus.RUNNING
    assert running.pid is not None

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
        wait_until_pid_gone(running.pid)
    finally:
        cleanup_process_group(running.pgid, running.pid)
