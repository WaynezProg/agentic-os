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
from pydantic import BaseModel, Field

from agentic_os.control_plane import (
    ControlPlaneStore,
    McpServerUpsert,
    PolicyEvaluationRequest,
    PolicyEvaluationResult,
    PolicyUpsert,
    SkillUpsert,
)
from agentic_os.logs import JsonlLogStore, StreamName
from agentic_os.memory import build_session_summary
from agentic_os.memory_store import MemoryStore, SessionSummaryRecord
from agentic_os.models import SessionRecord
from agentic_os.registry import Registry, RenderedRun
from agentic_os.storage import Store
from agentic_os.supervisor import ProcessSupervisor


SESSION_START_APPROVAL_TOOL = "session.start"


class SessionRunRequest(BaseModel):
    agent_id: str
    cwd: str | None = None
    message: str


class SkillUpsertRequest(BaseModel):
    label: str
    description: str = ""
    source: str = "local"
    entrypoint: str = ""
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True


class McpServerUpsertRequest(BaseModel):
    label: str
    description: str = ""
    transport: str = "stdio"
    command_preview: list[str] = Field(default_factory=list)
    url: str | None = None
    env_keys: list[str] = Field(default_factory=list)
    enabled: bool = True


class PolicyUpsertRequest(BaseModel):
    enabled: bool = True
    readonly: bool = False
    allowed_skill_ids: list[str] = Field(default_factory=list)
    allowed_mcp_server_ids: list[str] = Field(default_factory=list)
    allowed_tool_names: list[str] = Field(default_factory=list)
    approval_required_tool_names: list[str] = Field(default_factory=list)
    allowed_model_ids: list[str] = Field(default_factory=list)
    cwd_roots: list[str] = Field(default_factory=list)
    rate_limit_per_minute: int = 60


class PolicyEvaluateRequest(BaseModel):
    agent_id: str
    skill_id: str | None = None
    mcp_server_id: str | None = None
    tool_name: str | None = None
    model_id: str | None = None
    cwd: str | None = None


def create_app(state_dir: Path, registry_path: Path) -> FastAPI:
    state_dir.mkdir(parents=True, exist_ok=True)
    registry = Registry(registry_path)
    store = Store(state_dir / "agentic-os.db")
    store.init()
    memory_store = MemoryStore(state_dir / "agentic-os.db")
    memory_store.init()
    control_plane = ControlPlaneStore(state_dir / "agentic-os.db")
    control_plane.init()
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

        policy_result = _evaluate_session_policy(rendered.agent.id, rendered.cwd)
        if policy_result is not None and policy_result.decision != "allow":
            return _reject_session(rendered, policy_result)

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

    @app.get("/sessions/{session_id}/events")
    def session_events(session_id: str) -> dict[str, object]:
        try:
            store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        events = store.list_events(session_id)
        return {"events": [event.model_dump() for event in events]}

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
        return {"skills": [_asdict(skill) for skill in control_plane.list_skills()]}

    @app.get("/skills/{skill_id}")
    def show_skill(skill_id: str) -> dict[str, Any]:
        try:
            return _asdict(control_plane.get_skill(skill_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/skills/{skill_id}")
    def upsert_skill(skill_id: str, request: SkillUpsertRequest) -> dict[str, Any]:
        try:
            return _asdict(
                control_plane.upsert_skill(
                    skill_id,
                    SkillUpsert(
                        label=request.label,
                        description=request.description,
                        source=request.source,
                        entrypoint=request.entrypoint,
                        tags=request.tags,
                        enabled=request.enabled,
                    ),
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/skills/{skill_id}/disable")
    def disable_skill(skill_id: str) -> dict[str, Any]:
        try:
            return _asdict(control_plane.disable_skill(skill_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/mcp")
    def list_mcp_servers() -> dict[str, object]:
        return {"servers": [_asdict(server) for server in control_plane.list_mcp_servers()]}

    @app.get("/mcp/{server_id}")
    def show_mcp_server(server_id: str) -> dict[str, Any]:
        try:
            return _asdict(control_plane.get_mcp_server(server_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/mcp/{server_id}")
    def upsert_mcp_server(server_id: str, request: McpServerUpsertRequest) -> dict[str, Any]:
        try:
            return _asdict(
                control_plane.upsert_mcp_server(
                    server_id,
                    McpServerUpsert(
                        label=request.label,
                        description=request.description,
                        transport=request.transport,
                        command_preview=request.command_preview,
                        url=request.url,
                        env_keys=request.env_keys,
                        enabled=request.enabled,
                    ),
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/mcp/{server_id}/disable")
    def disable_mcp_server(server_id: str) -> dict[str, Any]:
        try:
            return _asdict(control_plane.disable_mcp_server(server_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/policy")
    def list_policies() -> dict[str, object]:
        return {"policies": [_asdict(policy) for policy in control_plane.list_policies()]}

    @app.post("/policy/evaluate")
    def evaluate_policy(request: PolicyEvaluateRequest) -> dict[str, Any]:
        try:
            return _asdict(
                control_plane.evaluate_policy(
                    PolicyEvaluationRequest(
                        agent_id=request.agent_id,
                        skill_id=request.skill_id,
                        mcp_server_id=request.mcp_server_id,
                        tool_name=request.tool_name,
                        model_id=request.model_id,
                        cwd=request.cwd,
                    )
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/policy/{agent_id}")
    def show_policy(agent_id: str) -> dict[str, Any]:
        try:
            return _asdict(control_plane.get_policy(agent_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/policy/{agent_id}")
    def upsert_policy(agent_id: str, request: PolicyUpsertRequest) -> dict[str, Any]:
        try:
            return _asdict(
                control_plane.upsert_policy(
                    agent_id,
                    PolicyUpsert(
                        enabled=request.enabled,
                        readonly=request.readonly,
                        allowed_skill_ids=request.allowed_skill_ids,
                        allowed_mcp_server_ids=request.allowed_mcp_server_ids,
                        allowed_tool_names=request.allowed_tool_names,
                        approval_required_tool_names=request.approval_required_tool_names,
                        allowed_model_ids=request.allowed_model_ids,
                        cwd_roots=request.cwd_roots,
                        rate_limit_per_minute=request.rate_limit_per_minute,
                    ),
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    def _evaluate_session_policy(
        agent_id: str, cwd: str
    ) -> PolicyEvaluationResult | None:
        try:
            policy = control_plane.get_policy(agent_id)
        except (KeyError, ValueError):
            return None
        result = control_plane.evaluate_policy(
            PolicyEvaluationRequest(agent_id=agent_id, cwd=cwd)
        )
        if result.decision == "allow" and _requires_session_start_approval(
            policy.approval_required_tool_names
        ):
            return PolicyEvaluationResult(
                agent_id=agent_id,
                decision="approval_required",
                reason=f"{SESSION_START_APPROVAL_TOOL} requires approval for {agent_id}",
                readonly=result.readonly,
                rate_limit_per_minute=result.rate_limit_per_minute,
            )
        return result

    def _requires_session_start_approval(tool_names: list[str]) -> bool:
        return "*" in tool_names or SESSION_START_APPROVAL_TOOL in tool_names

    def _reject_session(
        rendered: RenderedRun, result: PolicyEvaluationResult
    ) -> JSONResponse:
        session = supervisor.start_rejected(
            rendered.agent.id, rendered.cwd, rendered.argv, env=rendered.env
        )
        event_type = (
            "policy_denied"
            if result.decision == "deny"
            else "policy_approval_required"
        )
        store.record_event(
            session.id,
            event_type,
            result.reason,
            {"decision": result.decision, "agent_id": result.agent_id},
        )
        status_code = 403 if result.decision == "deny" else 409
        return JSONResponse(
            status_code=status_code,
            content={
                "detail": result.reason,
                "decision": result.decision,
                "session_id": session.id,
            },
        )

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
