from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import TextIO

from agentic_os.logs import JsonlLogStore, StreamName
from agentic_os.models import SessionCreate, SessionRecord, SessionStatus
from agentic_os.storage import Store


class ProcessSupervisor:
    def __init__(self, store: Store, logs: JsonlLogStore, state_dir: Path) -> None:
        self.store = store
        self.logs = logs
        self.state_dir = state_dir
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._reader_threads: dict[str, list[threading.Thread]] = {}
        self._lock = threading.Lock()

    def start(self, agent_id: str, cwd: str, argv: list[str]) -> SessionRecord:
        session_dir = self.state_dir / "sessions" / "pending"
        session = self.store.create_session(
            SessionCreate(
                agent_id=agent_id,
                cwd=cwd,
                argv=argv,
                artifact_dir=str(session_dir / "artifacts"),
                stdout_log=str(session_dir / "stdout.jsonl"),
                stderr_log=str(session_dir / "stderr.jsonl"),
            )
        )
        session_dir = self.state_dir / "sessions" / session.id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        self._move_session_paths(session.id, session_dir)
        session = self.store.get_session(session.id)

        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            self.store.record_event(session.id, "launch_failed", str(exc), {"argv": argv})
            self.logs.append(Path(session.stderr_log), session.id, "stderr", str(exc))
            return self.store.mark_failed(session.id)

        pgid = os.getpgid(process.pid)
        with self._lock:
            self._processes[session.id] = process
        session = self.store.mark_running(session.id, pid=process.pid, pgid=pgid)

        reader_threads = [
            threading.Thread(
                target=self._pipe_reader,
                args=(session.id, process.stdout, Path(session.stdout_log), "stdout"),
                daemon=True,
            ),
            threading.Thread(
                target=self._pipe_reader,
                args=(session.id, process.stderr, Path(session.stderr_log), "stderr"),
                daemon=True,
            ),
        ]
        with self._lock:
            self._reader_threads[session.id] = reader_threads
        for thread in reader_threads:
            thread.start()

        threading.Thread(target=self._waiter, args=(session.id, process), daemon=True).start()
        return session

    def stop(self, session_id: str, timeout_seconds: float = 5.0) -> SessionRecord:
        current = self.store.get_session(session_id)
        if current.status == SessionStatus.STOPPED:
            return current
        if current.status == SessionStatus.STOPPING:
            session = current
        else:
            session = self.store.mark_stopping(session_id)

        with self._lock:
            process = self._processes.get(session_id)

        pgid = session.pgid
        metadata: dict[str, object] = {"pid": session.pid}
        if process is not None:
            metadata["pid"] = process.pid
            if pgid is None:
                pgid = os.getpgid(process.pid)

        if pgid is None:
            return self._mark_stop_failed(
                session.id,
                "missing process handle and pgid",
                metadata,
            )

        return self._terminate_process_group(session.id, pgid, timeout_seconds, metadata)

    def retry(self, session_id: str) -> SessionRecord:
        previous = self.store.get_session(session_id)
        return self.start(previous.agent_id, previous.cwd, previous.argv)

    def reconcile(self) -> None:
        for session in self.store.list_sessions():
            if session.status != SessionStatus.RUNNING:
                continue
            if _session_process_exists(session):
                continue
            self.store.record_event(
                session.id,
                "daemon_reconciled_missing_process",
                "recorded process is gone",
                {"pid": session.pid, "pgid": session.pgid},
            )
            self.store.mark_failed(session.id)

    def _pipe_reader(
        self,
        session_id: str,
        pipe: TextIO | None,
        path: Path,
        stream: StreamName,
    ) -> None:
        if pipe is None:
            return
        for raw_line in pipe:
            self.logs.append(path, session_id, stream, raw_line.rstrip("\n"))

    def _waiter(self, session_id: str, process: subprocess.Popen[str]) -> None:
        exit_code = process.wait()
        with self._lock:
            reader_threads = list(self._reader_threads.get(session_id, []))
        for thread in reader_threads:
            thread.join(timeout=1.0)

        current = self.store.get_session(session_id)
        if current.status == SessionStatus.STOPPING:
            self._mark_stopped_once(session_id)
        elif current.status == SessionStatus.RUNNING:
            self.store.mark_finished(session_id, exit_code)

        with self._lock:
            self._processes.pop(session_id, None)
            self._reader_threads.pop(session_id, None)

    def _mark_stopped_once(self, session_id: str) -> SessionRecord:
        try:
            return self.store.mark_stopped(session_id)
        except ValueError:
            current = self.store.get_session(session_id)
            if current.status == SessionStatus.STOPPED:
                return current
            raise

    def _mark_stop_failed(
        self,
        session_id: str,
        message: str,
        metadata: dict[str, object],
    ) -> SessionRecord:
        self.store.record_event(session_id, "stop_failed", message, metadata)
        return self.store.mark_failed(session_id)

    def _terminate_process_group(
        self,
        session_id: str,
        pgid: int,
        timeout_seconds: float,
        metadata: dict[str, object],
    ) -> SessionRecord:
        if not _process_group_exists(pgid):
            return self._mark_stopped_once(session_id)
        sigterm_sent = self._signal_process_group(
            session_id,
            pgid,
            signal.SIGTERM,
            metadata,
        )
        if not sigterm_sent:
            return self._mark_stopped_once(session_id)

        if self._wait_until_process_group_gone(pgid, timeout_seconds):
            return self._mark_stopped_once(session_id)

        sigkill_sent = self._signal_process_group(
            session_id,
            pgid,
            signal.SIGKILL,
            metadata,
        )
        if not sigkill_sent:
            return self._mark_stopped_once(session_id)
        self.store.record_event(
            session_id,
            "stop_escalated",
            "sent SIGKILL",
            {**metadata, "pgid": pgid},
        )
        if self._wait_until_process_group_gone(pgid, timeout_seconds):
            return self._mark_stopped_once(session_id)
        return self._mark_stop_failed(
            session_id,
            "process group survived SIGKILL",
            {**metadata, "pgid": pgid},
        )

    def _signal_process_group(
        self,
        session_id: str,
        pgid: int,
        signal_number: signal.Signals,
        metadata: dict[str, object],
    ) -> bool:
        try:
            os.killpg(pgid, signal_number)
            return True
        except ProcessLookupError:
            return False
        except (PermissionError, OSError) as exc:
            self._mark_stop_failed(
                session_id,
                f"failed to signal process group: {exc}",
                {**metadata, "pgid": pgid, "signal": signal_number.name},
            )
            raise

    def _wait_until_process_group_gone(self, pgid: int, timeout_seconds: float) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if not _process_group_exists(pgid):
                return True
            time.sleep(0.05)
        return not _process_group_exists(pgid)

    def _move_session_paths(self, session_id: str, session_dir: Path) -> None:
        with self.store.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET artifact_dir = ?, stdout_log = ?, stderr_log = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    str(session_dir / "artifacts"),
                    str(session_dir / "stdout.jsonl"),
                    str(session_dir / "stderr.jsonl"),
                    session_id,
                ),
            )


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _session_process_exists(session: SessionRecord) -> bool:
    if session.pgid is not None:
        return _process_group_exists(session.pgid)
    if session.pid is not None:
        return _pid_exists(session.pid)
    return False


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
