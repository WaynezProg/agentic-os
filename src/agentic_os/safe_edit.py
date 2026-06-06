from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any

from agentic_os.audit import AuditStore
from agentic_os.backup_store import BackupStore
from agentic_os.control_plane import _redact_value
from agentic_os.jsonio import atomic_write_json
from agentic_os.patch_engine import PatchEngine, PatchOp
from agentic_os.schema_registry import SchemaRegistry
from agentic_os.surface_ops import CompiledSurfacePatch
from agentic_os.toml_io import atomic_write_toml, load_toml


@dataclass(frozen=True)
class PatchTarget:
    harness_id: str
    cwd: Path
    scope: str
    target_kind: str
    kind: str
    file_path: Path
    file_format: str  # json | toml
    surface_id: str | None = None


@dataclass(frozen=True)
class PatchResult:
    patch_id: str
    applied: bool
    diff: dict[str, Any]
    validation: dict[str, Any]
    backup: dict[str, Any] | None
    audit_event_id: int | None
    base_mtime: float | None = None


class ValidationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class ConflictError(Exception):
    pass


class SafeEditEngine:
    def __init__(
        self,
        *,
        state_dir: Path,
        backup_store: BackupStore,
        audit_store: AuditStore,
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.backup_store = backup_store
        self.audit_store = audit_store
        self.schema_registry = schema_registry or SchemaRegistry()

    def apply(
        self,
        target: PatchTarget,
        ops: list[PatchOp],
        *,
        source: str,
        dry_run: bool = False,
        base_mtime: float | None = None,
    ) -> PatchResult:
        patch_id = f"p_{uuid.uuid4().hex}"
        before = self._load_document(target)
        for op in ops:
            if not self.schema_registry.is_path_allowed(target.harness_id, target.kind, op.path):
                msg = f"forbidden path: {op.path}"
                raise PermissionError(msg)
        after = PatchEngine.apply(before, ops)
        errors = self.schema_registry.validate_document(target.harness_id, target.kind, after)
        validation = {"ok": not errors, "errors": errors}
        diff = PatchEngine.diff(before, after)
        file_path = target.file_path
        current_mtime = file_path.stat().st_mtime if file_path.exists() else None
        if errors:
            self.audit_store.record(
                domain="config_patch",
                entity_id=patch_id,
                event_type="config_patch_failed",
                message=f"validation failed for {target.harness_id}",
                metadata=_audit_metadata(target, patch_id, ops, before, after, source, dry_run=True),
            )
            raise ValidationError(errors)
        if base_mtime is not None and current_mtime is not None and base_mtime != current_mtime:
            msg = "stale_target"
            raise ConflictError(msg)
        would_backup = {
            "kind": "snapshot",
            "path": str(self.backup_store.patches_dir / patch_id / "before" / file_path.name),
        }
        if dry_run:
            return PatchResult(
                patch_id=patch_id,
                applied=False,
                diff=diff,
                validation=validation,
                backup=would_backup,
                audit_event_id=None,
                base_mtime=current_mtime,
            )
        entry = self.backup_store.create_snapshot(
            patch_id=patch_id,
            harness_id=target.harness_id,
            cwd=target.cwd,
            target_path=file_path,
            target_kind=target.target_kind,
            source=source,
            surface_id=target.surface_id,
        )
        self._write_document(target, after)
        event = self.audit_store.record(
            domain="config_patch",
            entity_id=patch_id,
            event_type="config_patch_applied",
            message=f"patched {target.harness_id} {target.kind}",
            metadata=_audit_metadata(target, patch_id, ops, before, after, source, dry_run=False),
        )
        return PatchResult(
            patch_id=patch_id,
            applied=True,
            diff=_redact_value(diff),
            validation=validation,
            backup={"kind": entry.backup_kind, "path": entry.backup_paths[0]},
            audit_event_id=event.id,
            base_mtime=current_mtime,
        )

    def apply_standalone(
        self,
        *,
        harness_id: str,
        cwd: Path,
        scope: str,
        file_path: Path,
        content: str,
        surface_id: str,
        source: str,
        dry_run: bool = False,
        base_mtime: float | None = None,
    ) -> PatchResult:
        patch_id = f"p_{uuid.uuid4().hex}"
        before_text = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        current_mtime = file_path.stat().st_mtime if file_path.exists() else None
        if base_mtime is not None and current_mtime is not None and base_mtime != current_mtime:
            msg = "stale_target"
            raise ConflictError(msg)
        validation = {"ok": True, "errors": []}
        diff = {
            "before_bytes": len(before_text.encode("utf-8")),
            "after_bytes": len(content.encode("utf-8")),
        }
        would_backup = {
            "kind": "sidecar",
            "path": str(file_path.with_name(f"{file_path.name}.bak.<ts>")),
        }
        if dry_run:
            return PatchResult(
                patch_id=patch_id,
                applied=False,
                diff=diff,
                validation=validation,
                backup=would_backup,
                audit_event_id=None,
                base_mtime=current_mtime,
            )
        file_path.parent.mkdir(parents=True, exist_ok=True)
        entry = self.backup_store.create_sidecar_indexed(
            patch_id=patch_id,
            harness_id=harness_id,
            cwd=cwd,
            target_path=file_path,
            target_kind="surface",
            source=source,
            surface_id=surface_id,
        )
        file_path.write_text(content, encoding="utf-8")
        event = self.audit_store.record(
            domain="config_patch",
            entity_id=patch_id,
            event_type="config_patch_applied",
            message=f"patched {harness_id} standalone {surface_id}",
            metadata=_standalone_audit_metadata(
                harness_id=harness_id,
                cwd=cwd,
                scope=scope,
                patch_id=patch_id,
                surface_id=surface_id,
                file_path=file_path,
                before_text=before_text,
                after_text=content,
                source=source,
                dry_run=False,
            ),
        )
        return PatchResult(
            patch_id=patch_id,
            applied=True,
            diff=_redact_value(diff),
            validation=validation,
            backup={"kind": entry.backup_kind, "path": entry.backup_paths[0]},
            audit_event_id=event.id,
            base_mtime=current_mtime,
        )

    def apply_surface_batch(
        self,
        *,
        harness_id: str,
        cwd: Path,
        compiled: CompiledSurfacePatch,
        structured_target: PatchTarget | None,
        resolve_standalone_path: Callable[..., Path],
        source: str,
        dry_run: bool = False,
        base_mtime: float | None = None,
    ) -> list[PatchResult]:
        results: list[PatchResult] = []
        if compiled.patch_ops:
            if structured_target is None:
                msg = "structured_target required for patch ops"
                raise ValueError(msg)
            results.append(
                self.apply(
                    structured_target,
                    compiled.patch_ops,
                    source=source,
                    dry_run=dry_run,
                    base_mtime=base_mtime,
                )
            )
        for standalone in compiled.standalone_files:
            file_path = resolve_standalone_path(
                harness_id,
                standalone.scope,
                standalone.kind,
                standalone.name,
                cwd,
            )
            surface_id = f"{standalone.kind}:{standalone.name}@{standalone.scope}"
            results.append(
                self.apply_standalone(
                    harness_id=harness_id,
                    cwd=cwd,
                    scope=standalone.scope,
                    file_path=file_path,
                    content=standalone.content,
                    surface_id=surface_id,
                    source=source,
                    dry_run=dry_run,
                    base_mtime=base_mtime,
                )
            )
        return results

    def rollback(self, patch_id: str, *, source: str) -> PatchResult:
        entry = self.backup_store.get(patch_id)
        if entry is None:
            raise LookupError("patch_not_found")
        if entry.rolled_back_at is not None:
            raise ConflictError("already_rolled_back")
        self.backup_store.restore(entry)
        self.backup_store.mark_rolled_back(patch_id)
        rollback_id = f"p_{uuid.uuid4().hex}"
        event = self.audit_store.record(
            domain="config_patch",
            entity_id=rollback_id,
            event_type="config_patch_rolled_back",
            message=f"rolled back {patch_id}",
            metadata={"rollback_of": patch_id, "source": source},
        )
        return PatchResult(
            patch_id=rollback_id,
            applied=True,
            diff={},
            validation={"ok": True, "errors": []},
            backup=None,
            audit_event_id=event.id,
        )

    def _load_document(self, target: PatchTarget) -> dict[str, Any]:
        if target.file_format == "json":
            if not target.file_path.exists():
                return {}
            try:
                data = json.loads(target.file_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}
        return load_toml(target.file_path)

    def _write_document(self, target: PatchTarget, doc: dict[str, Any]) -> None:
        if target.file_format == "json":
            atomic_write_json(target.file_path, doc)
        else:
            atomic_write_toml(target.file_path, doc)


def _audit_metadata(
    target: PatchTarget,
    patch_id: str,
    ops: list[PatchOp],
    before: dict[str, Any],
    after: dict[str, Any],
    source: str,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    return _redact_value(
        {
            "patch_id": patch_id,
            "harness_id": target.harness_id,
            "scope": target.scope,
            "cwd": str(target.cwd.resolve()),
            "target_kind": target.target_kind,
            "surface_id": target.surface_id,
            "ops": [{"op": o.op, "path": o.path, "value": o.value} for o in ops],
            "before_hash": _hash_doc(before),
            "after_hash": _hash_doc(after),
            "source": source,
            "dry_run": dry_run,
        }
    )


def _hash_doc(doc: dict[str, Any]) -> str:
    payload = json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _hash_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _standalone_audit_metadata(
    *,
    harness_id: str,
    cwd: Path,
    scope: str,
    patch_id: str,
    surface_id: str,
    file_path: Path,
    before_text: str,
    after_text: str,
    source: str,
    dry_run: bool,
) -> dict[str, Any]:
    return _redact_value(
        {
            "patch_id": patch_id,
            "harness_id": harness_id,
            "scope": scope,
            "cwd": str(cwd.resolve()),
            "target_kind": "surface",
            "surface_id": surface_id,
            "target_path": str(file_path),
            "before_hash": _hash_text(before_text),
            "after_hash": _hash_text(after_text),
            "source": source,
            "dry_run": dry_run,
        }
    )
