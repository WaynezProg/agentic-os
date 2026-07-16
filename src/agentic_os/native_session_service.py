from __future__ import annotations

import shlex
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from agentic_os.attach import DiscoveredSession, scan_external_sessions
from agentic_os.live_sessions import (
    LiveSession,
    default_roots,
    read_transcript_tail,
    scan_live_sessions_with_stats,
)
from agentic_os.models import AgentDefinition


class NativeSessionRecord(BaseModel):
    identity: str
    environment_id: str
    session_id: str
    workspace: str
    title: str
    started_at: str | None
    last_activity_at: str
    active: bool
    source: str | None
    log_path: str
    resume_command: str

    def live_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="json", exclude={"identity", "environment_id"})
        return {"tool": self.environment_id, **payload}

    def discovery_payload(self) -> dict[str, object]:
        return {
            "agent_id": self.environment_id,
            "external_session_id": self.session_id,
            "log_path": self.log_path,
            "started_at": self.started_at,
        }


class NativeSessionScan(BaseModel):
    sessions: list[NativeSessionRecord] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    files_examined: int = 0


class NativeSessionService:
    def __init__(
        self,
        roots: dict[str, Path] | None = None,
        *,
        agents_provider: Callable[[], list[AgentDefinition]] | None = None,
        max_files: int = 500,
    ) -> None:
        self.roots = default_roots()
        if roots:
            self.roots.update(roots)
        self.agents_provider = agents_provider or (lambda: [])
        self.max_files = max(1, max_files)

    def scan(
        self,
        *,
        environment_id: str | None = None,
        workspace: str | None = None,
        within_hours: int = 72,
        limit: int = 50,
        now: datetime | None = None,
        include_registered: bool = False,
    ) -> NativeSessionScan:
        records: list[NativeSessionRecord] = []
        files_examined = 0
        if include_registered and workspace:
            agents = [
                agent
                for agent in self.agents_provider()
                if environment_id is None or agent.id == environment_id
            ]
            discovered = scan_external_sessions(
                workspace_path=workspace,
                agents=agents,
                max_files=self.max_files,
            )
            files_examined += discovered.files_examined
            by_id = {agent.id: agent for agent in agents}
            records.extend(
                self._normalize_external(item, workspace, by_id.get(item.agent_id))
                for item in discovered.sessions
            )

        errors: list[dict[str, str]] = []
        remaining = self.max_files - files_examined
        if remaining > 0:
            live, errors, live_examined = scan_live_sessions_with_stats(
                self.roots,
                within_hours=within_hours,
                limit=remaining,
                now=now,
                max_files=remaining,
            )
            files_examined += live_examined
            records.extend(
                self._normalize_live(session)
                for session in live
                if (environment_id is None or session.tool == environment_id)
                and (workspace is None or self._same_workspace(session.workspace, workspace))
            )

        deduplicated: dict[tuple[str, str, str], NativeSessionRecord] = {}
        for record in records:
            key = (record.environment_id, record.session_id, record.log_path)
            deduplicated.setdefault(key, record)
        ordered = sorted(
            deduplicated.values(),
            key=lambda item: item.last_activity_at,
            reverse=True,
        )
        return NativeSessionScan(
            sessions=ordered[: max(1, limit)],
            errors=errors,
            files_examined=files_examined,
        )

    def is_known_log_path(self, environment_id: str, log_path: str | Path) -> bool:
        try:
            resolved = Path(log_path).expanduser().resolve()
        except (OSError, ValueError):
            return False
        if resolved.suffix != ".jsonl" or not resolved.is_file():
            return False

        roots: list[Path] = []
        native_root = self.roots.get(environment_id)
        if native_root is not None:
            roots.append(native_root)
        roots.extend(
            Path(path).expanduser()
            for agent in self.agents_provider()
            if agent.id == environment_id
            for path in agent.log_paths
        )
        for root in roots:
            try:
                if root.is_dir() and resolved.is_relative_to(root.resolve()):
                    return True
            except (OSError, ValueError):
                continue
        return False

    def read_transcript(
        self,
        environment_id: str,
        log_path: str | Path,
        *,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        if not self.is_known_log_path(environment_id, log_path):
            raise ValueError(f"log_path outside {environment_id} session roots")
        return read_transcript_tail(Path(log_path).expanduser().resolve(), environment_id, limit=limit)

    @staticmethod
    def _same_workspace(left: str, right: str) -> bool:
        try:
            return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
        except (OSError, ValueError):
            return left == right

    @staticmethod
    def _normalize_live(session: LiveSession) -> NativeSessionRecord:
        return NativeSessionRecord(
            identity=f"{session.tool}:{session.session_id}",
            environment_id=session.tool,
            session_id=session.session_id,
            workspace=session.workspace,
            title=session.title,
            started_at=session.started_at,
            last_activity_at=session.last_activity_at,
            active=session.active,
            source=session.source,
            log_path=session.log_path,
            resume_command=session.resume_command,
        )

    @staticmethod
    def _normalize_external(
        session: DiscoveredSession,
        workspace: str,
        agent: AgentDefinition | None,
    ) -> NativeSessionRecord:
        try:
            last_activity = datetime.fromtimestamp(
                Path(session.log_path).stat().st_mtime,
                tz=timezone.utc,
            ).isoformat()
        except OSError:
            last_activity = session.started_at or datetime.now(tz=timezone.utc).isoformat()
        command = [*(agent.attach_command or [])] if agent else []
        if command:
            command.append(session.external_session_id)
        return NativeSessionRecord(
            identity=f"{session.agent_id}:{session.external_session_id}",
            environment_id=session.agent_id,
            session_id=session.external_session_id,
            workspace=workspace,
            title="(external session)",
            started_at=session.started_at,
            last_activity_at=last_activity,
            active=False,
            source="registered_log_path",
            log_path=session.log_path,
            resume_command=shlex.join(command) if command else "",
        )
