from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from agentic_os.logs import JsonlLogStore, StreamName
from agentic_os.registry import Registry
from agentic_os.storage import Store
from agentic_os.supervisor import ProcessSupervisor


class SessionRunRequest(BaseModel):
    agent_id: str
    cwd: str | None = None
    message: str


def create_app(state_dir: Path, registry_path: Path) -> FastAPI:
    state_dir.mkdir(parents=True, exist_ok=True)
    registry = Registry(registry_path)
    store = Store(state_dir / "agentic-os.db")
    store.init()
    logs = JsonlLogStore()
    supervisor = ProcessSupervisor(store=store, logs=logs, state_dir=state_dir)
    supervisor.reconcile()

    app = FastAPI(title="agentic-os")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/agents")
    def list_agents() -> dict[str, object]:
        return {"agents": [agent.model_dump() for agent in registry.list_agents()]}

    @app.get("/agents/{agent_id}")
    def show_agent(agent_id: str) -> dict[str, object]:
        try:
            return registry.get(agent_id).model_dump()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions")
    def run_session(request: SessionRunRequest) -> dict[str, object]:
        try:
            rendered = registry.build_run(request.agent_id, request.cwd, request.message)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session = supervisor.start(rendered.agent.id, rendered.cwd, rendered.argv)
        _wait_for_short_command(supervisor, session.id)
        return supervisor.store.get_session(session.id).model_dump()

    @app.get("/sessions")
    def list_sessions() -> dict[str, object]:
        return {"sessions": [session.model_dump() for session in store.list_sessions()]}

    @app.get("/sessions/{session_id}")
    def show_session(session_id: str) -> dict[str, object]:
        try:
            return store.get_session(session_id).model_dump()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/logs")
    def session_logs(
        session_id: str,
        stream: StreamName | None = None,
        after: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        try:
            session = store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        entries = logs.read_merged(
            Path(session.stdout_log),
            Path(session.stderr_log),
            stream=stream,
            after=after,
        )
        return {"entries": [entry.model_dump() for entry in entries]}

    @app.post("/sessions/{session_id}/stop")
    def stop_session(session_id: str) -> dict[str, object]:
        try:
            return supervisor.stop(session_id).model_dump()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/retry")
    def retry_session(session_id: str) -> dict[str, object]:
        try:
            session = supervisor.retry(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _wait_for_short_command(supervisor, session.id)
        return supervisor.store.get_session(session.id).model_dump()

    return app


def _wait_for_short_command(supervisor: ProcessSupervisor, session_id: str) -> None:
    for _ in range(20):
        session = supervisor.store.get_session(session_id)
        if session.status.value in {"succeeded", "failed", "stopped"}:
            return
        time.sleep(0.025)
