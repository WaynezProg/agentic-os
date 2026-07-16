from __future__ import annotations

import hashlib
from pathlib import Path

from agentic_os.change_models import ChangePlan, ChangeVerification
from agentic_os.change_store import ChangeStore
from agentic_os.mcp_alignment import (
    build_copy_patch,
    build_remove_patch,
    config_format,
    config_path,
)
from agentic_os.patch_engine import PatchEngine, PatchOp
from agentic_os.safe_edit import ConflictError, ObservedTarget, PatchTarget, SafeEditEngine


class ChangeService:
    def __init__(
        self,
        *,
        home: Path,
        store: ChangeStore,
        safe_edit_engine: SafeEditEngine,
    ) -> None:
        self.home = home
        self.store = store
        self.safe_edit_engine = safe_edit_engine

    def preview(self, request: dict[str, object]) -> ChangePlan:
        redacted_request = _redacted_request(request)
        target, ops, _ = self._build(redacted_request)
        before = self.safe_edit_engine.observe_target(target)
        result = self.safe_edit_engine.apply(
            target,
            ops,
            source="change.preview",
            dry_run=True,
            base_mtime=_mtime_seconds(before),
        )
        plan = ChangePlan.previewed(
            operation=_required_str(redacted_request, "operation"),
            environment_id=_required_str(redacted_request, "environment_id"),
            target_surfaces=["config"],
            redacted_request=redacted_request,
            before_evidence=_observation_evidence(before),
            diff=_operation_diff(ops),
            validation=result.validation,
            base_versions=self._base_versions(redacted_request),
        )
        return self.store.create(plan)

    def apply(self, change_id: str) -> ChangePlan:
        plan = self.store.get(change_id)
        if plan.status not in {"previewed", "approved"}:
            raise ConflictError(f"change_not_applicable:{plan.status}")
        try:
            target, ops, _ = self._build(plan.redacted_request)
            current = self.safe_edit_engine.observe_target(target)
        except KeyError:
            return self._mark_stale(plan, "operation_input_changed")
        except ValueError as exc:
            self._mark_failed(plan, "target_observation_failed")
            raise exc

        if not _matches_evidence(current, plan.before_evidence):
            return self._mark_stale(plan, "target_changed")
        if not self._source_is_current(plan):
            return self._mark_stale(plan, "source_changed")

        expected_document = PatchEngine.apply(current.document, ops)
        applying = self.store.update(plan.with_updates(status="applying"))
        try:
            result = self.safe_edit_engine.apply(
                target,
                ops,
                source=f"change.apply:{plan.id}",
                base_mtime=_mtime_seconds(current),
            )
            observed = self.safe_edit_engine.observe_target(target)
        except ConflictError:
            return self._mark_stale(applying, "target_changed_during_apply")
        except Exception:
            self._mark_failed(applying, "apply_failed")
            raise

        document_matches = observed.document == expected_document
        verification = ChangeVerification(
            status="verified" if document_matches else "partial",
            observed=_observation_evidence(observed),
            checks=[
                {
                    "name": "document_matches_expected",
                    "passed": document_matches,
                }
            ],
        )
        return self.store.update(
            applying.with_updates(
                status=verification.status,
                backup_ref=result.patch_id,
                apply_result={
                    "patch_id": result.patch_id,
                    "applied": result.applied,
                    "audit_event_id": result.audit_event_id,
                },
                verification=verification,
            )
        )

    def rollback(self, change_id: str) -> ChangePlan:
        plan = self.store.get(change_id)
        if plan.backup_ref is None:
            raise ConflictError("change_has_no_backup")
        if plan.status == "rolled_back":
            raise ConflictError("change_already_rolled_back")

        target = self._target_for_plan(plan)
        current = self.safe_edit_engine.observe_target(target)
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
            observed = self.safe_edit_engine.observe_target(target)
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

    def _build(
        self,
        request: dict[str, object],
    ) -> tuple[PatchTarget, list[PatchOp], dict[str, object]]:
        operation = _required_str(request, "operation")
        environment_id = _required_str(request, "environment_id")
        server = _required_str(request, "server")
        if operation == "mcp.copy":
            from_tool = _required_str(request, "from_tool")
            to_tool = _required_str(request, "to_tool")
            if environment_id != to_tool:
                raise ValueError("environment_id must match to_tool")
            return build_copy_patch(from_tool, to_tool, server, self.home)
        if operation == "mcp.remove":
            return build_remove_patch(environment_id, server, self.home)
        raise ValueError(f"unsupported change operation: {operation}")

    def _target_for_plan(self, plan: ChangePlan) -> PatchTarget:
        environment_id = _required_str(plan.redacted_request, "environment_id")
        return PatchTarget(
            harness_id=environment_id,
            cwd=self.home,
            scope="user",
            target_kind="capability_mcp",
            kind="mcp_server",
            file_path=config_path(environment_id, self.home),
            file_format=config_format(environment_id),
        )

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

    def _mark_stale(self, plan: ChangePlan, reason: str) -> ChangePlan:
        return self.store.update(
            plan.with_updates(
                status="stale",
                apply_result={"applied": False, "reason": reason},
            )
        )

    def _mark_failed(self, plan: ChangePlan, reason: str) -> ChangePlan:
        return self.store.update(
            plan.with_updates(
                status="failed",
                apply_result={"applied": False, "reason": reason},
                verification=ChangeVerification(
                    status="failed",
                    checks=[{"name": reason, "passed": False}],
                ),
            )
        )


def _redacted_request(request: dict[str, object]) -> dict[str, object]:
    operation = _required_str(request, "operation")
    allowed_keys = {
        "mcp.copy": ("operation", "environment_id", "from_tool", "to_tool", "server"),
        "mcp.remove": ("operation", "environment_id", "server"),
    }.get(operation)
    if allowed_keys is None:
        raise ValueError(f"unsupported change operation: {operation}")
    return {key: _required_str(request, key) for key in allowed_keys}


def _required_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value


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


def _operation_diff(ops: list[PatchOp]) -> dict[str, object]:
    return {
        "operations": [
            {
                "op": op.op,
                "path": op.path,
            }
            for op in ops
        ]
    }


def _mtime_seconds(observed: ObservedTarget) -> float | None:
    return observed.mtime_ns / 1_000_000_000 if observed.mtime_ns is not None else None
