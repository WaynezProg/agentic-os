from __future__ import annotations

from dataclasses import asdict, is_dataclass
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agentic_os.logs import JsonlLogStore, StreamName
from agentic_os.memory import build_session_summary
from agentic_os.memory_store import MemoryStore, SessionSummaryRecord
from agentic_os.models import SessionRecord
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
    memory_store = MemoryStore(state_dir / "agentic-os.db")
    memory_store.init()
    logs = JsonlLogStore()
    supervisor = ProcessSupervisor(store=store, logs=logs, state_dir=state_dir)
    supervisor.reconcile()

    app = FastAPI(title="agentic-os")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        if request.method == "POST" and request.url.path == "/sessions":
            return JSONResponse(status_code=400, content={"detail": exc.errors()})
        return await request_validation_exception_handler(request, exc)

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session = supervisor.start(rendered.agent.id, rendered.cwd, rendered.argv, env=rendered.env)
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

    @app.post("/sessions/{session_id}/memory/summary")
    def create_session_memory_summary(session_id: str) -> dict[str, Any]:
        return _asdict(_build_and_store_summary(session_id))

    @app.get("/sessions/{session_id}/memory/summary")
    def show_session_memory_summary(session_id: str) -> dict[str, Any]:
        _get_session_or_404(session_id)
        try:
            return _asdict(memory_store.get_summary(session_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/memory/review")
    def create_session_memory_review(session_id: str) -> dict[str, Any]:
        summary = _get_or_create_summary(session_id)
        return _asdict(memory_store.create_review_item(summary))

    @app.get("/memory/review")
    def list_memory_review() -> dict[str, object]:
        return {"items": [_asdict(item) for item in memory_store.list_review_items()]}

    @app.post("/memory/review/{item_id}/approve")
    def approve_memory_review(item_id: str) -> dict[str, Any]:
        try:
            return _asdict(memory_store.approve_review_item(item_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/memory/review/{item_id}/reject")
    def reject_memory_review(item_id: str) -> dict[str, Any]:
        try:
            return _asdict(memory_store.reject_review_item(item_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/memory")
    def list_memories() -> dict[str, object]:
        return {"memories": [_asdict(memory) for memory in memory_store.list_memories()]}

    @app.get("/memory/search")
    def search_memories(q: str = Query(default="")) -> dict[str, object]:
        return {"memories": [_asdict(memory) for memory in memory_store.search_memories(q)]}

    @app.get("/skills")
    def list_skills() -> dict[str, object]:
        return {
            "skills": [
                {"id": "placeholder", "label": "Skills registry", "status": "placeholder"}
            ]
        }

    @app.get("/mcp")
    def list_mcp_servers() -> dict[str, object]:
        return {
            "servers": [
                {"id": "placeholder", "label": "MCP servers", "status": "placeholder"}
            ]
        }

    def _get_session_or_404(session_id: str) -> SessionRecord:
        try:
            return store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _build_and_store_summary(session_id: str) -> SessionSummaryRecord:
        session = _get_session_or_404(session_id)
        entries = logs.read_merged(Path(session.stdout_log), Path(session.stderr_log))
        return memory_store.upsert_summary(session, build_session_summary(session, entries))

    def _get_or_create_summary(session_id: str) -> SessionSummaryRecord:
        _get_session_or_404(session_id)
        try:
            return memory_store.get_summary(session_id)
        except KeyError:
            return _build_and_store_summary(session_id)

    return app


def _asdict(record: object) -> dict[str, Any]:
    if not is_dataclass(record):
        raise TypeError(f"Expected dataclass record, got {type(record).__name__}")
    return asdict(record)


def _wait_for_short_command(supervisor: ProcessSupervisor, session_id: str) -> None:
    for _ in range(20):
        session = supervisor.store.get_session(session_id)
        if session.status.value in {"succeeded", "failed", "stopped"}:
            return
        time.sleep(0.025)
