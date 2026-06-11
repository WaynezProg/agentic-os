from __future__ import annotations

from dataclasses import asdict, is_dataclass
import io
import json
import sqlite3
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
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
    _redact_value,
)
from agentic_os.control_plane_history import (
    ControlPlaneMutationResult,
    HistoryConflictError,
    history_row_dict,
    mutation_envelope,
)
from agentic_os.backup_store import BackupStore
from agentic_os.catalog import (
    SUPPORTED_HARNESSES,
    SurfaceRecord,
    diff as catalog_diff,
    merge as catalog_merge,
    resolve_standalone_surface_path,
    resolve_surface_write_target,
    scan as catalog_scan,
)
from agentic_os.import_export import (
    ImportExportContext,
    MissingEnvVarsError,
    export_setup,
    import_setup,
)
from agentic_os.harness_config import (
    HARNESS_CONFIG_SCOPES,
    diff as harness_config_diff,
    effective as harness_config_effective,
    explain as harness_config_explain,
    infer_patch_kind,
    resolve_write_path,
)
from agentic_os.patch_engine import PatchOp
from agentic_os.config_scope import (
    AGENTIC_CONFIG_SCHEMA_HARNESS,
    CONFIG_PATCH_SCOPES,
    diff as config_diff,
    effective as config_effective,
    explain as config_explain,
    resolve_write_path as config_resolve_write_path,
)
from agentic_os.adapter_contract import (
    SEMANTIC_HARNESS_IDS,
    SUPPORTED_CONTRACT_VERSIONS,
    contract_from_agent,
    contract_from_agent_v2,
)
from agentic_os.config_inventory import read_config_summary
from agentic_os.agentic_inventory import (
    build_agentic_inventory,
    build_all_agentic_inventory,
    inventory_result_dict,
)
from agentic_os.tool_discovery import discover_all
from agentic_os import profiles as profiles_module
from agentic_os.attach import build_attach_command, discover_external_sessions, evaluate_attach
from agentic_os.diagnostics import resource_snapshot
from agentic_os.evidence import EvidenceSeverity, EvidenceStore
from agentic_os.fleet import FleetEvent, FleetStore, HealthRecord
from agentic_os.health_prober import HealthProber
from agentic_os.live_sessions import (
    live_session_dict,
    open_terminal,
    scan_live_sessions,
)
from agentic_os.logs import JsonlLogStore, StreamName
from agentic_os.memory import build_session_summary
from agentic_os.memory_store import MemoryStore, SessionSummaryRecord
from agentic_os.models import (
    AgentDefinition,
    SessionAttachRequest,
    SessionBindRequest,
    SessionCreate,
    SessionDiscoverRequest,
    SessionRecord,
    SessionStatus,
)
from agentic_os.registry import (
    Registry,
    RenderedRun,
    agents_document,
    disable_agent_instance,
    merge_agent_instance,
    registry_patch_target,
    replace_agents_ops,
    validate_registry,
    validate_registry_document,
)
from agentic_os.remote_access import RemoteAccessService
from agentic_os.remote_api import register_remote_routes
from agentic_os.remote_gateway import require_localhost_operator
from agentic_os.run_templates import (
    RunTemplateInput,
    RunTemplateStore,
    render_message_template,
)
from agentic_os.workspaces import WorkspaceStore, build_workspace_dashboard
from agentic_os.safe_edit import (
    ConflictError,
    PatchResult,
    PatchTarget,
    SafeEditEngine,
    ValidationError,
)
from agentic_os.storage import Store
from agentic_os.supervisor import ProcessSupervisor
from agentic_os.surface_ops import compile_semantic_ops
from agentic_os.profiles import ResolvedRunProfile
from agentic_os.usage import UsageStore, usage_record_to_dict


SESSION_START_APPROVAL_TOOL = "session.start"
_HEALTH_OUTPUT_MAX = 2048


def _require_contract_version(version: str) -> None:
    if version not in SUPPORTED_CONTRACT_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"unsupported contract version: {version}",
                "supported": list(SUPPORTED_CONTRACT_VERSIONS),
            },
        )


def _require_v2_semantic_harness(harness_id: str) -> None:
    if harness_id not in SEMANTIC_HARNESS_IDS:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"unsupported harness for contract v2: {harness_id}",
                "supported": list(SEMANTIC_HARNESS_IDS),
            },
        )


def _harness_contract_payload(agent: AgentDefinition, version: str) -> dict[str, Any]:
    _require_contract_version(version)
    if version == "v1":
        return contract_from_agent(agent).model_dump()
    return contract_from_agent_v2(agent).model_dump(mode="json")


class SessionRunRequest(BaseModel):
    agent_id: str | None = None
    cwd: str | None = None
    message: str | None = None
    profile: str | None = None
    template_id: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)


class WorkspaceUpsertRequest(BaseModel):
    path: str
    set_active: bool = True


class WorkspaceActiveRequest(BaseModel):
    path: str


class RunTemplateUpsertRequest(BaseModel):
    name: str
    harness_id: str
    cwd: str
    message_template: str
    profile_name: str | None = None
    required_variables: list[str] = Field(default_factory=list)
    approval_policy_hint: str = ""


class ProjectProfileBindRequest(BaseModel):
    run_profile: str


class SkillUpsertRequest(BaseModel):
    label: str
    description: str = ""
    source: str = "local"
    entrypoint: str = ""
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True


class PatchOpsRequest(BaseModel):
    ops: list[dict[str, object]]
    source: str = "api"
    base_mtime: float | None = None


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


class LiveOpenTerminalRequest(BaseModel):
    tool: str
    session_id: str
    workspace: str


class ApprovalRejectRequest(BaseModel):
    reason: str = ""


class DeprecationRequest(BaseModel):
    reason: str = ""
    replacement_id: str | None = None
    sunset_at: str | None = None


def create_app(
    state_dir: Path,
    registry_path: Path,
    live_session_roots: dict[str, Path] | None = None,
) -> FastAPI:
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
    backup_store = BackupStore(state_dir)
    safe_edit_engine = SafeEditEngine(
        state_dir=state_dir,
        backup_store=backup_store,
        audit_store=audit_store,
    )
    usage_store = UsageStore(state_dir / "agentic-os.db")
    usage_store.init()
    workspace_store = WorkspaceStore(state_dir / "agentic-os.db")
    workspace_store.init()
    run_template_store = RunTemplateStore(state_dir / "agentic-os.db")
    run_template_store.init()
    prober = HealthProber(fleet_store)
    logs = JsonlLogStore()
    evidence_store = EvidenceStore(state_dir)
    remote_access = RemoteAccessService(state_dir)
    supervisor = ProcessSupervisor(
        store=store,
        logs=logs,
        state_dir=state_dir,
        registry=registry,
        usage_store=usage_store,
    )
    supervisor.reconcile()

    app = FastAPI(title="agentic-os")
    app.state.store = store
    app.state.fleet_store = fleet_store
    app.state.audit_store = audit_store
    app.state.backup_store = backup_store
    app.state.safe_edit_engine = safe_edit_engine
    app.state.control_plane = control_plane
    app.state.approval_store = approval_store
    app.state.usage_store = usage_store
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
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
    def list_agents(tool_kind: str | None = Query(default=None)) -> dict[str, object]:
        agents = list(registry.list_agents())
        if tool_kind is not None:
            agents = [a for a in agents if a.tool_kind == tool_kind]
        return {"agents": [agent.model_dump() for agent in agents]}

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

    @app.get("/tools/discovery")
    def tools_discovery() -> dict[str, object]:
        """Discover installed tools and their versions (P34). Read-only."""
        results = discover_all(registry)
        return {
            "tools": [
                {
                    "agent_id": r.agent_id,
                    "tool_kind": r.tool_kind,
                    "installed": r.installed,
                    "binary_path": r.binary_path,
                    "version": r.version,
                    "version_error": r.version_error,
                }
                for r in results
            ],
        }

    @app.get("/tools/inventory")
    def tools_inventory() -> dict[str, object]:
        """Read non-secret config summaries for installed tools (P34). Read-only."""
        agents = [a for a in registry.list_agents() if a.enabled and a.config_path]
        summaries = []
        for agent in agents:
            summary = read_config_summary(agent.id, agent.config_path)
            summaries.append(
                {
                    "agent_id": agent.id,
                    "tool_kind": agent.tool_kind,
                    "config_source": summary.config_source,
                    "model": summary.model,
                    "provider": summary.provider,
                    "system_prompt_path": summary.system_prompt_path,
                    "parse_error": summary.parse_error,
                }
            )
        return {"tools": summaries}

    @app.get("/agentic/inventory")
    def agentic_inventory() -> dict[str, object]:
        """Read agentic runtime inventory (P37). Read-only."""
        results = build_all_agentic_inventory(registry.list_agents())
        return {"agents": [inventory_result_dict(result) for result in results]}

    @app.get("/agentic/inventory/{agent_id}")
    def agentic_inventory_single(agent_id: str) -> dict[str, object]:
        """Read single agentic runtime agent inventory (P37). Read-only."""
        try:
            agent = registry.get(agent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if agent.tool_kind != "agentic_runtime":
            raise HTTPException(
                status_code=404,
                detail=f"agent is not agentic_runtime: {agent_id}",
            )
        result = build_agentic_inventory(agent_id=agent.id, config_path=agent.config_path)
        return inventory_result_dict(result)

    @app.get("/harness-contracts")
    def list_harness_contracts(version: str = Query(default="v1")) -> dict[str, object]:
        _require_contract_version(version)
        agents = registry.list_agents()
        if version == "v2":
            agents = [agent for agent in agents if agent.id in SEMANTIC_HARNESS_IDS]
        contracts = [_harness_contract_payload(agent, version) for agent in agents]
        contracts.sort(key=lambda contract: contract["harness_id"])
        return {"contracts": contracts, "count": len(contracts)}

    @app.get("/harness-contracts/{harness_id}")
    def show_harness_contract(
        harness_id: str, version: str = Query(default="v1")
    ) -> dict[str, object]:
        _require_contract_version(version)
        if version == "v2":
            _require_v2_semantic_harness(harness_id)
        try:
            agent = registry.get(harness_id)
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"unknown harness: {harness_id}",
                    "supported": [agent.id for agent in registry.list_agents()],
                },
            )
        return _harness_contract_payload(agent, version)

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

    @app.get("/profiles")
    def list_profiles(cwd: str | None = Query(default=None)) -> dict[str, object]:
        resolved_cwd = str(Path(cwd).resolve()) if cwd else str(Path.cwd())
        profiles = profiles_module.list_profiles(resolved_cwd)
        scopes = profiles_module.profile_scope_map(resolved_cwd)
        bindings = profiles_module.list_project_bindings(resolved_cwd)
        return {
            "cwd": str(resolved_cwd),
            "run_profiles": [
                {**profile.model_dump(), "scope": scopes[profile.name]}
                for profile in profiles.values()
            ],
            "project_bindings": [
                {"project_path": project_path, "run_profile": profile_name}
                for project_path, profile_name in bindings
            ],
        }

    @app.get("/profiles/{name}")
    def show_profile(
        name: str,
        cwd: str | None = Query(default=None),
    ) -> dict[str, object]:
        resolved_cwd = Path(cwd).resolve() if cwd else Path.cwd()
        profile = profiles_module.show_profile(name, resolved_cwd)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"unknown profile: {name}")
        scope = profiles_module.resolve_profile_scope(name, resolved_cwd)
        payload = profile.model_dump()
        if scope is not None:
            payload["scope"] = scope
        payload["cwd"] = str(resolved_cwd)
        return payload

    def _apply_profile_patch(
        target: PatchTarget,
        ops: list[PatchOp],
        *,
        source: str,
        dry_run: bool = False,
        base_mtime: float | None = None,
    ) -> PatchResult:
        try:
            return safe_edit_engine.apply(
                target,
                ops,
                source=source,
                dry_run=dry_run,
                base_mtime=base_mtime,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail={"validation_errors": exc.errors}
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail={"error": "forbidden_path", "message": str(exc)},
            ) from exc
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail={"error": "stale_target"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"validation_errors": [str(exc)]}) from exc

    @app.post("/profiles", status_code=201)
    def upsert_profile(
        profile: profiles_module.RunProfileInput,
        scope: str = Query(default="local"),
        cwd: str | None = Query(default=None),
        dry_run: bool = Query(default=False),
        source: str = Query(default="api"),
        base_mtime: float | None = Query(default=None),
    ) -> dict[str, object]:
        if scope not in {"local", "global"}:
            raise HTTPException(
                status_code=400,
                detail={"message": f"unsupported scope: {scope}", "supported": ["local", "global"]},
            )
        cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
        target = profiles_module.profile_patch_target(scope, cwd_path)
        ops = profiles_module.upsert_profile_ops(profile)
        result = _apply_profile_patch(
            target,
            ops,
            source=source,
            dry_run=dry_run,
            base_mtime=base_mtime,
        )
        if dry_run:
            return _patch_result_dict(result)
        return profile.model_dump()

    @app.delete("/profiles/{name}")
    def delete_profile(
        name: str,
        scope: str = Query(default="local"),
        cwd: str | None = Query(default=None),
        cascade: bool = Query(default=False),
        dry_run: bool = Query(default=False),
        source: str = Query(default="api"),
        base_mtime: float | None = Query(default=None),
    ) -> dict[str, object]:
        if scope not in {"local", "global"}:
            raise HTTPException(
                status_code=400,
                detail={"message": f"unsupported scope: {scope}", "supported": ["local", "global"]},
            )
        cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
        profile_path = profiles_module.profile_file_path(scope, cwd_path)
        bundle = profiles_module._read_bundle(profile_path)
        if name not in bundle.run_profiles:
            raise HTTPException(status_code=404, detail=f"unknown profile: {name}")
        bound = profiles_module.bound_projects_for_profile(bundle, name)
        if bound and not cascade:
            raise HTTPException(
                status_code=409,
                detail={"error": "bound", "projects": bound},
            )
        target = profiles_module.profile_patch_target(scope, cwd_path)
        ops = profiles_module.delete_profile_ops(name, bundle, cascade=cascade)
        result = _apply_profile_patch(
            target,
            ops,
            source=source,
            dry_run=dry_run,
            base_mtime=base_mtime,
        )
        return _patch_result_dict(result)

    @app.get("/profiles/{name}/diff")
    def profile_diff(
        name: str,
        scope: str = Query(default="local"),
        other_scope: str = Query(default="global"),
        cwd: str | None = Query(default=None),
    ) -> dict[str, object]:
        if scope not in {"local", "global"} or other_scope not in {"local", "global"}:
            raise HTTPException(
                status_code=400,
                detail={"message": "unsupported scope", "supported": ["local", "global"]},
            )
        cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
        return profiles_module.profile_scope_diff(
            scope,
            other_scope,
            cwd_path,
            name=name,
        )

    @app.post("/projects/{project_path:path}/bind-profile")
    def bind_project_profile(
        project_path: str,
        request: ProjectProfileBindRequest,
        dry_run: bool = Query(default=False),
        source: str = Query(default="api"),
        base_mtime: float | None = Query(default=None),
    ) -> dict[str, object]:
        resolved_project = str(Path(unquote(project_path)).resolve())
        if profiles_module.show_profile(request.run_profile, resolved_project) is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"unknown profile: {request.run_profile}",
                    "available": sorted(profiles_module.list_profiles(resolved_project)),
                },
            )
        cwd_path = Path(resolved_project)
        local_path = profiles_module.local_profile_path(cwd_path)
        bundle = profiles_module._read_bundle(local_path)
        target = profiles_module.profile_patch_target("local", cwd_path)
        ops = profiles_module.bind_project_profile_ops(bundle, resolved_project, request.run_profile)
        result = _apply_profile_patch(
            target,
            ops,
            source=source,
            dry_run=dry_run,
            base_mtime=base_mtime,
        )
        if dry_run:
            return _patch_result_dict(result)
        return {
            "project_path": resolved_project,
            "run_profile": request.run_profile,
        }

    @app.get("/usage/sessions/{session_id}")
    def usage_session(session_id: str) -> dict[str, object]:
        record = usage_store.try_get(session_id)
        if record is None:
            return {
                "session_id": session_id,
                "provider": "N/A",
                "model": "N/A",
                "total_tokens": "N/A",
                "cost_usd": "N/A",
            }
        return usage_record_to_dict(record)

    @app.get("/usage/summary")
    def usage_summary(
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None, alias="to"),
        harness_id: str | None = None,
        provider: str | None = None,
    ) -> dict[str, object]:
        rows = usage_store.list_summary(
            from_ts=from_,
            to_ts=to,
            harness_id=harness_id,
            provider=provider,
        )
        return {"count": len(rows), "rows": rows}

    @app.get("/usage/quotas")
    def usage_quotas(
        scope: str = Query(default="daily"),
        cwd: str | None = Query(default=None),
    ) -> dict[str, object]:
        resolved_cwd = str(Path(cwd).resolve()) if cwd else str(Path.cwd())
        profiles = profiles_module.list_profiles(resolved_cwd)
        if scope == "daily":
            return {
                "scope": "daily",
                "cwd": resolved_cwd,
                "quotas": usage_store.list_profile_quotas_daily(profiles),
            }
        if scope == "session":
            return {
                "scope": "session",
                "cwd": resolved_cwd,
                "quotas": usage_store.list_profile_quotas_session(profiles),
            }
        raise HTTPException(
            status_code=400,
            detail={"message": f"unsupported scope: {scope}", "supported": ["daily", "session"]},
        )

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
                    {
                        "agent_id": fleet_event.agent_id,
                        "event_type": fleet_type,
                        **fleet_event.metadata,
                    },
                )
            )

        if before:
            entries = [entry for entry in entries if str(entry["timestamp"]) < before]
        entries.sort(key=lambda e: str(e["timestamp"]), reverse=True)
        return {"harness_id": harness_id, "activity": entries[:limit]}

    @app.post("/sessions")
    def run_session(request: SessionRunRequest) -> dict[str, object]:
        run_request, source_template_id = _resolve_session_run_request(request)
        rendered, resolved = _prepare_session_run(run_request)
        _check_capacity(rendered.agent.id)

        policy_result = _evaluate_session_policy(
            rendered.agent.id,
            rendered.cwd,
            model_id=resolved.model if resolved is not None else None,
        )
        if policy_result is not None:
            if policy_result.decision != "allow":
                return _reject_session(
                    rendered,
                    policy_result,
                    source_template_id=source_template_id,
                    **_resolved_profile_kwargs(resolved),
                )
            session = _supervisor_start(rendered, resolved, source_template_id=source_template_id)
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
            session = _supervisor_start(rendered, resolved, source_template_id=source_template_id)
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

    # Registered before /sessions/{session_id} so "live" is not captured
    # as a session id by the dynamic route.
    @app.get("/sessions/live")
    def list_live_sessions(within_hours: int = 72, limit: int = 50) -> dict[str, object]:
        """Scan real external session stores (P39). Read-only."""
        within_hours = max(1, min(within_hours, 720))
        limit = max(1, min(limit, 200))
        live, errors = scan_live_sessions(
            live_session_roots, within_hours=within_hours, limit=limit
        )
        return {
            "sessions": [live_session_dict(s) for s in live],
            "errors": errors,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    @app.post("/sessions/live/open-terminal")
    def live_open_terminal(payload: LiveOpenTerminalRequest) -> dict[str, object]:
        """Open Terminal.app resuming a discovered session (P39, macOS only)."""
        if sys.platform != "darwin":
            raise HTTPException(status_code=501, detail="open-terminal is macOS-only")
        try:
            open_terminal(payload.tool, payload.session_id, payload.workspace)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"ok": True, "tool": payload.tool, "session_id": payload.session_id}

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

    @app.get("/sessions/{session_id}/evidence")
    def session_evidence(session_id: str) -> dict[str, object]:
        try:
            session = store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return evidence_store.evidence_index(session)

    @app.get("/sessions/{session_id}/evidence.zip")
    def session_evidence_zip(session_id: str) -> StreamingResponse:
        try:
            session = store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        bundle = evidence_store.zip_for_session(session)
        return StreamingResponse(
            io.BytesIO(bundle),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{session_id}-evidence.zip"'
            },
        )

    @app.get("/sessions/{session_id}/evidence/events")
    def session_evidence_events(
        session_id: str,
        after: int = Query(default=0, ge=0),
        max_lines: int = Query(default=5000, ge=1, le=50000),
    ) -> dict[str, object]:
        try:
            session = store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        result = evidence_store.read_events(session, after=after, max_lines=max_lines)
        return {
            "events": [event.model_dump(mode="json") for event in result.events],
            "truncated": result.truncated,
        }

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
            if (
                approval.source_session_id == session_id
                or approval.approved_session_id == session_id
            ):
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

    @app.post("/sessions/discover")
    def sessions_discover(request: SessionDiscoverRequest) -> dict[str, object]:
        try:
            workspace = Path(request.workspace_path).expanduser()
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not workspace.exists() or not workspace.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"workspace_path is not a directory: {request.workspace_path}",
            )
        discovered = discover_external_sessions(
            workspace_path=str(workspace),
            agents=list(registry.list_agents()),
        )
        return {
            "discovered": [
                {
                    "agent_id": d.agent_id,
                    "external_session_id": d.external_session_id,
                    "log_path": d.log_path,
                    "started_at": d.started_at,
                }
                for d in discovered
            ],
        }

    @app.post("/sessions/bind")
    def sessions_bind(request: SessionBindRequest) -> dict[str, object]:
        try:
            agent = registry.get(request.agent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        session_create = SessionCreate(
            agent_id=agent.id,
            cwd=request.workspace_path,
            argv=[agent.id, "--resume", request.external_session_id],
            artifact_dir=str(
                Path(request.workspace_path)
                / ".agentic-os-bound"
                / request.external_session_id
            ),
            stdout_log=request.log_path,
            stderr_log=request.log_path,
            summary_one_liner=f"bound to {agent.id} session {request.external_session_id}",
            workspace_path=request.workspace_path,
        )
        session = store.create_session(session_create)
        bound = store.update_session_attach(
            session.id,
            external_session_id=request.external_session_id,
            attachable=True,
            attach_status="available",
        )
        audit_store.record(
            "session",
            bound.id,
            "bind_external",
            f"bound to {agent.id} external session {request.external_session_id}",
            metadata={
                "agent_id": agent.id,
                "external_session_id": request.external_session_id,
                "log_path": request.log_path,
            },
        )
        return bound.model_dump()

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

        policy_result = _evaluate_session_policy(
            previous.agent_id,
            previous.cwd,
            model_id=previous.resolved_model,
        )
        if policy_result is not None:
            if policy_result.decision != "allow":
                rendered = RenderedRun(
                    agent=registry.get(previous.agent_id),
                    cwd=previous.cwd,
                    argv=previous.argv,
                    env=previous.env,
                )
                return _reject_session(
                    rendered,
                    policy_result,
                    resolved_profile=previous.resolved_profile,
                    resolved_provider=previous.resolved_provider,
                    resolved_model=previous.resolved_model,
                )
            session = supervisor.start(
                previous.agent_id,
                previous.cwd,
                previous.argv,
                env=previous.env,
                resolved_profile=previous.resolved_profile,
                resolved_provider=previous.resolved_provider,
                resolved_model=previous.resolved_model,
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
                previous.agent_id,
                previous.cwd,
                previous.argv,
                env=previous.env,
                resolved_profile=previous.resolved_profile,
                resolved_provider=previous.resolved_provider,
                resolved_model=previous.resolved_model,
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

        policy_result = _evaluate_session_policy(
            agent.id,
            session.cwd,
            model_id=session.resolved_model,
        )
        if policy_result is not None and policy_result.decision != "allow":
            status_code = 403 if policy_result.decision == "deny" else 409
            raise HTTPException(
                status_code=status_code,
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
            source_session = _get_session_or_none(approval.source_session_id)
            policy_result = _evaluate_session_policy(
                approval.agent_id,
                approval.cwd,
                model_id=source_session.resolved_model if source_session is not None else None,
            )
            if policy_result is None or policy_result.decision == "deny":
                reason = (
                    policy_result.reason
                    if policy_result is not None
                    else f"no policy configured for {approval.agent_id}"
                )
                approval_store.expire(approval_id, reason)
                _append_approval_resolution_event(
                    approval.source_session_id,
                    approval_id=approval_id,
                    status="expired",
                    reason=reason,
                )
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
            source_session = _get_session_or_none(claimed.source_session_id)
            session = supervisor.start(
                claimed.agent_id,
                claimed.cwd,
                claimed.argv,
                env=claimed.env,
                resolved_profile=(
                    source_session.resolved_profile if source_session is not None else None
                ),
                resolved_provider=(
                    source_session.resolved_provider if source_session is not None else None
                ),
                resolved_model=source_session.resolved_model
                if source_session is not None
                else None,
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
            _append_approval_resolution_event(
                claimed.source_session_id,
                approval_id=approval_id,
                status="approved",
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
            _append_approval_resolution_event(
                rejected.source_session_id,
                approval_id=approval_id,
                status="rejected",
                reason=request.reason,
            )
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
        return _with_memory_boundary(
            _asdict(_build_and_store_summary(session_id)),
            "summary_pointer",
        )

    @app.get("/sessions/{session_id}/memory/summary")
    def show_session_memory_summary(session_id: str) -> dict[str, Any]:
        _get_session_or_404(session_id)
        try:
            return _with_memory_boundary(
                _asdict(memory_store.get_summary(session_id)),
                "summary_pointer",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/memory/review")
    def create_session_memory_review(session_id: str) -> dict[str, Any]:
        summary = _get_or_create_summary(session_id)
        return _with_memory_boundary(
            _asdict(memory_store.create_review_item(summary)),
            "review_pointer",
        )

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
            mutation = control_plane.upsert_skill_tracked(
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
            event = audit_store.record(
                "skill",
                skill_id,
                "skill_upserted",
                f"upserted skill {skill_id}",
                metadata=_deprecated_reset_metadata(previous, mutation.record),
            )
            return _catalog_mutation_response(
                _asdict(mutation.record),
                _with_audit_event(mutation, event.id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/skills/{skill_id}/history")
    def skill_history(skill_id: str, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
        try:
            entries = control_plane.list_skill_history(skill_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"patches": [history_row_dict(entry) for entry in entries]}

    @app.post("/skills/{skill_id}/rollback")
    def skill_rollback(
        skill_id: str,
        to: str = Query(...),
        source: str = Query(default="api"),
    ) -> dict[str, Any]:
        try:
            mutation = control_plane.rollback_skill(skill_id, to, source=source)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
        except HistoryConflictError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        event = audit_store.record(
            "skill",
            skill_id,
            "skill_rolled_back",
            f"rolled back skill {skill_id} to {to}",
            metadata={"rollback_of": to, "source": source},
        )
        return _catalog_mutation_response(
            _asdict(mutation.record),
            _with_audit_event(mutation, event.id),
        )

    @app.post("/skills/{skill_id}/disable")
    def disable_skill(skill_id: str) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            mutation = control_plane.disable_skill_tracked(skill_id)
            event = audit_store.record("skill", skill_id, "skill_disabled", f"disabled skill {skill_id}")
            return _catalog_mutation_response(
                _asdict(mutation.record),
                _with_audit_event(mutation, event.id),
            )
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
            mutation = control_plane.upsert_mcp_server_tracked(
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
            event = audit_store.record(
                "mcp",
                server_id,
                "mcp_upserted",
                f"upserted mcp server {server_id}",
                metadata=_deprecated_reset_metadata(previous, mutation.record),
            )
            return _catalog_mutation_response(
                _asdict(mutation.record),
                _with_audit_event(mutation, event.id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/mcp/{server_id}/history")
    def mcp_history(server_id: str, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
        try:
            entries = control_plane.list_mcp_history(server_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"patches": [history_row_dict(entry) for entry in entries]}

    @app.post("/mcp/{server_id}/rollback")
    def mcp_rollback(
        server_id: str,
        to: str = Query(...),
        source: str = Query(default="api"),
    ) -> dict[str, Any]:
        try:
            mutation = control_plane.rollback_mcp_server(server_id, to, source=source)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
        except HistoryConflictError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        event = audit_store.record(
            "mcp",
            server_id,
            "mcp_rolled_back",
            f"rolled back mcp server {server_id} to {to}",
            metadata={"rollback_of": to, "source": source},
        )
        return _catalog_mutation_response(
            _asdict(mutation.record),
            _with_audit_event(mutation, event.id),
        )

    @app.post("/mcp/{server_id}/disable")
    def disable_mcp_server(server_id: str) -> dict[str, Any]:
        try:
            _apply_sunset_with_audit()
            mutation = control_plane._disable_mcp_server_tracked(server_id)
            event = audit_store.record("mcp", server_id, "mcp_disabled", f"disabled mcp server {server_id}")
            return _catalog_mutation_response(
                _asdict(mutation.record),
                _with_audit_event(mutation, event.id),
            )
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
            mutation = control_plane.upsert_policy_tracked(
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
            event = audit_store.record(
                "policy",
                agent_id,
                "policy_upserted",
                f"upserted policy for {agent_id}",
                metadata=_deprecated_reset_metadata(previous, mutation.record),
            )
            return _catalog_mutation_response(
                _asdict(mutation.record),
                _with_audit_event(mutation, event.id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/policy/{agent_id}/history")
    def policy_history(agent_id: str, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
        try:
            entries = control_plane.list_policy_history(agent_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"patches": [history_row_dict(entry) for entry in entries]}

    @app.post("/policy/{agent_id}/rollback")
    def policy_rollback(
        agent_id: str,
        to: str = Query(...),
        source: str = Query(default="api"),
    ) -> dict[str, Any]:
        try:
            mutation = control_plane.rollback_policy(agent_id, to, source=source)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
        except HistoryConflictError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        event = audit_store.record(
            "policy",
            agent_id,
            "policy_rolled_back",
            f"rolled back policy for {agent_id} to {to}",
            metadata={"rollback_of": to, "source": source},
        )
        return _catalog_mutation_response(
            _asdict(mutation.record),
            _with_audit_event(mutation, event.id),
        )

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

    _STRUCTURED_OPS = frozenset(
        {"enable_mcp_server", "disable_mcp_server", "upsert_hook"}
    )

    def _infer_surface_kind(op_name: str) -> str:
        if op_name in ("enable_mcp_server", "disable_mcp_server"):
            return "mcp_server"
        if op_name == "upsert_hook":
            return "hook"
        if op_name == "upsert_skill":
            return "skill"
        if op_name == "upsert_command":
            return "command"
        msg = f"unsupported semantic op: {op_name}"
        raise ValueError(msg)

    def _patch_result_dict(result: PatchResult) -> dict[str, object]:
        return {
            "patch_id": result.patch_id,
            "applied": result.applied,
            "diff": result.diff,
            "validation": result.validation,
            "backup": result.backup,
            "audit_event_id": result.audit_event_id,
            "base_mtime": result.base_mtime,
        }

    def _with_audit_event(mutation: ControlPlaneMutationResult, event_id: int | None) -> ControlPlaneMutationResult:
        return ControlPlaneMutationResult(
            patch_id=mutation.patch_id,
            applied=mutation.applied,
            diff=mutation.diff,
            audit_event_id=event_id,
            record=mutation.record,
        )

    def _catalog_mutation_response(record: dict[str, Any], mutation: ControlPlaneMutationResult) -> dict[str, Any]:
        return {**mutation_envelope(mutation), **record}

    @app.post("/catalog/{harness}/surfaces/patch")
    def catalog_surfaces_patch(
        harness: str,
        body: PatchOpsRequest,
        cwd: str | None = Query(default=None),
        dry_run: bool = Query(default=False),
    ) -> dict[str, object]:
        _require_catalog_harness(harness)
        if not body.ops:
            raise HTTPException(status_code=422, detail={"validation_errors": ["ops must not be empty"]})
        cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
        try:
            compiled = compile_semantic_ops(harness, body.ops)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"validation_errors": [str(exc)]}) from exc
        structured_target: PatchTarget | None = None
        if compiled.patch_ops:
            structured_ops = [op for op in body.ops if str(op.get("op")) in _STRUCTURED_OPS]
            first_op = structured_ops[0]
            scope = str(first_op.get("scope", "project"))
            kind = _infer_surface_kind(str(first_op["op"]))
            file_path, file_format = resolve_surface_write_target(harness, scope, kind, cwd_path)
            structured_target = PatchTarget(
                harness_id=harness,
                cwd=cwd_path,
                scope=scope,
                target_kind="surface",
                kind=kind,
                file_path=file_path,
                file_format=file_format,
            )
        try:
            results = safe_edit_engine.apply_surface_batch(
                harness_id=harness,
                cwd=cwd_path,
                compiled=compiled,
                structured_target=structured_target,
                resolve_standalone_path=resolve_standalone_surface_path,
                source=body.source,
                dry_run=dry_run,
                base_mtime=body.base_mtime,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail={"validation_errors": exc.errors}
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail={"error": "forbidden_path", "message": str(exc)},
            ) from exc
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail={"error": "stale_target"}) from exc
        if len(results) == 1:
            return _patch_result_dict(results[0])
        return {"results": [_patch_result_dict(result) for result in results]}

    @app.get("/patches")
    def patches_list(
        harness: str | None = Query(default=None),
        cwd: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, object]:
        entries = backup_store.list_entries(
            harness_id=harness,
            cwd=str(Path(cwd).resolve()) if cwd else None,
            limit=limit,
        )
        return {"patches": [entry.__dict__ for entry in entries]}

    @app.get("/patches/{patch_id}")
    def patches_get(patch_id: str) -> dict[str, object]:
        entry = backup_store.get(patch_id)
        if entry is None:
            raise HTTPException(status_code=404, detail={"error": "patch_not_found"})
        return {"patch": entry.__dict__}

    @app.post("/patches/{patch_id}/rollback")
    def patches_rollback(
        patch_id: str,
        source: str = Query(default="api"),
    ) -> dict[str, object]:
        entry = backup_store.get(patch_id)
        try:
            result = safe_edit_engine.rollback(patch_id, source=source)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        if entry is not None and Path(entry.target_path).resolve() == registry_path.resolve():
            registry.reload()
        return {
            "patch_id": result.patch_id,
            "applied": result.applied,
            "audit_event_id": result.audit_event_id,
        }

    def _registry_extra_validator(after: dict[str, object]) -> list[str]:
        errors, _warnings = validate_registry_document(after)
        return errors

    def _apply_registry_patch(
        ops: list[PatchOp],
        *,
        source: str,
        dry_run: bool = False,
        base_mtime: float | None = None,
    ) -> PatchResult:
        cwd_path = Path.cwd()
        target = registry_patch_target(registry_path, cwd_path)
        try:
            result = safe_edit_engine.apply(
                target,
                ops,
                source=source,
                dry_run=dry_run,
                base_mtime=base_mtime,
                extra_validator=_registry_extra_validator,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail={"validation_errors": exc.errors}
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail={"error": "forbidden_path", "message": str(exc)},
            ) from exc
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail={"error": "stale_target"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"validation_errors": [str(exc)]}) from exc
        if not dry_run:
            registry.reload()
        return result

    def _registry_patch_response(result: PatchResult, after_doc: dict[str, object]) -> dict[str, object]:
        _errors, warnings = validate_registry_document(after_doc)
        response = _patch_result_dict(result)
        validation = dict(response.get("validation", {}))
        validation["warnings"] = warnings
        response["validation"] = validation
        return response

    @app.get("/registry/schema")
    def registry_schema() -> dict[str, object]:
        return {"cwd_mode": ["required", "optional", "ignored"]}

    @app.post("/registry/agents")
    def registry_upsert_agent(
        agent: AgentDefinition,
        dry_run: bool = Query(default=False),
        source: str = Query(default="api"),
        base_mtime: float | None = Query(default=None),
    ) -> dict[str, object]:
        merged = merge_agent_instance(registry.list_agents(), agent)
        agent_payloads = agents_document(merged)
        ops = replace_agents_ops(agent_payloads)
        result = _apply_registry_patch(
            ops,
            source=source,
            dry_run=dry_run,
            base_mtime=base_mtime,
        )
        return _registry_patch_response(result, {"agents": agent_payloads})

    @app.post("/registry/agents/{agent_id}/disable")
    def registry_disable_agent(
        agent_id: str,
        dry_run: bool = Query(default=False),
        source: str = Query(default="api"),
        base_mtime: float | None = Query(default=None),
    ) -> dict[str, object]:
        try:
            merged = disable_agent_instance(registry.list_agents(), agent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        agent_payloads = agents_document(merged)
        ops = replace_agents_ops(agent_payloads)
        result = _apply_registry_patch(
            ops,
            source=source,
            dry_run=dry_run,
            base_mtime=base_mtime,
        )
        return _registry_patch_response(result, {"agents": agent_payloads})

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

    @app.post("/config/{harness_id}/patch")
    def config_patch_endpoint(
        harness_id: str,
        body: PatchOpsRequest,
        scope: str = Query(default="user"),
        cwd: str | None = Query(default=None),
        dry_run: bool = Query(default=False),
    ) -> dict[str, object]:
        if scope not in CONFIG_PATCH_SCOPES:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"invalid scope: {scope}",
                    "supported": list(CONFIG_PATCH_SCOPES),
                },
            )
        if not body.ops:
            raise HTTPException(status_code=422, detail={"validation_errors": ["ops must not be empty"]})
        cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
        home_dir = Path.home()
        try:
            file_path = config_resolve_write_path(scope, cwd=str(cwd_path), home_dir=home_dir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
        patch_ops = [
            PatchOp(
                op=str(raw["op"]),
                path=str(raw.get("path", "")),
                value=raw.get("value"),
            )
            for raw in body.ops
        ]
        target = PatchTarget(
            harness_id=AGENTIC_CONFIG_SCHEMA_HARNESS,
            cwd=cwd_path,
            scope=scope,
            target_kind="agentic_config",
            kind="config",
            file_path=file_path,
            file_format="toml",
        )
        try:
            result = safe_edit_engine.apply(
                target,
                patch_ops,
                source=body.source,
                dry_run=dry_run,
                base_mtime=body.base_mtime,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail={"validation_errors": exc.errors}
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail={"error": "forbidden_path", "message": str(exc)},
            ) from exc
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail={"error": "stale_target"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"validation_errors": [str(exc)]}) from exc
        response = _patch_result_dict(result)
        response["harness_id"] = harness_id
        return response

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

    @app.post("/harness-config/{harness_id}/patch")
    def harness_config_patch_endpoint(
        harness_id: str,
        body: PatchOpsRequest,
        scope: str = Query(default="project"),
        cwd: str | None = Query(default=None),
        dry_run: bool = Query(default=False),
        file: str | None = Query(default=None),
    ) -> dict[str, object]:
        _require_harness_config_harness(harness_id)
        if scope not in HARNESS_CONFIG_SCOPES:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"invalid scope: {scope}",
                    "supported": list(HARNESS_CONFIG_SCOPES),
                },
            )
        if not body.ops:
            raise HTTPException(status_code=422, detail={"validation_errors": ["ops must not be empty"]})
        cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
        try:
            file_path, file_format = resolve_write_path(
                harness_id,
                scope,
                cwd_path,
                file_name=file,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
        kind = infer_patch_kind(harness_id, file_path)
        patch_ops = [
            PatchOp(
                op=str(raw["op"]),
                path=str(raw.get("path", "")),
                value=raw.get("value"),
            )
            for raw in body.ops
        ]
        target = PatchTarget(
            harness_id=harness_id,
            cwd=cwd_path,
            scope=scope,
            target_kind="harness_config",
            kind=kind,
            file_path=file_path,
            file_format=file_format,
        )
        try:
            result = safe_edit_engine.apply(
                target,
                patch_ops,
                source=body.source,
                dry_run=dry_run,
                base_mtime=body.base_mtime,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail={"validation_errors": exc.errors}
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail={"error": "forbidden_path", "message": str(exc)},
            ) from exc
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail={"error": "stale_target"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"validation_errors": [str(exc)]}) from exc
        return _patch_result_dict(result)

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

    def _prepare_session_run(
        request: SessionRunRequest,
    ) -> tuple[RenderedRun, ResolvedRunProfile | None]:
        profile_cwd = request.cwd or str(Path.cwd())
        profiles = profiles_module.list_profiles(profile_cwd)
        bindings = profiles_module.list_project_bindings(profile_cwd)
        try:
            _resolved_name, resolved, effective_message = profiles_module.resolve_profile(
                request.profile,
                profile_cwd,
                request.message,
                profiles,
                bindings,
                request.agent_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        agent_id = resolved.harness_id if resolved is not None else request.agent_id
        if not agent_id:
            raise HTTPException(status_code=400, detail="agent_id is required")
        resolved_model = resolved.model if resolved is not None else None
        resolved_provider = resolved.provider if resolved is not None else None
        try:
            rendered = registry.build_run(
                agent_id,
                request.cwd,
                effective_message,
                model=resolved_model,
                provider=resolved_provider,
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if resolved is not None:
            rendered = RenderedRun(
                agent=rendered.agent,
                cwd=rendered.cwd,
                argv=rendered.argv,
                env={**rendered.env, **resolved.default_env},
            )
        return rendered, resolved

    def _resolve_session_run_request(
        request: SessionRunRequest,
    ) -> tuple[SessionRunRequest, str | None]:
        if request.template_id:
            template = run_template_store.get(request.template_id)
            message = render_message_template(template.message_template, request.variables)
            return (
                SessionRunRequest(
                    agent_id=template.harness_id,
                    cwd=template.cwd,
                    message=message,
                    profile=template.profile_name,
                ),
                template.id,
            )
        if not request.agent_id or not request.message:
            raise HTTPException(
                status_code=400,
                detail="agent_id and message are required when template_id is omitted",
            )
        return request, None

    def _supervisor_start(
        rendered: RenderedRun,
        resolved: ResolvedRunProfile | None,
        *,
        source_template_id: str | None = None,
    ) -> SessionRecord:
        kwargs = _resolved_profile_kwargs(resolved)
        return supervisor.start(
            rendered.agent.id,
            rendered.cwd,
            rendered.argv,
            env=rendered.env,
            source_template_id=source_template_id,
            **kwargs,
        )

    def _resolved_profile_kwargs(
        resolved: ResolvedRunProfile | None,
    ) -> dict[str, str | None]:
        if resolved is None:
            return {}
        return {
            "resolved_profile": resolved.name,
            "resolved_provider": resolved.provider,
            "resolved_model": resolved.model,
        }

    def _evaluate_session_policy(
        agent_id: str,
        cwd: str,
        model_id: str | None = None,
    ) -> PolicyEvaluationResult | None:
        try:
            policy = control_plane.get_policy(agent_id)
        except (KeyError, ValueError):
            return None
        result = control_plane.evaluate_policy(
            PolicyEvaluationRequest(agent_id=agent_id, cwd=cwd, model_id=model_id)
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

    def _append_session_evidence_event(
        session_id: str,
        event_type: str,
        message: str,
        metadata: dict[str, object],
        *,
        severity: EvidenceSeverity = "info",
    ) -> None:
        try:
            session = store.get_session(session_id)
            evidence_store.append_event(
                session,
                event_type,
                message,
                metadata,
                severity=severity,
            )
            evidence_store.write_metadata(session)
        except Exception as exc:  # noqa: BLE001
            try:
                store.record_event(
                    session_id,
                    "evidence_write_failed",
                    str(exc),
                    {"phase": f"api_event:{event_type}"},
                )
            except Exception:  # noqa: BLE001
                pass

    def _append_approval_resolution_event(
        session_id: str,
        *,
        approval_id: str,
        status: str,
        reason: str | None = None,
        approved_session_id: str | None = None,
    ) -> None:
        metadata: dict[str, object] = {"approval_id": approval_id, "status": status}
        if reason is not None:
            metadata["reason"] = reason
        if approved_session_id is not None:
            metadata["approved_session_id"] = approved_session_id
        _append_session_evidence_event(
            session_id,
            "approval_resolved",
            f"approval {approval_id} {status}",
            metadata,
        )

    def _refresh_approval(approval: ApprovalRecord) -> ApprovalRecord:
        if approval.status != ApprovalStatus.PENDING:
            return approval
        source_session = _get_session_or_none(approval.source_session_id)
        policy_result = _evaluate_session_policy(
            approval.agent_id,
            approval.cwd,
            model_id=source_session.resolved_model if source_session is not None else None,
        )
        if policy_result is not None and policy_result.decision != "deny":
            return approval
        reason = (
            policy_result.reason
            if policy_result is not None
            else f"no policy configured for {approval.agent_id}"
        )
        expired = approval_store.expire(approval.id, reason)
        _append_approval_resolution_event(
            approval.source_session_id,
            approval_id=approval.id,
            status="expired",
            reason=reason,
        )
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

    def _get_session_or_none(session_id: str) -> SessionRecord | None:
        try:
            return store.get_session(session_id)
        except KeyError:
            return None

    def _reject_session(
        rendered: RenderedRun,
        result: PolicyEvaluationResult,
        *,
        resolved_profile: str | None = None,
        resolved_provider: str | None = None,
        resolved_model: str | None = None,
        source_template_id: str | None = None,
    ) -> JSONResponse:
        session = supervisor.start_rejected(
            rendered.agent.id,
            rendered.cwd,
            rendered.argv,
            env=rendered.env,
            resolved_profile=resolved_profile,
            resolved_provider=resolved_provider,
            resolved_model=resolved_model,
            source_template_id=source_template_id,
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
            _append_session_evidence_event(
                session.id,
                "approval_required",
                result.reason,
                {
                    "decision": result.decision,
                    "approval_id": approval.id,
                    "agent_id": result.agent_id,
                },
                severity="warning",
            )
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

    def _import_export_context() -> ImportExportContext:
        return ImportExportContext(
            control_plane=control_plane,
            registry=registry,
            registry_path=registry_path,
            safe_edit_engine=safe_edit_engine,
            audit_store=audit_store,
            run_template_store=run_template_store,
        )

    @app.get("/version")
    def version_info() -> dict[str, object]:
        return {
            "version": "0.1.0",
            "update_available": False,
            "update_check": "stub",
        }

    @app.get("/setup/logs.zip")
    def setup_logs_zip(limit: int = Query(default=5000, ge=1, le=5000)) -> StreamingResponse:
        buffer = io.BytesIO()
        sessions = store.list_sessions()[:25]
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for session in sessions:
                stdout_path = Path(session.stdout_log)
                stderr_path = Path(session.stderr_log)
                if not stdout_path.exists() and not stderr_path.exists():
                    continue
                result = logs.read_merged(stdout_path, stderr_path, max_lines=limit)
                redacted_lines = [
                    f"{entry.ts}\t{entry.stream}\t{_redact_value(entry.line)}"
                    for entry in result.entries
                ]
                archive.writestr(
                    f"{session.id}/merged.log",
                    "\n".join(redacted_lines),
                )
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="agentic-os-logs.zip"'},
        )

    @app.get("/setup/export")
    def setup_export(cwd: str | None = Query(default=None)) -> dict[str, object]:
        cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
        return export_setup(_import_export_context(), cwd_path)

    @app.post("/setup/import")
    def setup_import(
        bundle: dict[str, object],
        cwd: str | None = Query(default=None),
        dry_run: bool = Query(default=True),
    ) -> dict[str, object]:
        cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
        try:
            return import_setup(
                _import_export_context(),
                cwd_path,
                bundle,
                dry_run=dry_run,
            )
        except MissingEnvVarsError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "missing_env_vars",
                    "missing": exc.names,
                    "message": str(exc),
                },
            ) from exc

    @app.get("/workspaces")
    def list_workspaces() -> dict[str, object]:
        return {
            "active": workspace_store.get_active(),
            "workspaces": [asdict(record) for record in workspace_store.list_workspaces()],
        }

    @app.post("/workspaces")
    def upsert_workspace(body: WorkspaceUpsertRequest, request: Request) -> dict[str, object]:
        require_localhost_operator(request)
        try:
            record = (
                workspace_store.set_active(body.path)
                if body.set_active
                else workspace_store.touch(body.path)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(record)

    @app.put("/workspaces/active")
    def set_active_workspace(body: WorkspaceActiveRequest, request: Request) -> dict[str, object]:
        require_localhost_operator(request)
        try:
            record = workspace_store.set_active(body.path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"active": record.path, "workspace": asdict(record)}

    @app.get("/workspaces/dashboard")
    def workspace_dashboard(cwd: str | None = Query(default=None)) -> dict[str, object]:
        active = workspace_store.get_active()
        target = cwd or active or str(Path.cwd())
        try:
            return build_workspace_dashboard(
                target,
                profiles_module=profiles_module,
                registry=registry,
                store=store,
                approval_store=approval_store,
                audit_store=audit_store,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/run-templates")
    def list_run_templates(cwd: str | None = Query(default=None)) -> dict[str, object]:
        try:
            templates = run_template_store.list_templates(cwd=cwd)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"templates": [asdict(template) for template in templates]}

    @app.get("/run-templates/{template_id}")
    def show_run_template(template_id: str) -> dict[str, object]:
        try:
            return asdict(run_template_store.get(template_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/run-templates/{template_id}/preview")
    def preview_run_template(
        template_id: str,
        variables: str | None = Query(default=None),
    ) -> dict[str, object]:
        try:
            template = run_template_store.get(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        parsed_variables: dict[str, str] = {}
        if variables:
            try:
                loaded = json.loads(variables)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="invalid variables JSON") from exc
            if not isinstance(loaded, dict):
                raise HTTPException(status_code=400, detail="variables must be a JSON object")
            parsed_variables = {str(key): str(value) for key, value in loaded.items()}
        run_request = SessionRunRequest(
            agent_id=template.harness_id,
            cwd=template.cwd,
            message=render_message_template(template.message_template, parsed_variables),
            profile=template.profile_name,
        )
        rendered, resolved = _prepare_session_run(run_request)
        return {
            "template_id": template.id,
            "cwd": rendered.cwd,
            "argv": rendered.argv,
            "env": sorted(rendered.env.keys()),
            "resolved_profile": resolved.name if resolved is not None else None,
            "resolved_provider": resolved.provider if resolved is not None else None,
            "resolved_model": resolved.model if resolved is not None else None,
        }

    @app.post("/run-templates", status_code=201)
    def create_run_template(body: RunTemplateUpsertRequest, request: Request) -> dict[str, object]:
        require_localhost_operator(request)
        try:
            record = run_template_store.create(RunTemplateInput(**body.model_dump()))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(record)

    @app.put("/run-templates/{template_id}")
    def update_run_template(
        template_id: str,
        body: RunTemplateUpsertRequest,
        request: Request,
    ) -> dict[str, object]:
        require_localhost_operator(request)
        try:
            record = run_template_store.update(template_id, RunTemplateInput(**body.model_dump()))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(record)

    @app.delete("/run-templates/{template_id}")
    def delete_run_template(template_id: str, request: Request) -> dict[str, object]:
        require_localhost_operator(request)
        try:
            run_template_store.delete(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True, "template_id": template_id}

    register_remote_routes(app, remote=remote_access, audit_store=audit_store)

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


def _with_memory_boundary(payload: dict[str, Any], ownership: str) -> dict[str, Any]:
    return {
        **payload,
        "ownership": ownership,
        "formal_memory_owner": "session2memory",
    }


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
