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
        session = self.store.mark_stopping(session_id)
        with self._lock:
            process = self._processes.get(session_id)
        if process is None or process.poll() is not None:
            return self._mark_stopped_once(session_id)

        pgid = session.pgid if session.pgid is not None else os.getpgid(process.pid)
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return self._mark_stopped_once(session_id)

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if process.poll() is not None:
                return self._mark_stopped_once(session_id)
            time.sleep(0.05)

        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return self._mark_stopped_once(session_id)
        self.store.record_event(session_id, "stop_escalated", "sent SIGKILL", {"pid": process.pid})
        return self._mark_stopped_once(session_id)

    def retry(self, session_id: str) -> SessionRecord:
        previous = self.store.get_session(session_id)
        return self.start(previous.agent_id, previous.cwd, previous.argv)

    def reconcile(self) -> None:
        for session in self.store.list_sessions():
            if session.status != SessionStatus.RUNNING or session.pid is None:
                continue
            if not _pid_exists(session.pid):
                self.store.record_event(
                    session.id,
                    "daemon_reconciled_missing_process",
                    "recorded pid is gone",
                    {"pid": session.pid},
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
