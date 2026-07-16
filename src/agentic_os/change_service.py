from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentic_os import catalog, config_scope, harness_config, profiles, registry
from agentic_os.change_models import ChangePlan, ChangeVerification
from agentic_os.change_payload_store import ChangePayloadStore
from agentic_os.change_store import ChangeStore
from agentic_os.mcp_alignment import (
    build_copy_patch,
    build_remove_patch,
    config_format,
    config_path,
)
from agentic_os.patch_engine import PatchEngine, PatchOp
from agentic_os.safe_edit import (
    ConflictError,
    ObservedTarget,
    PatchResult,
    PatchTarget,
    SafeEditEngine,
)

DocumentValidator = Callable[[dict[str, Any]], list[str]]


@dataclass(frozen=True)
class BuiltChange:
    target: PatchTarget | None
    ops: list[PatchOp]
    summary: dict[str, object]
    standalone_path: Path | None = None
    standalone_content: str | None = None
    surface_id: str | None = None
    extra_validator: DocumentValidator | None = None

    @property
    def is_standalone(self) -> bool:
        return self.standalone_path is not None


class ChangeService:
    def __init__(
        self,
        *,
        home: Path,
        store: ChangeStore,
        safe_edit_engine: SafeEditEngine,
        registry_path: Path | None = None,
        on_registry_change: Callable[[], None] | None = None,
    ) -> None:
        self.home = home
        self.store = store
        self.safe_edit_engine = safe_edit_engine
        self.registry_path = registry_path
        self.on_registry_change = on_registry_change
        self.payload_store = ChangePayloadStore(safe_edit_engine.state_dir)

    def preview(self, request: dict[str, object]) -> ChangePlan:
        redacted_request = _redacted_request(request)
        built = self._build(request)
        before = self._observe_built(built)
        result = self._preview_built(built, before)
        operation = _required_str(redacted_request, "operation")
        plan = ChangePlan.previewed(
            operation=operation,
            environment_id=_required_str(redacted_request, "environment_id"),
            target_surfaces=[
                "capability" if operation == "catalog.patch" else "config"
            ],
            redacted_request=redacted_request,
            before_evidence=_observation_evidence(before),
            diff=_operation_diff(built),
            validation=result.validation,
            base_versions=self._base_versions(redacted_request),
        )
        self.payload_store.write(plan.id, request)
        try:
            return self.store.create(plan)
        except Exception:
            self.payload_store.delete(plan.id)
            raise

    def apply(self, change_id: str) -> ChangePlan:
        plan = self.store.get(change_id)
        if plan.status not in {"previewed", "approved"}:
            raise ConflictError(f"change_not_applicable:{plan.status}")
        request = self.payload_store.read(plan.id)
        if request is None:
            if plan.operation in {"mcp.copy", "mcp.remove"}:
                request = plan.redacted_request
            else:
                self._mark_failed(plan, "change_payload_missing")
                raise ValueError("change payload is no longer available")
        try:
            built = self._build(request)
            current = self._observe_built(built)
        except KeyError:
            return self._mark_stale(plan, "operation_input_changed")
        except ValueError:
            self._mark_failed(plan, "target_observation_failed")
            raise

        if not _matches_evidence(current, plan.before_evidence):
            return self._mark_stale(plan, "target_changed")
        if not self._source_is_current(plan):
            return self._mark_stale(plan, "source_changed")

        expected_document = (
            PatchEngine.apply(current.document, built.ops)
            if built.target is not None
            else None
        )
        expected_hash = (
            hashlib.sha256((built.standalone_content or "").encode("utf-8")).hexdigest()
            if built.is_standalone
            else None
        )
        patch_id = _patch_id_for_change(plan.id)
        applying = self.store.update(
            plan.with_updates(
                status="applying",
                backup_ref=patch_id,
                apply_result={
                    "patch_id": patch_id,
                    "applied": False,
                    "phase": "prepared",
                },
            )
        )
        try:
            result = self._apply_built(built, current, plan.id, patch_id)
        except ConflictError:
            return self._mark_stale(
                applying.with_updates(backup_ref=None),
                "target_changed_during_apply",
            )
        except Exception:
            if self.safe_edit_engine.backup_store.get(patch_id) is not None:
                return self._mark_applied_partial(
                    applying,
                    reason="apply_interrupted_after_backup",
                    applied=None,
                )
            self._mark_failed(applying, "apply_failed")
            raise

        applied = self.store.update(
            applying.with_updates(
                status="partial",
                apply_result={
                    "patch_id": result.patch_id,
                    "applied": result.applied,
                    "audit_event_id": result.audit_event_id,
                    "phase": "applied_pending_verification",
                },
                verification=ChangeVerification(
                    status="partial",
                    checks=[
                        {
                            "name": "post_apply_verification",
                            "passed": False,
                            "detail": "pending",
                        }
                    ],
                ),
            )
        )
        try:
            observed = self._observe_built(built)
        except Exception:
            return self._mark_applied_partial(
                applied,
                reason="target_reobservation_failed",
                applied=True,
            )

        matches = (
            observed.content_sha256 == expected_hash
            if built.is_standalone
            else observed.document == expected_document
        )
        checks: list[dict[str, object]] = [
            {
                "name": (
                    "content_matches_expected"
                    if built.is_standalone
                    else "document_matches_expected"
                ),
                "passed": matches,
            }
        ]
        try:
            self._post_mutation(plan.operation)
        except Exception:
            checks.append({"name": "post_apply_verification", "passed": False})
            return self._mark_applied_partial(
                applied,
                reason="post_apply_verification_failed",
                applied=True,
                observed=observed,
                checks=checks,
            )

        verification = ChangeVerification(
            status="verified" if matches else "partial",
            observed=_observation_evidence(observed),
            checks=checks,
        )
        updated = self.store.update(
            applied.with_updates(
                status=verification.status,
                apply_result={
                    "patch_id": result.patch_id,
                    "applied": result.applied,
                    "audit_event_id": result.audit_event_id,
                    "phase": "verified" if matches else "verification_partial",
                },
                verification=verification,
            )
        )
        if updated.status == "verified":
            self.payload_store.delete(plan.id)
        return updated

    def rollback(self, change_id: str) -> ChangePlan:
        plan = self.store.get(change_id)
        if plan.backup_ref is None:
            raise ConflictError("change_has_no_backup")
        if plan.status == "rolled_back":
            raise ConflictError("change_already_rolled_back")

        target = self._target_for_plan(plan)
        current = self._observe_reference(target)
        applied_hash = (
            plan.verification.observed.get("content_sha256")
            if plan.verification is not None
            else None
        )
        if isinstance(applied_hash, str) and current.content_sha256 != applied_hash:
            return self.store.update(
                plan.with_updates(
                    status="rollback_failed",
                    rollback={
                        "verified": False,
                        "reason": "target_changed_since_apply",
                    },
                )
            )

        try:
            result = self.safe_edit_engine.rollback(
                plan.backup_ref,
                source=f"change.rollback:{plan.id}",
            )
            observed = self._observe_reference(target)
            self._post_mutation(plan.operation)
        except Exception:
            self.store.update(
                plan.with_updates(
                    status="rollback_failed",
                    rollback={"verified": False, "reason": "rollback_failed"},
                )
            )
            raise

        verified = _matches_evidence(observed, plan.before_evidence)
        return self.store.update(
            plan.with_updates(
                status="rolled_back" if verified else "rollback_failed",
                rollback={
                    "patch_id": result.patch_id,
                    "verified": verified,
                    "observed": _observation_evidence(observed),
                },
            )
        )

    def get(self, change_id: str) -> ChangePlan:
        return self.store.get(change_id)

    def list(self, *, limit: int = 200) -> list[ChangePlan]:
        return self.store.list(limit=limit)

    def find_by_backup_ref(self, patch_id: str) -> ChangePlan | None:
        return self.store.find_by_backup_ref(patch_id)

    def invalidate(self, change_id: str, reason: str) -> ChangePlan:
        plan = self.store.get(change_id)
        if plan.status not in {"previewed", "approved"}:
            raise ConflictError(f"change_not_invalidatable:{plan.status}")
        return self._mark_stale(plan, reason)

    def _build(self, request: dict[str, object]) -> BuiltChange:
        operation = _required_str(request, "operation")
        environment_id = _required_str(request, "environment_id")
        if operation == "mcp.copy":
            from_tool = _required_str(request, "from_tool")
            to_tool = _required_str(request, "to_tool")
            if environment_id != to_tool:
                raise ValueError("environment_id must match to_tool")
            target, ops, summary = build_copy_patch(
                from_tool,
                to_tool,
                _required_str(request, "server"),
                self.home,
            )
            return BuiltChange(target=target, ops=ops, summary=summary)
        if operation == "mcp.remove":
            target, ops, summary = build_remove_patch(
                environment_id,
                _required_str(request, "server"),
                self.home,
            )
            return BuiltChange(target=target, ops=ops, summary=summary)
        if operation == "catalog.patch":
            cwd = _required_path(request, "cwd")
            built = catalog.build_surface_patch(
                environment_id,
                cwd,
                _raw_ops(request),
                home_dir=self.home,
            )
            return BuiltChange(
                target=built.target,
                ops=built.ops,
                standalone_path=built.standalone_path,
                standalone_content=built.standalone_content,
                surface_id=built.surface_id,
                summary=built.summary,
            )
        if operation == "config.patch":
            target, ops, summary = config_scope.build_config_patch(
                _required_str(request, "scope"),
                _required_path(request, "cwd"),
                _raw_ops(request),
                home_dir=self.home,
            )
            return BuiltChange(target=target, ops=ops, summary=summary)
        if operation == "harness_config.patch":
            target, ops, summary = harness_config.build_harness_config_patch(
                environment_id,
                _required_str(request, "scope"),
                _required_path(request, "cwd"),
                _raw_ops(request),
                home=self.home,
                file_name=_optional_str(request, "file"),
            )
            return BuiltChange(target=target, ops=ops, summary=summary)
        if operation == "profile.patch":
            target, ops, summary = profiles.build_profile_patch(
                request,
                _required_path(request, "cwd"),
            )
            return BuiltChange(target=target, ops=ops, summary=summary)
        if operation == "registry.patch":
            if self.registry_path is None:
                raise ValueError("registry path is not configured")
            target, ops, summary = registry.build_registry_patch(
                self.registry_path,
                request,
            )
            return BuiltChange(
                target=target,
                ops=ops,
                summary=summary,
                extra_validator=_registry_validator,
            )
        raise ValueError(f"unsupported change operation: {operation}")

    def _preview_built(
        self,
        built: BuiltChange,
        before: ObservedTarget,
    ) -> PatchResult:
        if built.target is not None:
            return self.safe_edit_engine.apply(
                built.target,
                built.ops,
                source="change.preview",
                dry_run=True,
                base_mtime=_mtime_seconds(before),
                extra_validator=built.extra_validator,
            )
        if built.standalone_path is None or built.standalone_content is None:
            raise ValueError("change has no target")
        return self.safe_edit_engine.apply_standalone(
            harness_id=_required_str(built.summary, "harness_id"),
            cwd=_required_path(built.summary, "cwd"),
            scope=str(built.summary.get("scope", "project")),
            file_path=built.standalone_path,
            content=built.standalone_content,
            surface_id=built.surface_id or "surface",
            source="change.preview",
            dry_run=True,
            base_mtime=_mtime_seconds(before),
        )

    def _apply_built(
        self,
        built: BuiltChange,
        current: ObservedTarget,
        change_id: str,
        patch_id: str,
    ) -> PatchResult:
        if built.target is not None:
            return self.safe_edit_engine.apply(
                built.target,
                built.ops,
                source=f"change.apply:{change_id}",
                base_mtime=_mtime_seconds(current),
                extra_validator=built.extra_validator,
                patch_id=patch_id,
            )
        if built.standalone_path is None or built.standalone_content is None:
            raise ValueError("change has no target")
        return self.safe_edit_engine.apply_standalone(
            harness_id=_required_str(built.summary, "harness_id"),
            cwd=_required_path(built.summary, "cwd"),
            scope=str(built.summary.get("scope", "project")),
            file_path=built.standalone_path,
            content=built.standalone_content,
            surface_id=built.surface_id or "surface",
            source=f"change.apply:{change_id}",
            base_mtime=_mtime_seconds(current),
            patch_id=patch_id,
        )

    def _observe_built(self, built: BuiltChange) -> ObservedTarget:
        if built.target is not None:
            return self.safe_edit_engine.observe_target(built.target)
        if built.standalone_path is None:
            raise ValueError("change has no target")
        return _observe_path(built.standalone_path)

    def _target_for_plan(self, plan: ChangePlan) -> PatchTarget | Path:
        request = plan.redacted_request
        operation = plan.operation
        environment_id = _required_str(request, "environment_id")
        if operation in {"mcp.copy", "mcp.remove"}:
            return PatchTarget(
                harness_id=environment_id,
                cwd=self.home,
                scope="user",
                target_kind="capability_mcp",
                kind="mcp_server",
                file_path=config_path(environment_id, self.home),
                file_format=config_format(environment_id),
            )
        if operation == "config.patch":
            return config_scope.config_patch_target(
                _required_str(request, "scope"),
                _required_path(request, "cwd"),
                home_dir=self.home,
            )
        if operation == "harness_config.patch":
            return harness_config.harness_config_patch_target(
                environment_id,
                _required_str(request, "scope"),
                _required_path(request, "cwd"),
                home=self.home,
                file_name=_optional_str(request, "file"),
            )
        if operation == "profile.patch":
            return profiles.profile_patch_target(
                _required_str(request, "scope"),
                _required_path(request, "cwd"),
            )
        if operation == "registry.patch":
            if self.registry_path is None:
                raise ValueError("registry path is not configured")
            return registry.registry_patch_target(
                self.registry_path,
                self.registry_path.parent,
            )
        if operation == "catalog.patch":
            return self._catalog_target_for_plan(request)
        raise ValueError(f"unsupported change operation: {operation}")

    def _catalog_target_for_plan(
        self,
        request: dict[str, object],
    ) -> PatchTarget | Path:
        environment_id = _required_str(request, "environment_id")
        cwd = _required_path(request, "cwd")
        raw_ops = _raw_ops(request)
        raw = raw_ops[0]
        op_name = _required_str(raw, "op")
        scope = _required_str(raw, "scope")
        if op_name in {"upsert_skill", "upsert_command"}:
            kind = "skill" if op_name == "upsert_skill" else "command"
            return catalog.resolve_standalone_surface_path(
                environment_id,
                scope,
                kind,
                _required_str(raw, "name"),
                cwd,
                self.home,
            )
        kind = (
            "mcp_server"
            if op_name in {"enable_mcp_server", "disable_mcp_server"}
            else "hook"
        )
        file_path, file_format = catalog.resolve_surface_write_target(
            environment_id,
            scope,
            kind,
            cwd,
            self.home,
        )
        return PatchTarget(
            harness_id=environment_id,
            cwd=cwd,
            scope=scope,
            target_kind="surface",
            kind=kind,
            file_path=file_path,
            file_format=file_format,
        )

    def _observe_reference(self, target: PatchTarget | Path) -> ObservedTarget:
        if isinstance(target, PatchTarget):
            return self.safe_edit_engine.observe_target(target)
        return _observe_path(target)

    def _base_versions(self, request: dict[str, object]) -> dict[str, object]:
        if request.get("operation") != "mcp.copy":
            return {}
        from_tool = _required_str(request, "from_tool")
        return {"source": _file_evidence(config_path(from_tool, self.home))}

    def _source_is_current(self, plan: ChangePlan) -> bool:
        expected = plan.base_versions.get("source")
        if not isinstance(expected, dict):
            return True
        from_tool = _required_str(plan.redacted_request, "from_tool")
        return _file_evidence(config_path(from_tool, self.home)) == expected

    def _post_mutation(self, operation: str) -> None:
        if operation == "registry.patch" and self.on_registry_change is not None:
            self.on_registry_change()

    def _mark_stale(self, plan: ChangePlan, reason: str) -> ChangePlan:
        self.payload_store.delete(plan.id)
        return self.store.update(
            plan.with_updates(
                status="stale",
                apply_result={"applied": False, "reason": reason},
            )
        )

    def _mark_failed(self, plan: ChangePlan, reason: str) -> ChangePlan:
        self.payload_store.delete(plan.id)
        return self.store.update(
            plan.with_updates(
                status="failed",
                backup_ref=None,
                apply_result={"applied": False, "reason": reason},
                verification=ChangeVerification(
                    status="failed",
                    checks=[{"name": reason, "passed": False}],
                ),
            )
        )

    def _mark_applied_partial(
        self,
        plan: ChangePlan,
        *,
        reason: str,
        applied: bool | None,
        observed: ObservedTarget | None = None,
        checks: list[dict[str, object]] | None = None,
    ) -> ChangePlan:
        apply_result = dict(plan.apply_result or {})
        apply_result.update(
            {
                "patch_id": plan.backup_ref,
                "applied": applied,
                "reason": reason,
                "phase": "applied_unverified",
            }
        )
        return self.store.update(
            plan.with_updates(
                status="partial",
                apply_result=apply_result,
                verification=ChangeVerification(
                    status="partial",
                    observed=(
                        _observation_evidence(observed) if observed is not None else {}
                    ),
                    checks=checks
                    or [{"name": "post_apply_verification", "passed": False}],
                ),
            )
        )


def _redacted_request(request: dict[str, object]) -> dict[str, object]:
    operation = _required_str(request, "operation")
    environment_id = _required_str(request, "environment_id")
    base: dict[str, object] = {
        "operation": operation,
        "environment_id": environment_id,
    }
    if operation == "mcp.copy":
        base.update(
            {
                "from_tool": _required_str(request, "from_tool"),
                "to_tool": _required_str(request, "to_tool"),
                "server": _required_str(request, "server"),
            }
        )
        return base
    if operation == "mcp.remove":
        base["server"] = _required_str(request, "server")
        return base
    if operation in {"config.patch", "harness_config.patch"}:
        base.update(
            {
                "scope": _required_str(request, "scope"),
                "cwd": str(_required_path(request, "cwd")),
                "ops": _structural_ops(_raw_ops(request)),
            }
        )
        file_name = _optional_str(request, "file")
        if file_name is not None:
            base["file"] = file_name
        return base
    if operation == "catalog.patch":
        raw_ops = _raw_ops(request)
        if len(raw_ops) != 1:
            raise ValueError("catalog change plans require exactly one semantic op")
        raw = raw_ops[0]
        structural = {
            key: raw[key]
            for key in ("op", "scope", "name", "event")
            if isinstance(raw.get(key), str)
        }
        base.update(
            {
                "cwd": str(_required_path(request, "cwd")),
                "ops": [structural],
            }
        )
        return base
    if operation == "profile.patch":
        action = _required_str(request, "action")
        base.update(
            {
                "action": action,
                "scope": _required_str(request, "scope"),
                "cwd": str(_required_path(request, "cwd")),
            }
        )
        if action == "upsert":
            raw_profile = request.get("profile")
            if not isinstance(raw_profile, dict):
                raise ValueError("profile is required")
            base["name"] = _required_str(raw_profile, "name")
        elif action == "delete":
            base["name"] = _required_str(request, "name")
            base["cascade"] = bool(request.get("cascade", False))
        elif action == "bind":
            base["project_path"] = _required_str(request, "project_path")
            base["run_profile"] = _required_str(request, "run_profile")
        else:
            raise ValueError(f"unsupported profile action: {action}")
        return base
    if operation == "registry.patch":
        action = _required_str(request, "action")
        base["action"] = action
        if action == "upsert":
            raw_agent = request.get("agent")
            if not isinstance(raw_agent, dict):
                raise ValueError("agent is required")
            base["agent_id"] = _required_str(raw_agent, "id")
        elif action == "disable":
            base["agent_id"] = _required_str(request, "agent_id")
        else:
            raise ValueError(f"unsupported registry action: {action}")
        return base
    raise ValueError(f"unsupported change operation: {operation}")


def _required_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value


def _optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_path(payload: dict[str, object], key: str) -> Path:
    return Path(_required_str(payload, key)).expanduser().resolve()


def _raw_ops(payload: dict[str, object]) -> list[dict[str, object]]:
    raw_ops = payload.get("ops")
    if not isinstance(raw_ops, list) or not raw_ops:
        raise ValueError("ops must not be empty")
    if not all(isinstance(raw, dict) for raw in raw_ops):
        raise ValueError("ops entries must be objects")
    return [dict(raw) for raw in raw_ops]


def _structural_ops(raw_ops: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            key: raw[key]
            for key in ("op", "path")
            if isinstance(raw.get(key), str)
        }
        for raw in raw_ops
    ]


def _observation_evidence(observed: ObservedTarget) -> dict[str, object]:
    return {
        "exists": observed.exists,
        "mtime_ns": observed.mtime_ns,
        "content_sha256": observed.content_sha256,
    }


def _matches_evidence(
    observed: ObservedTarget,
    evidence: dict[str, object],
) -> bool:
    return (
        observed.exists == evidence.get("exists")
        and observed.mtime_ns == evidence.get("mtime_ns")
        and observed.content_sha256 == evidence.get("content_sha256")
    )


def _observe_path(path: Path) -> ObservedTarget:
    evidence = _file_evidence(path)
    return ObservedTarget(
        exists=bool(evidence["exists"]),
        mtime_ns=evidence["mtime_ns"] if isinstance(evidence["mtime_ns"], int) else None,
        content_sha256=str(evidence["content_sha256"]),
        document={},
    )


def _file_evidence(path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "exists": False,
            "mtime_ns": None,
            "content_sha256": hashlib.sha256(b"").hexdigest(),
        }
    raw = path.read_bytes()
    return {
        "exists": True,
        "mtime_ns": path.stat().st_mtime_ns,
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _operation_diff(built: BuiltChange) -> dict[str, object]:
    if built.is_standalone:
        return {
            "operations": [
                {
                    "op": "write",
                    "path": built.surface_id or "surface",
                }
            ]
        }
    return {
        "operations": [
            {
                "op": op.op,
                "path": op.path,
            }
            for op in built.ops
        ]
    }


def _patch_id_for_change(change_id: str) -> str:
    return f"p_{change_id.removeprefix('chg_')}"


def _mtime_seconds(observed: ObservedTarget) -> float | None:
    return observed.mtime_ns / 1_000_000_000 if observed.mtime_ns is not None else None


def _registry_validator(document: dict[str, Any]) -> list[str]:
    errors, _warnings = registry.validate_registry_document(document)
    return errors
