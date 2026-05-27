import os
import signal
import subprocess
import sys
import time
from pathlib import Path

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
        "import signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(10)"
    )
    parent_code = (
        "import pathlib, signal, subprocess, sys, time; "
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); "
        f"subprocess.Popen([{sys.executable!r}, '-c', {child_code!r}]); "
        "pathlib.Path(sys.argv[1]).write_text('ready', encoding='utf-8'); "
        "time.sleep(10)"
    )
    return [sys.executable, "-c", parent_code, str(ready_path)]


def orphaned_child_process_group(ready_path: Path) -> tuple[int, int]:
    child_code = (
        "import signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(10)"
    )
    parent_code = (
        "import pathlib, subprocess, sys; "
        f"subprocess.Popen([{sys.executable!r}, '-c', {child_code!r}]); "
        "pathlib.Path(sys.argv[1]).write_text('ready', encoding='utf-8')"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", parent_code, str(ready_path)],
        start_new_session=True,
    )
    pgid = os.getpgid(process.pid)
    wait_until_file_exists(ready_path)
    process.wait(timeout=2.0)
    return process.pid, pgid


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
    assert supervisor.logs.read(Path(finished.stdout_log))[0].line == "retry"


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


def test_reconcile_marks_missing_running_session_failed(tmp_path: Path) -> None:
    supervisor = make_supervisor(tmp_path)
    missing = missing_process_id()
    session = create_running_session(supervisor.store, tmp_path, pid=missing, pgid=missing)

    supervisor.reconcile()

    reconciled = supervisor.store.get_session(session.id)
    events = supervisor.store.list_events(session.id)
    assert reconciled.status == SessionStatus.FAILED
    assert events[-1].event_type == "daemon_reconciled_missing_process"


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
