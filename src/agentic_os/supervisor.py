from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import TextIO

from agentic_os.attach import capture_external_session_after_run
from agentic_os.logs import JsonlLogStore, StreamName
from agentic_os.models import SessionCreate, SessionRecord, SessionStatus
from agentic_os.registry import Registry
from agentic_os.storage import Store
from agentic_os.usage import UsageRecord, UsageStore, parse_logs_for_usage, read_usage_parser

log = logging.getLogger(__name__)


TERMINAL_STATUSES = {
    SessionStatus.SUCCEEDED,
    SessionStatus.FAILED,
    SessionStatus.STOPPED,
}


class LaunchFailure(ValueError):
    pass


class ProcessSupervisor:
    def __init__(
        self,
        store: Store,
        logs: JsonlLogStore,
        state_dir: Path,
        registry: Registry | None = None,
        usage_store: UsageStore | None = None,
    ) -> None:
        self.store = store
        self.logs = logs
        self.state_dir = state_dir
        self.registry = registry
        self.usage_store = usage_store
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._reader_threads: dict[str, list[threading.Thread]] = {}
        self._lock = threading.Lock()

    def start_rejected(
        self,
        agent_id: str,
        cwd: str,
        argv: list[str],
        env: dict[str, str] | None = None,
        *,
        resolved_profile: str | None = None,
        resolved_provider: str | None = None,
        resolved_model: str | None = None,
    ) -> SessionRecord:
        session_env = env or {}
        session_dir = self.state_dir / "sessions" / "pending"
        session = self.store.create_session(
            SessionCreate(
                agent_id=agent_id,
                cwd=cwd,
                argv=argv,
                env=session_env,
                artifact_dir=str(session_dir / "artifacts"),
                stdout_log=str(session_dir / "stdout.jsonl"),
                stderr_log=str(session_dir / "stderr.jsonl"),
                resolved_profile=resolved_profile,
                resolved_provider=resolved_provider,
                resolved_model=resolved_model,
            )
        )
        session_dir = self.state_dir / "sessions" / session.id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        self._move_session_paths(session.id, session_dir)
        session = self.store.get_session(session.id)
        Path(session.stdout_log).touch()
        Path(session.stderr_log).touch()
        return self.store.mark_failed(session.id)

    def start(
        self,
        agent_id: str,
        cwd: str,
        argv: list[str],
        env: dict[str, str] | None = None,
        *,
        resolved_profile: str | None = None,
        resolved_provider: str | None = None,
        resolved_model: str | None = None,
    ) -> SessionRecord:
        session_env = env or {}
        session_dir = self.state_dir / "sessions" / "pending"
        session = self.store.create_session(
            SessionCreate(
                agent_id=agent_id,
                cwd=cwd,
                argv=argv,
                env=session_env,
                artifact_dir=str(session_dir / "artifacts"),
                stdout_log=str(session_dir / "stdout.jsonl"),
                stderr_log=str(session_dir / "stderr.jsonl"),
                resolved_profile=resolved_profile,
                resolved_provider=resolved_provider,
                resolved_model=resolved_model,
            )
        )
        session_dir = self.state_dir / "sessions" / session.id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        self._move_session_paths(session.id, session_dir)
        session = self.store.get_session(session.id)
        Path(session.stdout_log).touch()
        Path(session.stderr_log).touch()

        try:
            _validate_argv(argv)
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=_child_env(session.env),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except (OSError, LaunchFailure) as exc:
            self.store.record_event(session.id, "launch_failed", str(exc), {"argv": argv})
            self.logs.append(Path(session.stderr_log), session.id, "stderr", str(exc))
            return self.store.mark_failed(session.id)

        # start_new_session=True makes the child the leader of its own process group.
        # Using pid avoids a race where a very short command exits before os.getpgid().
        pgid = process.pid
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
        current = self._repair_terminal_live_process_group(current)
        if current.status in TERMINAL_STATUSES:
            raise ValueError(
                f"Cannot stop terminal session {session_id} with status {current.status.value}"
            )
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

    def get_retryable(self, session_id: str) -> SessionRecord:
        previous = self._repair_terminal_live_process_group(self.store.get_session(session_id))
        if previous.status not in TERMINAL_STATUSES:
            raise ValueError(
                f"Cannot retry active session {session_id} with status {previous.status.value}"
            )
        return previous

    def retry(self, session_id: str) -> SessionRecord:
        previous = self.get_retryable(session_id)
        return self.start(
            previous.agent_id,
            previous.cwd,
            previous.argv,
            env=previous.env,
            resolved_profile=previous.resolved_profile,
            resolved_provider=previous.resolved_provider,
            resolved_model=previous.resolved_model,
        )

    def reconcile(self) -> None:
        for session in self.store.list_sessions():
            session = self._repair_terminal_live_process_group(session)
            if session.status not in {SessionStatus.RUNNING, SessionStatus.STOPPING}:
                continue
            if _session_process_exists(session):
                continue
            if session.status == SessionStatus.RUNNING and session.exit_code is not None:
                self.store.mark_finished(session.id, session.exit_code)
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
        if current.status == SessionStatus.RUNNING:
            if current.pgid is not None and _process_group_exists(current.pgid):
                try:
                    current = self.store.record_root_exit(session_id, exit_code)
                except ValueError:
                    current = self.store.get_session(session_id)
                    if current.status != SessionStatus.RUNNING:
                        self._cleanup_process_tracking(session_id)
                        return
                    raise
                self.store.record_event(
                    session_id,
                    "root_exited_but_group_alive",
                    "root process exited while process group is still alive",
                    {"pid": process.pid, "pgid": current.pgid, "exit_code": exit_code},
                )
                self._wait_until_process_group_gone(current.pgid, timeout_seconds=None)
                current = self.store.get_session(session_id)
                if current.status == SessionStatus.RUNNING:
                    self.store.mark_finished(session_id, exit_code)
            else:
                self.store.mark_finished(session_id, exit_code)

        self._cleanup_process_tracking(session_id)
        has_attach_command = False
        if self.registry is not None:
            try:
                has_attach_command = bool(self.registry.get(current.agent_id).attach_command)
            except KeyError:
                has_attach_command = False
        capture_external_session_after_run(
            self.store,
            session_id,
            has_attach_command=has_attach_command,
        )
        try:
            self._collect_usage_for_session(session_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to collect usage for %s: %s", session_id, exc)

    def _collect_usage_for_session(self, session_id: str) -> None:
        if self.usage_store is None:
            return
        session = self.store.get_session(session_id)
        lines = parse_logs_for_usage(
            [Path(session.stdout_log), Path(session.stderr_log)],
        )
        parser = read_usage_parser(session.agent_id)
        usage = parser.extract(
            session_id=session_id,
            harness_id=session.agent_id,
            lines=lines,
        )
        usage = UsageRecord(
            session_id=usage.session_id,
            harness_id=usage.harness_id,
            provider=session.resolved_provider or usage.provider or "N/A",
            model=session.resolved_model or usage.model or "N/A",
            run_profile=session.resolved_profile or usage.run_profile or "default",
            cwd=session.cwd,
            started_at=session.started_at or usage.started_at or "N/A",
            ended_at=session.ended_at or usage.ended_at or "N/A",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=usage.cost_usd,
            currency=usage.currency,
            source=usage.source,
            raw_evidence=usage.raw_evidence,
        )
        self.usage_store.upsert(usage)

    def _cleanup_process_tracking(self, session_id: str) -> None:
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

    def _repair_terminal_live_process_group(self, session: SessionRecord) -> SessionRecord:
        if (
            session.status not in TERMINAL_STATUSES
            or session.pgid is None
            or not _process_group_exists(session.pgid)
        ):
            return session

        self.store.record_event(
            session.id,
            "terminal_state_repaired_live_process_group",
            "terminal session still has a live process group",
            {"pid": session.pid, "pgid": session.pgid, "status": session.status.value},
        )
        return self.store.repair_running(session.id)

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

    def _wait_until_process_group_gone(self, pgid: int, timeout_seconds: float | None) -> bool:
        deadline = None if timeout_seconds is None else time.time() + timeout_seconds
        while deadline is None or time.time() < deadline:
            if not _process_group_exists(pgid):
                return True
            time.sleep(0.05)
        return not _process_group_exists(pgid)

    def _move_session_paths(self, session_id: str, session_dir: Path) -> None:
        self.store.update_session_paths(
            session_id,
            artifact_dir=str(session_dir / "artifacts"),
            stdout_log=str(session_dir / "stdout.jsonl"),
            stderr_log=str(session_dir / "stderr.jsonl"),
        )


def _validate_argv(argv: list[str]) -> None:
    if not argv:
        raise LaunchFailure("empty argv cannot be launched")
    if argv[0] == "":
        raise LaunchFailure("empty executable path in argv[0]")


def _child_env(env: dict[str, str]) -> dict[str, str] | None:
    if not env:
        return None
    return {**os.environ, **env}


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
