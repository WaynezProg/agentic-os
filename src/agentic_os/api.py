from __future__ import annotations

from dataclasses import asdict, is_dataclass
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agentic_os.approvals import ApprovalCreate, ApprovalRecord, ApprovalStatus, ApprovalStore
from agentic_os.audit import AuditEvent, AuditStore
from agentic_os.control_plane import (
    ControlPlaneStore,
    McpServerUpsert,
    PolicyEvaluationRequest,
    PolicyEvaluationResult,
    PolicyUpsert,
    SkillUpsert,
    SunsetChange,
)
from agentic_os.catalog import (
    SUPPORTED_HARNESSES,
    SurfaceRecord,
    diff as catalog_diff,
    merge as catalog_merge,
    scan as catalog_scan,
)
from agentic_os.harness_config import (
    diff as harness_config_diff,
    effective as harness_config_effective,
    explain as harness_config_explain,
)
from agentic_os.config_scope import (
    diff as config_diff,
    effective as config_effective,
    explain as config_explain,
)
from agentic_os.attach import build_attach_command, evaluate_attach
from agentic_os.diagnostics import resource_snapshot
from agentic_os.fleet import FleetEvent, FleetStore, HealthRecord
from agentic_os.health_prober import HealthProber
from agentic_os.logs import JsonlLogStore, StreamName
from agentic_os.memory import build_session_summary
from agentic_os.memory_store import MemoryStore, SessionSummaryRecord
from agentic_os.models import AgentDefinition, SessionAttachRequest, SessionRecord, SessionStatus
from agentic_os.registry import Registry, RenderedRun, validate_registry
from agentic_os.storage import Store
from agentic_os.supervisor import ProcessSupervisor


SESSION_START_APPROVAL_TOOL = "session.start"
_HEALTH_OUTPUT_MAX = 2048


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


class ApprovalRejectRequest(BaseModel):
    reason: str = ""


class DeprecationRequest(BaseModel):
    reason: str = ""
    replacement_id: str | None = None
    sunset_at: str | None = None


def create_app(state_dir: Path, registry_path: Path) -> FastAPI:
    state_dir.mkdir(parents=True, exist_ok=True)
    registry = Registry(registry_path)
    store = Store(state_dir / "agentic-os.db")
    store.init()
    memory_store = MemoryStore(state_dir / "agentic-os.db")
    memory_store.init()
    approval_store = ApprovalStore(state_dir / "agentic-os.db")
    approval_store.init()
    control_plane = ControlPlaneStore(state_dir / "agentic-os.db")
    control_plane.init()
    fleet_store = FleetStore(state_dir / "agentic-os.db")
    fleet_store.init()
    audit_store = AuditStore(state_dir / "agentic-os.db")
    audit_store.init()
    prober = HealthProber(fleet_store)
    logs = JsonlLogStore()
    supervisor = ProcessSupervisor(
        store=store,
        logs=logs,
        state_dir=state_dir,
        registry=registry,
    )
    supervisor.reconcile()

    app = FastAPI(title="agentic-os")
    app.state.store = store
    app.state.fleet_store = fleet_store
    app.state.audit_store = audit_store
    app.state.control_plane = control_plane
    app.state.approval_store = approval_store
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

    def _check_capacity(agent_id: str = "_fleet") -> None:
        running = [
            s
            for s in store.list_sessions()
            if s.status in {SessionStatus.RUNNING, SessionStatus.QUEUED, SessionStatus.STOPPING}
        ]
        if len(running) >= fleet_store.MAX_RUNNING_SESSIONS:
            detail = (
                f"Capacity limit reached: {len(running)}/"
                f"{fleet_store.MAX_RUNNING_SESSIONS} concurrent sessions"
            )
            fleet_store.record_event(
                agent_id,
                "capacity_limit_reached",
                detail,
                {
                    "running_sessions": len(running),
                    "max_running_sessions": fleet_store.MAX_RUNNING_SESSIONS,
                },
            )
            raise HTTPException(
                status_code=429,
                detail=detail,
            )

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

    @app.get("/harnesses")
    def list_harnesses() -> dict[str, object]:
        return {"harnesses": [_harness_profile(a) for a in registry.list_agents()]}

    @app.get("/harnesses/validate")
    def validate_harnesses_registry() -> dict[str, object]:
        errors, warnings = validate_registry(registry.list_agents())
        return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}

    @app.get("/harnesses/{harness_id}")
    def show_harness(harness_id: str) -> dict[str, object]:
        try:
            return _harness_profile(registry.get(harness_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/harnesses/{harness_id}/health")
    def harness_health(harness_id: str) -> dict[str, object]:
        try:
            agent = registry.get(harness_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if agent.health_command is None:
            return {"id": agent.id, "state": "unknown", "message": "no health command defined"}
        fleet_store.record_event(harness_id, "health_probe_requested", "health probe requested")
        result = _run_health_check(agent)
        event_type = "health_probe_completed"
        fleet_store.record_event(
            harness_id,
            event_type,
            f"health probe {result['state']}",
            metadata={
                "exit_code": result.get("exit_code"),
                "duration_ms": result.get("duration_ms"),
                "truncated": result.get("truncated", False),
            },
        )
        return result

    @app.get("/harnesses/{harness_id}/logs")
    def harness_logs(harness_id: str) -> dict[str, object]:
        try:
            agent = registry.get(harness_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"id": agent.id, "log_paths": list(agent.log_paths)}

    @app.get("/harnesses/{harness_id}/activity")
    def harness_activity(
        harness_id: str,
        event_type: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        before: str | None = Query(default=None),
    ) -> dict[str, object]:
        try:
            registry.get(harness_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        sessions = [s for s in store.list_sessions() if s.agent_id == harness_id]
        entries: list[dict[str, object]] = []

        for session in sessions:
            if session.started_at:
                entries.append(
                    _timeline_entry(
                        session.started_at,
                        "session_start",
                        "session",
                        f"Session {session.id} started",
                        {"session_id": session.id, "cwd": session.cwd},
                    )
                )
            if session.ended_at:
                entries.append(
                    _timeline_entry(
                        session.ended_at,
                        "session_ended",
                        "session",
                        f"Session {session.id} ended with exit_code={session.exit_code}",
                        {"session_id": session.id, "exit_code": session.exit_code},
                    )
                )
            for evt in store.list_events(session.id):
                if event_type and evt.event_type != event_type:
                    continue
                entries.append(
                    _timeline_entry(
                        evt.created_at,
                        evt.event_type,
                        "session",
                        evt.message,
                        {"session_id": session.id, **evt.metadata},
                    )
                )

        for fleet_event in fleet_store.list_events(agent_id=harness_id, limit=500):
            fleet_type = fleet_event.event_type
            if fleet_type in {"health_probe_requested", "health_probe_completed"}:
                mapped_type = "health_probe"
            else:
                mapped_type = "fleet_event"
            if event_type and mapped_type != event_type and fleet_type != event_type:
                continue
            entries.append(
                _timeline_entry(
                    fleet_event.created_at,
                    mapped_type,
                    "fleet",
                    fleet_event.message,
                    {"agent_id": fleet_event.agent_id, "event_type": fleet_type, **fleet_event.metadata},
                )
            )

        if before:
            entries = [entry for entry in entries if str(entry["timestamp"]) < before]
        entries.sort(key=lambda e: str(e["timestamp"]), reverse=True)
        return {"harness_id": harness_id, "activity": entries[:limit]}

    @app.post("/sessions")
    def run_session(request: SessionRunRequest) -> dict[str, object]:
        _check_capacity(request.agent_id)
        try:
            rendered = registry.build_run(request.agent_id, request.cwd, request.message)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        policy_result = _evaluate_session_policy(rendered.agent.id, rendered.cwd)
        if policy_result is not None:
            if policy_result.decision != "allow":
                return _reject_session(rendered, policy_result)
            session = supervisor.start(
                rendered.agent.id, rendered.cwd, rendered.argv, env=rendered.env
            )
            audit_store.record(
                "governance",
                rendered.agent.id,
                "policy_evaluated",
                f"allow: {policy_result.reason}",
                metadata=_policy_evaluation_metadata(session.id, policy_result),
            )
            audit_store.record(
                "governance",
                rendered.agent.id,
                "run_started_with_policy",
                f"session {session.id} started with policy",
                metadata={"session_id": session.id},
            )
            _wait_for_short_command(supervisor, session.id)
            return supervisor.store.get_session(session.id).model_dump()
        else:
            audit_store.record(
                "governance",
                rendered.agent.id,
                "policy_missing_at_run_start",
                f"no policy configured for {rendered.agent.id}",
            )
            session = supervisor.start(
                rendered.agent.id, rendered.cwd, rendered.argv, env=rendered.env
            )
            audit_store.record(
                "governance",
                rendered.agent.id,
                "run_started_without_policy",
                f"session {session.id} started without policy",
                metadata={"session_id": session.id},
            )
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

    @app.get("/sessions/{session_id}/timeline")
    def session_timeline(
        session_id: str,
        event_type: str | None = Query(default=None),
    ) -> dict[str, object]:
        try:
            session = store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        entries: list[dict[str, object]] = []

        # Session lifecycle events
        if session.started_at:
            entry = _timeline_entry(
                session.started_at,
                "session_start",
                "session",
                f"Session {session_id} started",
                {"agent_id": session.agent_id, "cwd": session.cwd},
            )
            if not event_type or entry["type"] == event_type:
                entries.append(entry)
        if session.pid is not None:
            entry = _timeline_entry(
                session.started_at or session.updated_at,
                "process_started",
                "supervisor",
                f"Process started with pid={session.pid}, pgid={session.pgid}",
                {"pid": session.pid, "pgid": session.pgid},
            )
            if not event_type or entry["type"] == event_type:
                entries.append(entry)
        if session.ended_at:
            entry = _timeline_entry(
                session.ended_at,
                "session_ended",
                "session",
                f"Session ended with exit_code={session.exit_code}",
                {"exit_code": session.exit_code, "status": session.status.value},
            )
            if not event_type or entry["type"] == event_type:
                entries.append(entry)

        # Session events (policy decisions, etc.)
        session_evts = store.list_events(session_id)
        for evt in session_evts:
            if event_type and evt.event_type != event_type:
                continue
            entries.append(
                _timeline_entry(
                    evt.created_at,
                    evt.event_type,
                    "session",
                    evt.message,
                    evt.metadata,
                )
            )

        # Memory review status
        try:
            summary = memory_store.get_summary(session_id)
            entry = _timeline_entry(
                summary.created_at,
                "summary_created",
                "memory",
                f"Summary created: {summary.one_liner}",
                {"summary_id": summary.id, "stdout_lines": summary.stdout_lines},
            )
            if not event_type or entry["type"] == event_type:
                entries.append(entry)
        except KeyError:
            pass

        # Memory review items
        for review in memory_store.list_review_items():
            if review.session_id == session_id:
                entry = _timeline_entry(
                    review.created_at,
                    f"review_{review.status}",
                    "memory",
                    f"Review {review.status} for session {session_id}",
                    {"review_id": review.id, "kind": review.kind},
                )
                if not event_type or entry["type"] == event_type:
                    entries.append(entry)

        for approval in approval_store.list():
            if approval.source_session_id == session_id or approval.approved_session_id == session_id:
                entry = _timeline_entry(
                    approval.created_at,
                    "approval",
                    "approval",
                    f"Approval {approval.status}: {approval.reason}",
                    {
                        "approval_id": approval.id,
                        "status": approval.status.value,
                        "source_session_id": approval.source_session_id,
                        "approved_session_id": approval.approved_session_id,
                    },
                )
                if not event_type or entry["type"] == event_type:
                    entries.append(entry)

        for stream_name, log_path in (
            ("stdout", Path(session.stdout_log)),
            ("stderr", Path(session.stderr_log)),
        ):
            for log_entry in logs.read_tail(log_path, max_lines=20):
                entry = _timeline_entry(
                    log_entry.ts,
                    "log_chunk",
                    stream_name,
                    log_entry.line[:500],
                    {"stream": stream_name, "index": log_entry.index},
                )
                if not event_type or entry["type"] == event_type:
                    entries.append(entry)

        entries.sort(key=lambda e: str(e["timestamp"]))
        return {"timeline": entries}

    @app.get("/sessions/{session_id}/logs")
    def session_logs(
        session_id: str,
        stream: StreamName | None = None,
        after: int = Query(default=0, ge=0),
        max_lines: int = Query(default=5000, ge=1, le=50000),
    ) -> dict[str, object]:
        try:
            session = store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        result = logs.read_merged(
            Path(session.stdout_log),
            Path(session.stderr_log),
            stream=stream,
            after=after,
            max_lines=max_lines,
        )
        if result.truncated:
            audit_store.record(
                "session",
                session_id,
                "log_read_truncated",
                f"log read truncated at {max_lines} lines",
                metadata={
                    "session_id": session_id,
                    "stream": stream or "merged",
                    "after": after,
                    "max_lines": max_lines,
                    "returned_lines": len(result.entries),
                },
            )
        return {
            "entries": [entry.model_dump() for entry in result.entries],
            "truncated": result.truncated,
        }

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
            previous = supervisor.get_retryable(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _check_capacity(previous.agent_id)

        store.record_event(
            session_id,
            "retry_requested",
            f"Retry requested for session {session_id}",
            {"source_session_id": session_id},
        )

        policy_result = _evaluate_session_policy(previous.agent_id, previous.cwd)
        if policy_result is not None:
            if policy_result.decision != "allow":
                rendered = RenderedRun(
                    agent=registry.get(previous.agent_id),
                    cwd=previous.cwd,
                    argv=previous.argv,
                    env=previous.env,
                )
                return _reject_session(rendered, policy_result)
            session = supervisor.start(
                previous.agent_id, previous.cwd, previous.argv, env=previous.env
            )
            audit_store.record(
                "governance",
                previous.agent_id,
                "policy_evaluated",
                f"allow: {policy_result.reason}",
                metadata=_policy_evaluation_metadata(session.id, policy_result),
            )
            audit_store.record(
                "governance",
                previous.agent_id,
                "run_started_with_policy",
                f"session {session.id} started with policy",
                metadata={"session_id": session.id},
            )
            _wait_for_short_command(supervisor, session.id)
            return supervisor.store.get_session(session.id).model_dump()
        else:
            audit_store.record(
                "governance",
                previous.agent_id,
                "policy_missing_at_run_start",
                f"no policy configured for {previous.agent_id}",
            )
            session = supervisor.start(
                previous.agent_id, previous.cwd, previous.argv, env=previous.env
            )
            audit_store.record(
                "governance",
                previous.agent_id,
                "run_started_without_policy",
                f"session {session.id} started without policy",
                metadata={"session_id": session.id},
            )
            _wait_for_short_command(supervisor, session.id)
            return supervisor.store.get_session(session.id).model_dump()

    @app.post("/sessions/{session_id}/attach")
    def attach_session(
        session_id: str,
        request: SessionAttachRequest | None = None,
    ) -> dict[str, object]:
        body = request or SessionAttachRequest()
        try:
            session = store.get_session(session_id)
            agent = registry.get(session.agent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        decision, reason = evaluate_attach(agent, session)
        attach_command = build_attach_command(agent, session)
        response: dict[str, object] = {
            "session_id": session_id,
            "harness_id": agent.id,
            "attach_command": attach_command,
            "decision": decision,
            "reason": reason,
            "mode": body.mode,
        }
        if decision == "unsupported":
            return response
        if decision == "deny":
            raise HTTPException(
                status_code=403,
                detail={
                    "decision": decision,
                    "reason": reason,
                    "session_id": session_id,
                },
            )
        if body.mode == "preview":
            return response

        policy_result = _evaluate_session_policy(agent.id, session.cwd)
        if policy_result is not None and policy_result.decision != "allow":
            raise HTTPException(
                status_code=403,
                detail={
                    "decision": policy_result.decision,
                    "reason": policy_result.reason,
                    "session_id": session_id,
                },
            )

        proc = subprocess.Popen(
            attach_command,
            cwd=session.cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        store.update_session_attach(session_id, attach_status="attached")
        audit_store.record(
            "session",
            session_id,
            "attach_exec",
            f"attach exec started for {session_id}",
            metadata={"pid": proc.pid, "attach_command": attach_command},
        )
        response["pid"] = proc.pid
        return response

    @app.get("/approvals")
    def list_approvals(
        status: str | None = Query(default=None),
        harness_id: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict[str, object]:
        approvals = [_asdict(_refresh_approval(approval)) for approval in approval_store.list()]
        if status:
            approvals = [a for a in approvals if a["status"] == status]
        if harness_id:
            approvals = [a for a in approvals if a["agent_id"] == harness_id]
        return {"approvals": approvals[:limit]}

    @app.get("/approvals/{approval_id}")
    def show_approval(approval_id: str) -> dict[str, Any]:
        try:
            return _asdict(_refresh_approval(approval_store.get(approval_id)))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/approvals/{approval_id}/approve")
    def approve_approval(approval_id: str) -> dict[str, Any]:
        try:
            approval = approval_store.get(approval_id)
            if approval.status != ApprovalStatus.PENDING:
                raise ValueError(f"approval {approval_id} is not pending")
            _check_capacity(approval.agent_id)
            policy_result = _evaluate_session_policy(approval.agent_id, approval.cwd)
            if policy_result is None or policy_result.decision == "deny":
                reason = (
                    policy_result.reason
                    if policy_result is not None
                    else f"no policy configured for {approval.agent_id}"
                )
                approval_store.expire(approval_id, reason)
                audit_store.record(
                    "governance",
                    approval.agent_id,
                    "approval_expired",
                    f"approval {approval_id} expired: {reason}",
                    metadata={
                        "approval_id": approval_id,
                        "source_session_id": approval.source_session_id,
                        "reason": reason,
                    },
                )
                raise HTTPException(status_code=409, detail=reason) from None
            claimed = approval_store.claim(approval_id)
            session = supervisor.start(
                claimed.agent_id,
                claimed.cwd,
                claimed.argv,
                env=claimed.env,
            )
            audit_store.record(
                "governance",
                claimed.agent_id,
                "policy_evaluated",
                f"approved launch: {policy_result.reason}",
                metadata=_policy_evaluation_metadata(session.id, policy_result),
            )
            approved = approval_store.link_approved_session(
                approval_id,
                approved_session_id=session.id,
            )
            audit_store.record(
                "governance",
                claimed.agent_id,
                "approval_approved",
                f"approved {approval_id}",
                metadata={
                    "approval_id": approval_id,
                    "source_session_id": claimed.source_session_id,
                    "approved_session_id": session.id,
                },
            )
            audit_store.record(
                "governance",
                claimed.agent_id,
                "run_started_after_approval",
                f"session {session.id} started after approval",
                metadata={"approval_id": approval_id, "approved_session_id": session.id},
            )
            _wait_for_short_command(supervisor, session.id)
            return _asdict(approved)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/approvals/{approval_id}/reject")
    def reject_approval(approval_id: str, request: ApprovalRejectRequest) -> dict[str, Any]:
        try:
            rejected = approval_store.reject(approval_id, request.reason)
            audit_store.record(
                "governance",
                rejected.agent_id,
                "approval_rejected",
                f"rejected {approval_id}",
                metadata={
                    "approval_id": approval_id,
                    "source_session_id": rejected.source_session_id,
                    "reason": request.reason,
                },
            )
            return _asdict(rejected)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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
        _apply_sunset_with_audit()
        return {"skills": [_asdict(skill) for skill in control_plane.list_skills()]}

    @app.get("/skills/{skill_id}")
    def show_skill(skill_id: str) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            return _asdict(control_plane.get_skill(skill_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/skills/{skill_id}")
    def upsert_skill(skill_id: str, request: SkillUpsertRequest) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            try:
                previous = control_plane.get_skill(skill_id)
            except KeyError:
                previous = None
            result = control_plane.upsert_skill(
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
            audit_store.record(
                "skill",
                skill_id,
                "skill_upserted",
                f"upserted skill {skill_id}",
                metadata=_deprecated_reset_metadata(previous, result),
            )
            return _asdict(result)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/skills/{skill_id}/disable")
    def disable_skill(skill_id: str) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            result = control_plane.disable_skill(skill_id)
            audit_store.record("skill", skill_id, "skill_disabled", f"disabled skill {skill_id}")
            return _asdict(result)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/skills/{skill_id}/deprecate")
    def deprecate_skill(
        skill_id: str,
        request: DeprecationRequest | None = None,
    ) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            previous = control_plane.get_skill(skill_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        payload = request or DeprecationRequest()
        result = control_plane.deprecate_skill(
            skill_id,
            reason=payload.reason,
            replacement_id=payload.replacement_id,
            sunset_at=payload.sunset_at,
        )
        audit_store.record(
            "skill",
            skill_id,
            "skill_deprecated",
            f"deprecated skill {skill_id}",
            metadata=_lifecycle_metadata(previous, result),
        )
        _apply_sunset_with_audit()
        return _asdict(result)

    @app.post("/skills/{skill_id}/undeprecate")
    def undeprecate_skill(skill_id: str) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            previous = control_plane.get_skill(skill_id)
            result = control_plane.undeprecate_skill(skill_id)
            audit_store.record(
                "skill",
                skill_id,
                "skill_undeprecated",
                f"undeprecated skill {skill_id}",
                metadata=_lifecycle_metadata(previous, result),
            )
            return _asdict(result)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/mcp")
    def list_mcp_servers() -> dict[str, object]:
        _apply_sunset_with_audit()
        return {"servers": [_asdict(server) for server in control_plane.list_mcp_servers()]}

    @app.get("/mcp/{server_id}")
    def show_mcp_server(server_id: str) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            return _asdict(control_plane.get_mcp_server(server_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/mcp/{server_id}")
    def upsert_mcp_server(server_id: str, request: McpServerUpsertRequest) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            try:
                previous = control_plane.get_mcp_server(server_id)
            except KeyError:
                previous = None
            result = control_plane.upsert_mcp_server(
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
            audit_store.record(
                "mcp",
                server_id,
                "mcp_upserted",
                f"upserted mcp server {server_id}",
                metadata=_deprecated_reset_metadata(previous, result),
            )
            return _asdict(result)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/mcp/{server_id}/disable")
    def disable_mcp_server(server_id: str) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            result = control_plane.disable_mcp_server(server_id)
            audit_store.record("mcp", server_id, "mcp_disabled", f"disabled mcp server {server_id}")
            return _asdict(result)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/mcp/{server_id}/deprecate")
    def deprecate_mcp_server(
        server_id: str,
        request: DeprecationRequest | None = None,
    ) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            previous = control_plane.get_mcp_server(server_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        payload = request or DeprecationRequest()
        result = control_plane.deprecate_mcp_server(
            server_id,
            reason=payload.reason,
            replacement_id=payload.replacement_id,
            sunset_at=payload.sunset_at,
        )
        audit_store.record(
            "mcp",
            server_id,
            "mcp_deprecated",
            f"deprecated mcp server {server_id}",
            metadata=_lifecycle_metadata(previous, result),
        )
        _apply_sunset_with_audit()
        return _asdict(result)

    @app.post("/mcp/{server_id}/undeprecate")
    def undeprecate_mcp_server(server_id: str) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            previous = control_plane.get_mcp_server(server_id)
            result = control_plane.undeprecate_mcp_server(server_id)
            audit_store.record(
                "mcp",
                server_id,
                "mcp_undeprecated",
                f"undeprecated mcp server {server_id}",
                metadata=_lifecycle_metadata(previous, result),
            )
            return _asdict(result)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/policy")
    def list_policies() -> dict[str, object]:
        _apply_sunset_with_audit()
        return {"policies": [_asdict(policy) for policy in control_plane.list_policies()]}

    @app.post("/policy/evaluate")
    def evaluate_policy(request: PolicyEvaluateRequest) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
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
            _apply_sunset_with_audit()
            return _asdict(control_plane.get_policy(agent_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/policy/{agent_id}")
    def upsert_policy(agent_id: str, request: PolicyUpsertRequest) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            try:
                previous = control_plane.get_policy(agent_id)
            except KeyError:
                previous = None
            result = control_plane.upsert_policy(
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
            audit_store.record(
                "policy",
                agent_id,
                "policy_upserted",
                f"upserted policy for {agent_id}",
                metadata=_deprecated_reset_metadata(previous, result),
            )
            return _asdict(result)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/policy/{agent_id}/deprecate")
    def deprecate_policy(
        agent_id: str,
        request: DeprecationRequest | None = None,
    ) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            previous = control_plane.get_policy(agent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        payload = request or DeprecationRequest()
        result = control_plane.deprecate_policy(
            agent_id,
            reason=payload.reason,
            replacement_id=payload.replacement_id,
            sunset_at=payload.sunset_at,
        )
        audit_store.record(
            "policy",
            agent_id,
            "policy_deprecated",
            f"deprecated policy for {agent_id}",
            metadata=_lifecycle_metadata(previous, result),
        )
        _apply_sunset_with_audit()
        return _asdict(result)

    @app.post("/policy/{agent_id}/undeprecate")
    def undeprecate_policy(agent_id: str) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            previous = control_plane.get_policy(agent_id)
            result = control_plane.undeprecate_policy(agent_id)
            audit_store.record(
                "policy",
                agent_id,
                "policy_undeprecated",
                f"undeprecated policy for {agent_id}",
                metadata=_lifecycle_metadata(previous, result),
            )
            return _asdict(result)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/audit/events")
    def audit_events(
        domain: str | None = Query(default=None),
        entity_id: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict[str, object]:
        events = audit_store.list_events(
            domain=domain, entity_id=entity_id, event_type=event_type, limit=limit
        )
        return {"events": [_audit_event_dict(e) for e in events]}

    @app.get("/audit/policy-coverage")
    def audit_policy_coverage() -> dict[str, object]:
        _apply_sunset_with_audit()
        agents = registry.list_agents()
        agent_ids = [a.id for a in agents]
        sessions = store.list_sessions()
        session_ids_by_agent: dict[str, list[str]] = {}
        for s in sessions:
            session_ids_by_agent.setdefault(s.agent_id, []).append(s.id)
        policy_agent_ids = [p.agent_id for p in control_plane.list_policies()]
        coverage = audit_store.policy_coverage(agent_ids, session_ids_by_agent, policy_agent_ids)
        return {"coverage": coverage}

    def _require_catalog_harness(harness: str) -> None:
        if harness not in SUPPORTED_HARNESSES:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"unsupported harness: {harness}",
                    "supported": list(SUPPORTED_HARNESSES),
                },
            )

    @app.get("/catalog/{harness}/surfaces")
    def catalog_surfaces(
        harness: str,
        cwd: str | None = Query(default=None),
        scope: str | None = Query(default=None),
        surface_type: str | None = Query(default=None),
    ) -> dict[str, object]:
        _require_catalog_harness(harness)
        records = catalog_scan(harness, cwd)
        if scope:
            records = [r for r in records if r.scope == scope]
        if surface_type:
            records = [r for r in records if r.type == surface_type]
        return {"surfaces": [_surface_record_dict(r) for r in records]}

    @app.get("/catalog/{harness}/merged")
    def catalog_merged(
        harness: str,
        cwd: str | None = Query(default=None),
    ) -> dict[str, object]:
        _require_catalog_harness(harness)
        records = catalog_scan(harness, cwd)
        merged = catalog_merge(records)
        surfaces = [_surface_record_dict(r) for r in merged]
        return {"surfaces": surfaces, "empty": len(surfaces) == 0}

    @app.get("/catalog/{harness}/diff")
    def catalog_diff_endpoint(
        harness: str,
        cwd_a: str | None = Query(default=None),
        cwd_b: str | None = Query(default=None),
        scope_a: str | None = Query(default=None),
        scope_b: str | None = Query(default=None),
    ) -> dict[str, object]:
        _require_catalog_harness(harness)
        records_a = [r for r in catalog_scan(harness, cwd_a) if not scope_a or r.scope == scope_a]
        records_b = [r for r in catalog_scan(harness, cwd_b) if not scope_b or r.scope == scope_b]
        result = catalog_diff(records_a, records_b)
        return result

    @app.get("/config/{harness_id}/effective")
    def config_effective_endpoint(
        harness_id: str,
        cwd: str | None = Query(default=None),
    ) -> dict[str, object]:
        view = config_effective(harness_id, cwd)
        return {
            "harness_id": view.harness_id,
            "scopes_present": view.scopes_present,
            "entries": [
                {"key": e.key, "value": e.value, "scope": e.scope, "source": e.source}
                for e in view.entries
            ],
        }

    @app.get("/config/{harness_id}/diff")
    def config_diff_endpoint(
        harness_id: str,
        scope_a: str = Query(default="user"),
        scope_b: str = Query(default="project"),
        cwd: str | None = Query(default=None),
    ) -> dict[str, object]:
        return config_diff(harness_id, cwd=cwd, scope_a=scope_a, scope_b=scope_b)

    @app.get("/config/{harness_id}/explain")
    def config_explain_endpoint(
        harness_id: str,
        cwd: str | None = Query(default=None),
    ) -> dict[str, object]:
        entries = config_explain(harness_id, cwd)
        return {"harness_id": harness_id, "entries": entries}

    def _require_harness_config_harness(harness_id: str) -> None:
        if harness_id not in SUPPORTED_HARNESSES:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"unsupported harness: {harness_id}",
                    "supported": list(SUPPORTED_HARNESSES),
                },
            )

    @app.get("/harness-config/{harness_id}/effective")
    def harness_config_effective_endpoint(
        harness_id: str,
        cwd: str | None = Query(default=None),
    ) -> dict[str, object]:
        _require_harness_config_harness(harness_id)
        view = harness_config_effective(harness_id, cwd)
        return {
            "harness_id": view.harness_id,
            "scopes_present": view.scopes_present,
            "entries": [
                {"key": e.key, "value": e.value, "scope": e.scope, "source": e.source}
                for e in view.entries
            ],
        }

    @app.get("/harness-config/{harness_id}/diff")
    def harness_config_diff_endpoint(
        harness_id: str,
        scope_a: str = Query(default="user"),
        scope_b: str = Query(default="project"),
        cwd: str | None = Query(default=None),
    ) -> dict[str, object]:
        _require_harness_config_harness(harness_id)
        return harness_config_diff(harness_id, cwd, scope_a=scope_a, scope_b=scope_b)

    @app.get("/harness-config/{harness_id}/explain")
    def harness_config_explain_endpoint(
        harness_id: str,
        cwd: str | None = Query(default=None),
    ) -> dict[str, object]:
        _require_harness_config_harness(harness_id)
        entries = harness_config_explain(harness_id, cwd)
        return {"harness_id": harness_id, "entries": entries}

    @app.get("/fleet/health")
    def fleet_health() -> dict[str, object]:
        records = fleet_store.list_health()
        return {"instances": [_fleet_health_dict(r) for r in records]}

    @app.get("/fleet/{agent_id}/health")
    def fleet_instance_health(agent_id: str) -> dict[str, object]:
        record = fleet_store.get_health(agent_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"No health data for {agent_id}")
        return _fleet_health_dict(record)

    @app.get("/fleet/events")
    def fleet_events(
        agent_id: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
    ) -> dict[str, object]:
        events = fleet_store.list_events(agent_id=agent_id, event_type=event_type)
        return {"events": [_fleet_event_dict(e) for e in events]}

    @app.get("/fleet/capacity")
    def fleet_capacity() -> dict[str, object]:
        running = [
            s
            for s in store.list_sessions()
            if s.status in {SessionStatus.RUNNING, SessionStatus.QUEUED, SessionStatus.STOPPING}
        ]
        return fleet_store.get_capacity(
            running_sessions=len(running),
            registered_instances=len(registry.list_agents()),
        )

    @app.post("/fleet/probe")
    async def fleet_probe() -> dict[str, object]:
        agents = registry.list_agents()
        probeable = [a for a in agents if a.health_command is not None]
        await prober.probe_all(probeable)
        return {"probed": len(probeable)}

    @app.get("/diagnostics/resources")
    def diagnostics_resources() -> dict[str, int]:
        db_path = state_dir / "agentic-os.db"
        snapshot = resource_snapshot(state_dir, db_path)
        snapshot.update(
            {
                "session_count": _sqlite_count(db_path, "sessions"),
                "audit_event_count": _sqlite_count(db_path, "audit_events"),
                "fleet_event_count": _sqlite_count(db_path, "fleet_events"),
            }
        )
        return snapshot

    def _get_session_or_404(session_id: str) -> SessionRecord:
        try:
            return store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _build_and_store_summary(session_id: str) -> SessionSummaryRecord:
        session = _get_session_or_404(session_id)
        result = logs.read_merged(Path(session.stdout_log), Path(session.stderr_log))
        return memory_store.upsert_summary(session, build_session_summary(session, result.entries))

    def _get_or_create_summary(session_id: str) -> SessionSummaryRecord:
        _get_session_or_404(session_id)
        try:
            return memory_store.get_summary(session_id)
        except KeyError:
            return _build_and_store_summary(session_id)

    def _evaluate_session_policy(agent_id: str, cwd: str) -> PolicyEvaluationResult | None:
        try:
            policy = control_plane.get_policy(agent_id)
        except (KeyError, ValueError):
            return None
        result = control_plane.evaluate_policy(PolicyEvaluationRequest(agent_id=agent_id, cwd=cwd))
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

    def _record_sunset_changes(changes: list[SunsetChange]) -> None:
        event_names = {
            "skill": "skill_auto_disabled_after_sunset",
            "mcp": "mcp_auto_disabled_after_sunset",
            "policy": "policy_auto_disabled_after_sunset",
        }
        for change in changes:
            audit_store.record(
                change.domain,
                change.entity_id,
                event_names[change.domain],
                f"auto disabled {change.entity_id} after sunset",
                metadata={
                    "sunset_at": change.sunset_at,
                    "before": change.before,
                    "after": change.after,
                },
            )

    def _apply_sunset_with_audit() -> None:
        _record_sunset_changes(control_plane.apply_sunset())

    def _refresh_approval(approval: ApprovalRecord) -> ApprovalRecord:
        if approval.status != ApprovalStatus.PENDING:
            return approval
        policy_result = _evaluate_session_policy(approval.agent_id, approval.cwd)
        if policy_result is not None and policy_result.decision != "deny":
            return approval
        reason = (
            policy_result.reason
            if policy_result is not None
            else f"no policy configured for {approval.agent_id}"
        )
        expired = approval_store.expire(approval.id, reason)
        audit_store.record(
            "governance",
            approval.agent_id,
            "approval_expired",
            f"approval {approval.id} expired: {reason}",
            metadata={
                "approval_id": approval.id,
                "source_session_id": approval.source_session_id,
                "reason": reason,
            },
        )
        return expired

    def _reject_session(rendered: RenderedRun, result: PolicyEvaluationResult) -> JSONResponse:
        session = supervisor.start_rejected(
            rendered.agent.id, rendered.cwd, rendered.argv, env=rendered.env
        )
        approval_id = None
        metadata = _policy_evaluation_metadata(session.id, result)
        if result.decision == "approval_required":
            approval = approval_store.create(
                ApprovalCreate(
                    source_session_id=session.id,
                    agent_id=rendered.agent.id,
                    cwd=rendered.cwd,
                    argv=rendered.argv,
                    env=rendered.env,
                    reason=result.reason,
                )
            )
            approval_id = approval.id
            metadata["approval_id"] = approval.id
            audit_store.record(
                "governance",
                rendered.agent.id,
                "approval_requested",
                f"approval {approval.id} requested",
                metadata={
                    "approval_id": approval.id,
                    "source_session_id": session.id,
                    "reason": result.reason,
                },
            )
        audit_store.record(
            "governance",
            rendered.agent.id,
            "policy_evaluated",
            f"{result.decision}: {result.reason}",
            metadata=metadata,
        )
        event_type = "policy_denied" if result.decision == "deny" else "policy_approval_required"
        store.record_event(
            session.id,
            event_type,
            result.reason,
            {
                "decision": result.decision,
                "agent_id": result.agent_id,
                **({"approval_id": approval_id} if approval_id is not None else {}),
            },
        )
        status_code = 403 if result.decision == "deny" else 409
        content: dict[str, object] = {
            "detail": result.reason,
            "decision": result.decision,
            "session_id": session.id,
        }
        if approval_id is not None:
            content["approval_id"] = approval_id
        return JSONResponse(status_code=status_code, content=content)

    return app


def _audit_event_dict(event: AuditEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "domain": event.domain,
        "entity_id": event.entity_id,
        "event_type": event.event_type,
        "message": event.message,
        "metadata": event.metadata,
        "created_at": event.created_at,
    }


def _fleet_health_dict(record: HealthRecord) -> dict[str, object]:
    return {
        "agent_id": record.agent_id,
        "state": record.state.value,
        "message": record.message,
        "version": record.version,
        "config_fingerprint": record.config_fingerprint,
        "updated_at": record.updated_at,
    }


def _fleet_event_dict(event: FleetEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "agent_id": event.agent_id,
        "event_type": event.event_type,
        "message": event.message,
        "metadata": event.metadata,
        "created_at": event.created_at,
    }


def _asdict(record: object) -> dict[str, Any]:
    if not is_dataclass(record):
        raise TypeError(f"Expected dataclass record, got {type(record).__name__}")
    return asdict(record)


def _deprecated_reset_metadata(
    previous: object | None, current: object
) -> dict[str, object] | None:
    if bool(getattr(previous, "deprecated", False)) and not bool(
        getattr(current, "deprecated", False)
    ):
        return {"field": "deprecated", "before": True, "after": False}
    return None


def _lifecycle_metadata(previous: object, current: object) -> dict[str, object]:
    return {"before": _asdict(previous), "after": _asdict(current)}


def _policy_evaluation_metadata(
    session_id: str,
    result: PolicyEvaluationResult,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "decision": result.decision,
        "reason": result.reason,
        "warnings": result.warnings,
    }


def _wait_for_short_command(supervisor: ProcessSupervisor, session_id: str) -> None:
    for _ in range(20):
        session = supervisor.store.get_session(session_id)
        if session.status.value in {"succeeded", "failed", "stopped"}:
            return
        time.sleep(0.025)


def _sqlite_count(db_path: Path, table: str) -> int:
    if table not in {"sessions", "audit_events", "fleet_events"}:
        raise ValueError(f"unsupported diagnostics table: {table}")
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0])


def _harness_profile(agent: AgentDefinition) -> dict[str, object]:
    """Map AgentDefinition to Harness Instance Profile field names."""
    return {
        "id": agent.id,
        "name": agent.label,
        "config_path": agent.config_path,
        "workspace_roots": list(agent.workspace_roots),
        "launch_command": list(agent.command),
        "health_command": agent.health_command,
        "attach_command": agent.attach_command,
        "log_paths": list(agent.log_paths),
        "default_provider": agent.default_provider,
    }


def _run_health_check(agent: AgentDefinition) -> dict[str, object]:
    """Execute health_command and return structured result with bounded output."""
    cmd = agent.health_command
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        duration_ms = round((time.monotonic() - start) * 1000)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        stdout_preview, s_trunc = _truncate_output(stdout)
        stderr_preview, e_trunc = _truncate_output(stderr)
        truncated = s_trunc or e_trunc
        state = "up" if proc.returncode == 0 else "down"
        message = stdout_preview or (stderr_preview or "OK")
        return {
            "id": agent.id,
            "state": state,
            "message": message,
            "exit_code": proc.returncode,
            "duration_ms": duration_ms,
            "stdout_preview": stdout_preview,
            "stderr_preview": stderr_preview,
            "truncated": truncated,
        }
    except subprocess.TimeoutExpired:
        duration_ms = round((time.monotonic() - start) * 1000)
        return {
            "id": agent.id,
            "state": "down",
            "message": "health check timed out",
            "exit_code": None,
            "duration_ms": duration_ms,
            "stdout_preview": "",
            "stderr_preview": "",
            "truncated": False,
        }
    except Exception as exc:
        duration_ms = round((time.monotonic() - start) * 1000)
        return {
            "id": agent.id,
            "state": "down",
            "message": str(exc),
            "exit_code": None,
            "duration_ms": duration_ms,
            "stdout_preview": "",
            "stderr_preview": "",
            "truncated": False,
        }


def _truncate_output(text: str) -> tuple[str, bool]:
    """Truncate output to _HEALTH_OUTPUT_MAX bytes, return (preview, truncated)."""
    encoded = text.encode("utf-8")
    if len(encoded) <= _HEALTH_OUTPUT_MAX:
        return text.strip(), False
    # Truncate to valid UTF-8 boundary to avoid partial multibyte characters
    truncated = encoded[:_HEALTH_OUTPUT_MAX]
    # Find the last complete UTF-8 character by decoding and re-encoding
    decoded = truncated.decode("utf-8", errors="ignore")
    return decoded.strip(), True


def _timeline_entry(
    timestamp: str,
    event_type: str,
    source: str,
    message: str,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": event_type,
        "source": source,
        "message": message,
        "metadata": metadata or {},
    }


def _surface_record_dict(r: SurfaceRecord) -> dict[str, object]:
    return {
        "id": r.id,
        "type": r.type,
        "name": r.name,
        "scope": r.scope,
        "harness": r.harness,
        "source": r.source,
        "enabled": r.enabled,
        "metadata": r.metadata,
        "overridden_by": r.overridden_by,
        "overrides": r.overrides,
    }
