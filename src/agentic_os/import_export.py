"""Project setup import/export (P26).

Exports a portable bundle of profiles, control-plane catalog entries, registry
agents, and catalog surfaces. Import applies each change through the same
patch/upsert paths used by the HTTP API — never bulk raw writes.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agentic_os.audit import AuditStore
from agentic_os.catalog import (
    SUPPORTED_HARNESSES,
    resolve_standalone_surface_path,
    resolve_surface_write_target,
    scan as catalog_scan,
)
from agentic_os.control_plane import (
    ControlPlaneStore,
    McpServerUpsert,
    PolicyUpsert,
    SkillUpsert,
    _redact_value,
)
from agentic_os.control_plane_history import ControlPlaneMutationResult, entity_diff
from agentic_os.models import AgentDefinition
from agentic_os.patch_engine import PatchEngine, PatchOp
from agentic_os.profiles import (
    RunProfileInput,
    _read_bundle,
    local_profile_path,
    profile_patch_target,
    project_profiles_document,
    upsert_profile_ops,
)
from agentic_os.registry import (
    Registry,
    agents_document,
    merge_agent_instance,
    registry_patch_target,
    replace_agents_ops,
    validate_registry_document,
)
from agentic_os.run_templates import RunTemplateInput, RunTemplateStore
from agentic_os.safe_edit import PatchResult, PatchTarget, SafeEditEngine, ValidationError
from agentic_os.surface_ops import _MCP_PATH, compile_semantic_ops
from agentic_os.toml_io import load_toml

BUNDLE_VERSION = 1
PROJECT_ROOT_TOKEN = "${PROJECT_ROOT}"
HOME_TOKEN = "${HOME}"
_IMPORT_SOURCE = "setup_import"

_STRUCTURED_OPS = frozenset({"enable_mcp_server", "disable_mcp_server", "upsert_hook"})
_SECRET_KEY_PATTERN = re.compile(
    r"(?i)(token|secret|password|passwd|apikey|api_key|api-key|authorization|bearer)"
)
_JSON_SETTINGS_FILES = {
    "claude": "settings.json",
    "qwen": "settings.json",
    "opencode": "config.json",
    "cursor": "cli-config.json",
}
_HARNESS_PROJECT_DIRS = {
    "claude": ".claude",
    "codex": ".codex",
    "opencode": ".opencode",
    "qwen": ".qwen",
    "openclaw": ".openclaw",
    "hermes": ".hermes",
    "cursor": ".cursor",
}
_TOML_CONFIG_HARNESSES = frozenset({"openclaw", "hermes", "codex"})


class MissingEnvVarsError(Exception):
    def __init__(self, names: list[str]) -> None:
        self.names = sorted(names)
        super().__init__(f"missing required environment variables: {', '.join(self.names)}")


@dataclass(frozen=True)
class ImportExportContext:
    control_plane: ControlPlaneStore
    registry: Registry
    registry_path: Path
    safe_edit_engine: SafeEditEngine
    audit_store: AuditStore
    run_template_store: RunTemplateStore | None = None


def export_setup(ctx: ImportExportContext, cwd: str | Path) -> dict[str, Any]:
    cwd_path = Path(cwd).resolve()
    home = Path.home()

    local_bundle = _read_bundle(local_profile_path(cwd_path))
    run_profiles = [
        _export_profile(profile, cwd_path, home) for profile in local_bundle.run_profiles.values()
    ]
    project_bindings = [
        {
            "project_path": tokenize_path(project_path, cwd_path, home),
            "run_profile": profile_name,
        }
        for project_path, profile_name in local_bundle.project_bindings
    ]

    skills = [_redact_value(asdict(skill)) for skill in ctx.control_plane.list_skills()]
    mcp_servers = [_redact_value(asdict(server)) for server in ctx.control_plane.list_mcp_servers()]
    policies = [
        _export_policy(asdict(policy), cwd_path, home) for policy in ctx.control_plane.list_policies()
    ]
    registry_agents = [
        _export_registry_agent(agent.model_dump(exclude_none=True), cwd_path, home)
        for agent in ctx.registry.list_agents()
    ]

    catalog_surfaces: dict[str, list[dict[str, Any]]] = {}
    for harness in SUPPORTED_HARNESSES:
        records = [r for r in catalog_scan(harness, str(cwd_path)) if r.scope == "project"]
        if records:
            catalog_surfaces[harness] = [
                _export_surface(r, cwd_path, home) for r in records
            ]

    run_templates: list[dict[str, Any]] = []
    if ctx.run_template_store is not None:
        run_templates = [
            {
                "name": template.name,
                "harness_id": template.harness_id,
                "profile_name": template.profile_name,
                "cwd": tokenize_path(template.cwd, cwd_path, home),
                "message_template": template.message_template,
                "required_variables": template.required_variables,
                "approval_policy_hint": template.approval_policy_hint,
            }
            for template in ctx.run_template_store.list_templates(cwd=str(cwd_path))
        ]

    return {
        "version": BUNDLE_VERSION,
        "cwd": PROJECT_ROOT_TOKEN,
        "profiles": {
            "run_profiles": run_profiles,
            "project_bindings": project_bindings,
        },
        "skills": skills,
        "mcp_servers": mcp_servers,
        "policies": policies,
        "registry_agents": registry_agents,
        "catalog_surfaces": catalog_surfaces,
        "catalog_ops": _export_catalog_ops(cwd_path),
        "run_templates": run_templates,
    }


def import_setup(
    ctx: ImportExportContext,
    cwd: str | Path,
    bundle: dict[str, Any],
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    cwd_path = Path(cwd).resolve()
    home = Path.home()

    missing_env = _missing_env_vars(bundle)
    if missing_env:
        raise MissingEnvVarsError(missing_env)

    items: list[dict[str, Any]] = []
    unresolved_paths: list[str] = []

    items.extend(_import_skills(ctx, bundle, dry_run=dry_run))
    items.extend(_import_mcp(ctx, bundle, dry_run=dry_run))
    items.extend(
        _import_policies(ctx, bundle, cwd_path, home, dry_run=dry_run, unresolved_paths=unresolved_paths)
    )
    items.extend(
        _import_profiles(ctx, bundle, cwd_path, home, dry_run=dry_run, unresolved_paths=unresolved_paths)
    )
    items.extend(
        _import_registry(ctx, bundle, cwd_path, home, dry_run=dry_run, unresolved_paths=unresolved_paths)
    )
    items.extend(_import_catalog_ops(ctx, bundle, cwd_path, dry_run=dry_run))
    items.extend(
        _import_run_templates(
            ctx,
            bundle,
            cwd_path,
            home,
            dry_run=dry_run,
            unresolved_paths=unresolved_paths,
        )
    )

    return {
        "dry_run": dry_run,
        "cwd": str(cwd_path),
        "items": items,
        "unresolved_paths": unresolved_paths,
        "applied": not dry_run and any(item.get("applied") for item in items),
    }


def tokenize_path(path: str, cwd: Path, home: Path) -> str:
    if not path:
        return path
    resolved = Path(path).expanduser()
    try:
        resolved = resolved.resolve(strict=False)
    except OSError:
        return path
    cwd_resolved = cwd.resolve()
    home_resolved = home.resolve()
    if resolved == cwd_resolved:
        return PROJECT_ROOT_TOKEN
    try:
        rel = resolved.relative_to(cwd_resolved)
        suffix = "" if str(rel) == "." else f"/{rel}"
        return f"{PROJECT_ROOT_TOKEN}{suffix}"
    except ValueError:
        pass
    if resolved == home_resolved:
        return HOME_TOKEN
    try:
        rel = resolved.relative_to(home_resolved)
        suffix = "" if str(rel) == "." else f"/{rel}"
        return f"{HOME_TOKEN}{suffix}"
    except ValueError:
        return path


def detokenize_path(token: str, cwd: Path, home: Path) -> tuple[str, bool]:
    if token == PROJECT_ROOT_TOKEN:
        return str(cwd), True
    if token.startswith(f"{PROJECT_ROOT_TOKEN}/"):
        return str(cwd / token[len(PROJECT_ROOT_TOKEN) + 1 :]), True
    if token == HOME_TOKEN:
        return str(home), True
    if token.startswith(f"{HOME_TOKEN}/"):
        return str(home / token[len(HOME_TOKEN) + 1 :]), True
    if Path(token).expanduser().is_absolute():
        return str(Path(token).expanduser()), False
    return token, True


def collect_env_var_names(bundle: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for server in bundle.get("mcp_servers", []):
        if isinstance(server, dict):
            for key in server.get("env_keys", []):
                if isinstance(key, str) and key:
                    names.add(key.split("=", 1)[0].strip())
    profiles = bundle.get("profiles", {})
    if isinstance(profiles, dict):
        for profile in profiles.get("run_profiles", []):
            if not isinstance(profile, dict):
                continue
            default_env = profile.get("default_env", {})
            if isinstance(default_env, dict):
                for env_key, env_value in default_env.items():
                    if isinstance(env_key, str) and _is_env_var_reference(env_key, env_value):
                        names.add(env_key)
    for agent in bundle.get("registry_agents", []):
        if not isinstance(agent, dict):
            continue
        env = agent.get("env", {})
        if isinstance(env, dict):
            for env_key, env_value in env.items():
                if isinstance(env_key, str) and _SECRET_KEY_PATTERN.search(env_key):
                    if isinstance(env_value, str) and env_value:
                        names.add(env_value if value_is_env_name(env_value) else env_key)
    return names


def value_is_env_name(value: str) -> bool:
    return value not in {"[REDACTED]", ""} and value == value.upper().replace("-", "_")


def _missing_env_vars(bundle: dict[str, Any]) -> list[str]:
    required = collect_env_var_names(bundle)
    return sorted(name for name in required if name not in os.environ)


def _is_env_var_reference(key: str, value: object) -> bool:
    if not isinstance(value, str):
        return False
    if value in {key, "[REDACTED]"}:
        return True
    if value == f"${{{key}}}":
        return True
    return bool(_SECRET_KEY_PATTERN.search(key))


def _export_profile(profile: RunProfileInput, cwd: Path, home: Path) -> dict[str, Any]:
    payload = profile.model_dump(exclude_none=True)
    if payload.get("cwd_root"):
        payload["cwd_root"] = tokenize_path(payload["cwd_root"], cwd, home)
    if payload.get("default_env"):
        payload["default_env"] = _export_default_env(payload["default_env"])
    return _redact_profile_fields(payload)


def _redact_profile_fields(payload: dict[str, Any]) -> dict[str, Any]:
    preserved = {
        "default_env": payload.get("default_env"),
        "cwd_root": payload.get("cwd_root"),
        "cwd_prefix": payload.get("cwd_prefix"),
        "repo_glob": payload.get("repo_glob"),
        "max_tokens_budget": payload.get("max_tokens_budget"),
    }
    redacted = _redact_value({k: v for k, v in payload.items() if k not in preserved})
    return {**redacted, **{k: v for k, v in preserved.items() if v is not None}}


def _export_default_env(default_env: dict[str, str]) -> dict[str, str]:
    exported: dict[str, str] = {}
    for key, value in default_env.items():
        if _SECRET_KEY_PATTERN.search(key) or value == key:
            exported[key] = key
        else:
            exported[key] = str(_redact_value(value, key))
    return exported


def _export_policy(policy: dict[str, Any], cwd: Path, home: Path) -> dict[str, Any]:
    roots = policy.get("cwd_roots", [])
    if isinstance(roots, list):
        policy = {**policy, "cwd_roots": [tokenize_path(str(root), cwd, home) for root in roots]}
    return _redact_value(policy)


def _export_registry_agent(agent: dict[str, Any], cwd: Path, home: Path) -> dict[str, Any]:
    payload = dict(agent)
    if payload.get("config_path"):
        payload["config_path"] = tokenize_path(str(payload["config_path"]), cwd, home)
    for field in ("workspace_roots", "log_paths"):
        values = payload.get(field, [])
        if isinstance(values, list):
            payload[field] = [tokenize_path(str(value), cwd, home) for value in values]
    env = payload.get("env", {})
    if isinstance(env, dict):
        payload["env"] = _export_registry_env(env)
    return _redact_registry_fields(payload)


def _redact_registry_fields(payload: dict[str, Any]) -> dict[str, Any]:
    preserved = {
        "env": payload.get("env"),
        "config_path": payload.get("config_path"),
        "workspace_roots": payload.get("workspace_roots"),
        "log_paths": payload.get("log_paths"),
    }
    redacted = _redact_value({k: v for k, v in payload.items() if k not in preserved})
    return {**redacted, **{k: v for k, v in preserved.items() if v is not None}}


def _export_registry_env(env: dict[str, Any]) -> dict[str, str]:
    exported: dict[str, str] = {}
    for key, value in env.items():
        if not isinstance(key, str):
            continue
        if _SECRET_KEY_PATTERN.search(key):
            exported[key] = key
        elif isinstance(value, str):
            exported[key] = str(_redact_value(value, key))
        else:
            exported[key] = str(value)
    return exported


def _export_surface(record: object, cwd: Path, home: Path) -> dict[str, Any]:
    data = asdict(record)
    if data.get("source"):
        data["source"] = tokenize_path(str(data["source"]), cwd, home)
    return _redact_value(data)


def _export_catalog_ops(cwd: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for harness in SUPPORTED_HARNESSES:
        ops = _catalog_ops_for_harness(harness, cwd)
        if ops:
            entries.append({"harness": harness, "ops": ops})
    return entries


def _catalog_ops_for_harness(harness: str, cwd: Path) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    records = [
        r for r in catalog_scan(harness, str(cwd)) if r.scope == "project" and r.type == "mcp_server"
    ]
    for record in records:
        config = _read_project_mcp_config(harness, cwd, record.name)
        if not config:
            continue
        ops.append(
            {
                "op": "enable_mcp_server",
                "name": record.name,
                "scope": "project",
                "config": _redact_value(config),
            }
        )
    return ops


def _read_project_mcp_config(harness: str, cwd: Path, name: str) -> dict[str, Any] | None:
    if harness not in _HARNESS_PROJECT_DIRS:
        return None
    project_dir = cwd / _HARNESS_PROJECT_DIRS[harness]
    if harness in _JSON_SETTINGS_FILES:
        settings_path = project_dir / _JSON_SETTINGS_FILES[harness]
        if not settings_path.exists():
            return None
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        if isinstance(servers, dict):
            config = servers.get(name)
            return config if isinstance(config, dict) else None
        return None
    if harness in _TOML_CONFIG_HARNESSES:
        config_path = project_dir / "config.toml"
        if not config_path.exists():
            return None
        data = load_toml(config_path)
        key = _MCP_PATH.get(harness, "mcp_servers")
        servers = data.get(key, {})
        if isinstance(servers, dict):
            config = servers.get(name)
            return config if isinstance(config, dict) else None
    return None


def _import_skills(ctx: ImportExportContext, bundle: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in bundle.get("skills", []):
        if not isinstance(raw, dict) or "id" not in raw:
            continue
        skill_id = str(raw["id"])
        desired = SkillUpsert(
            label=str(raw.get("label", skill_id)),
            description=str(raw.get("description", "")),
            source=str(raw.get("source", "local")),
            entrypoint=str(raw.get("entrypoint", "")),
            tags=[str(tag) for tag in raw.get("tags", []) if isinstance(tag, str)],
            enabled=bool(raw.get("enabled", True)),
        )
        try:
            before = asdict(ctx.control_plane.get_skill(skill_id))
        except KeyError:
            before = None
        after = {**({"id": skill_id} if before is None else before), **asdict(desired)}
        diff = entity_diff(before, after) if before is not None else {"added": after}
        if before is not None and not diff:
            items.append({"domain": "skill", "entity_id": skill_id, "action": "unchanged"})
            continue
        if dry_run:
            items.append(
                {"domain": "skill", "entity_id": skill_id, "action": "upsert", "diff": diff, "applied": False}
            )
            continue
        mutation = ctx.control_plane.upsert_skill_tracked(skill_id, desired, source=_IMPORT_SOURCE)
        event = ctx.audit_store.record(
            "skill",
            skill_id,
            "skill_imported",
            f"imported skill {skill_id}",
            metadata={"source": _IMPORT_SOURCE, "diff": mutation.diff},
        )
        items.append(_control_plane_item("skill", skill_id, "upsert", mutation, event.id))
    return items


def _import_mcp(ctx: ImportExportContext, bundle: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in bundle.get("mcp_servers", []):
        if not isinstance(raw, dict) or "id" not in raw:
            continue
        server_id = str(raw["id"])
        desired = McpServerUpsert(
            label=str(raw.get("label", server_id)),
            description=str(raw.get("description", "")),
            transport=str(raw.get("transport", "stdio")),  # type: ignore[arg-type]
            command_preview=[str(part) for part in raw.get("command_preview", [])],
            url=raw.get("url"),
            env_keys=[str(key) for key in raw.get("env_keys", [])],
            enabled=bool(raw.get("enabled", True)),
        )
        try:
            before = asdict(ctx.control_plane.get_mcp_server(server_id))
        except KeyError:
            before = None
        after = {**({"id": server_id} if before is None else before), **asdict(desired)}
        diff = entity_diff(before, after) if before is not None else {"added": after}
        if before is not None and not diff:
            items.append({"domain": "mcp", "entity_id": server_id, "action": "unchanged"})
            continue
        if dry_run:
            items.append(
                {"domain": "mcp", "entity_id": server_id, "action": "upsert", "diff": diff, "applied": False}
            )
            continue
        mutation = ctx.control_plane.upsert_mcp_server_tracked(server_id, desired, source=_IMPORT_SOURCE)
        event = ctx.audit_store.record(
            "mcp",
            server_id,
            "mcp_imported",
            f"imported mcp server {server_id}",
            metadata={"source": _IMPORT_SOURCE, "diff": mutation.diff},
        )
        items.append(_control_plane_item("mcp", server_id, "upsert", mutation, event.id))
    return items


def _import_policies(
    ctx: ImportExportContext,
    bundle: dict[str, Any],
    cwd: Path,
    home: Path,
    *,
    dry_run: bool,
    unresolved_paths: list[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in bundle.get("policies", []):
        if not isinstance(raw, dict) or "agent_id" not in raw:
            continue
        agent_id = str(raw["agent_id"])
        cwd_roots, unresolved = _detokenize_paths(raw.get("cwd_roots", []), cwd, home)
        unresolved_paths.extend(unresolved)
        desired = PolicyUpsert(
            enabled=bool(raw.get("enabled", True)),
            readonly=bool(raw.get("readonly", False)),
            allowed_skill_ids=[str(v) for v in raw.get("allowed_skill_ids", [])],
            allowed_mcp_server_ids=[str(v) for v in raw.get("allowed_mcp_server_ids", [])],
            allowed_tool_names=[str(v) for v in raw.get("allowed_tool_names", [])],
            approval_required_tool_names=[str(v) for v in raw.get("approval_required_tool_names", [])],
            allowed_model_ids=[str(v) for v in raw.get("allowed_model_ids", [])],
            cwd_roots=cwd_roots,
            rate_limit_per_minute=int(raw.get("rate_limit_per_minute", 60)),
        )
        try:
            before = asdict(ctx.control_plane.get_policy(agent_id))
        except KeyError:
            before = None
        after = {**({"agent_id": agent_id} if before is None else before), **asdict(desired)}
        diff = entity_diff(before, after) if before is not None else {"added": after}
        if before is not None and not diff:
            items.append({"domain": "policy", "entity_id": agent_id, "action": "unchanged"})
            continue
        if dry_run:
            items.append(
                {"domain": "policy", "entity_id": agent_id, "action": "upsert", "diff": diff, "applied": False}
            )
            continue
        mutation = ctx.control_plane.upsert_policy_tracked(agent_id, desired, source=_IMPORT_SOURCE)
        event = ctx.audit_store.record(
            "policy",
            agent_id,
            "policy_imported",
            f"imported policy {agent_id}",
            metadata={"source": _IMPORT_SOURCE, "diff": mutation.diff},
        )
        items.append(_control_plane_item("policy", agent_id, "upsert", mutation, event.id))
    return items


def _import_profiles(
    ctx: ImportExportContext,
    bundle: dict[str, Any],
    cwd: Path,
    home: Path,
    *,
    dry_run: bool,
    unresolved_paths: list[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    profiles = bundle.get("profiles", {})
    if not isinstance(profiles, dict):
        return items

    for raw in profiles.get("run_profiles", []):
        if not isinstance(raw, dict) or "name" not in raw:
            continue
        profile = _profile_from_bundle(raw, cwd, home, unresolved_paths)
        target = profile_patch_target("local", cwd)
        ops = upsert_profile_ops(profile)
        before_doc = _load_patch_document(target)
        after_doc = PatchEngine.apply(before_doc, ops)
        if not PatchEngine.diff(before_doc, after_doc):
            items.append({"domain": "profile", "entity_id": profile.name, "action": "unchanged"})
            continue
        result = ctx.safe_edit_engine.apply(target, ops, source=_IMPORT_SOURCE, dry_run=dry_run)
        items.append(_patch_item("profile", profile.name, result))

    bindings_raw = profiles.get("project_bindings", [])
    if isinstance(bindings_raw, list) and bindings_raw:
        binding_pairs: list[tuple[str, str]] = []
        for row in bindings_raw:
            if not isinstance(row, dict):
                continue
            project_path = str(row.get("project_path", ""))
            profile_name = str(row.get("run_profile", ""))
            resolved, ok = detokenize_path(project_path, cwd, home)
            if not ok:
                unresolved_paths.append(project_path)
            binding_pairs.append((resolved, profile_name))
        ops = [
            PatchOp(op="remove", path="project_profiles"),
            PatchOp(op="merge", path="project_profiles", value=project_profiles_document(binding_pairs)),
        ]
        target = profile_patch_target("local", cwd)
        before_doc = _load_patch_document(target)
        after_doc = PatchEngine.apply(before_doc, ops)
        if PatchEngine.diff(before_doc, after_doc):
            result = ctx.safe_edit_engine.apply(target, ops, source=_IMPORT_SOURCE, dry_run=dry_run)
            items.append(_patch_item("profile_bindings", str(cwd), result))
        else:
            items.append({"domain": "profile_bindings", "entity_id": str(cwd), "action": "unchanged"})
    return items


def _import_registry(
    ctx: ImportExportContext,
    bundle: dict[str, Any],
    cwd: Path,
    home: Path,
    *,
    dry_run: bool,
    unresolved_paths: list[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in bundle.get("registry_agents", []):
        if not isinstance(raw, dict) or "id" not in raw:
            continue
        payload = _registry_agent_from_bundle(raw, cwd, home, unresolved_paths)
        agent = AgentDefinition.model_validate(payload)
        merged = merge_agent_instance(ctx.registry.list_agents(), agent)
        ops = replace_agents_ops(agents_document(merged))
        target = registry_patch_target(ctx.registry_path, cwd)
        before_doc = _load_patch_document(target)
        after_doc = PatchEngine.apply(before_doc, ops)
        if not PatchEngine.diff(before_doc, after_doc):
            items.append({"domain": "registry", "entity_id": agent.id, "action": "unchanged"})
            continue
        try:
            result = ctx.safe_edit_engine.apply(
                target,
                ops,
                source=_IMPORT_SOURCE,
                dry_run=dry_run,
                extra_validator=lambda doc: validate_registry_document(doc)[0],
            )
        except ValidationError as exc:
            items.append(
                {
                    "domain": "registry",
                    "entity_id": agent.id,
                    "action": "error",
                    "validation_errors": exc.errors,
                    "applied": False,
                }
            )
            continue
        if not dry_run:
            ctx.registry.reload()
        items.append(_patch_item("registry", agent.id, result))
    return items


def _import_catalog_ops(
    ctx: ImportExportContext,
    bundle: dict[str, Any],
    cwd: Path,
    *,
    dry_run: bool,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in bundle.get("catalog_ops", []):
        if not isinstance(entry, dict):
            continue
        harness = str(entry.get("harness", ""))
        ops = entry.get("ops", [])
        if harness not in SUPPORTED_HARNESSES or not isinstance(ops, list) or not ops:
            continue
        compiled = compile_semantic_ops(harness, ops)
        structured_ops = [op for op in ops if isinstance(op, dict) and str(op.get("op")) in _STRUCTURED_OPS]
        structured_target: PatchTarget | None = None
        if compiled.patch_ops and structured_ops:
            first_op = structured_ops[0]
            scope = str(first_op.get("scope", "project"))
            kind = _infer_surface_kind(str(first_op["op"]))
            file_path, file_format = resolve_surface_write_target(harness, scope, kind, cwd)
            structured_target = PatchTarget(
                harness_id=harness,
                cwd=cwd,
                scope=scope,
                target_kind="surface",
                kind=kind,
                file_path=file_path,
                file_format=file_format,
            )
        results = ctx.safe_edit_engine.apply_surface_batch(
            harness_id=harness,
            cwd=cwd,
            compiled=compiled,
            structured_target=structured_target,
            resolve_standalone_path=resolve_standalone_surface_path,
            source=_IMPORT_SOURCE,
            dry_run=dry_run,
        )
        for result in results:
            items.append(_patch_item(f"catalog:{harness}", result.patch_id, result))
    return items


def _profile_from_bundle(
    raw: dict[str, Any],
    cwd: Path,
    home: Path,
    unresolved_paths: list[str],
) -> RunProfileInput:
    payload = dict(raw)
    cwd_root = payload.get("cwd_root")
    if isinstance(cwd_root, str):
        resolved, ok = detokenize_path(cwd_root, cwd, home)
        if not ok:
            unresolved_paths.append(cwd_root)
        payload["cwd_root"] = resolved
    default_env = payload.get("default_env", {})
    if isinstance(default_env, dict):
        payload["default_env"] = _import_default_env(default_env)
    return RunProfileInput.model_validate(payload)


def _import_default_env(default_env: dict[str, Any]) -> dict[str, str]:
    imported: dict[str, str] = {}
    for key, value in default_env.items():
        if not isinstance(key, str):
            continue
        if value == "[REDACTED]" or _is_env_var_reference(key, value):
            imported[key] = os.environ[key]
        elif isinstance(value, str):
            imported[key] = value
        else:
            imported[key] = str(value)
    return imported


def _registry_agent_from_bundle(
    raw: dict[str, Any],
    cwd: Path,
    home: Path,
    unresolved_paths: list[str],
) -> dict[str, Any]:
    payload = dict(raw)
    config_path = payload.get("config_path")
    if isinstance(config_path, str):
        resolved, ok = detokenize_path(config_path, cwd, home)
        if not ok:
            unresolved_paths.append(config_path)
        payload["config_path"] = resolved
    for field in ("workspace_roots", "log_paths"):
        values = payload.get(field, [])
        if isinstance(values, list):
            payload[field], unresolved = _detokenize_paths(values, cwd, home)
            unresolved_paths.extend(unresolved)
    env = payload.get("env", {})
    if isinstance(env, dict):
        payload["env"] = _import_registry_env(env)
    return payload


def _import_registry_env(env: dict[str, Any]) -> dict[str, str]:
    imported: dict[str, str] = {}
    for key, value in env.items():
        if not isinstance(key, str):
            continue
        if _SECRET_KEY_PATTERN.search(key):
            env_name = key if not isinstance(value, str) or not value_is_env_name(value) else value
            imported[key] = os.environ[env_name]
        elif isinstance(value, str):
            imported[key] = value
        else:
            imported[key] = str(value)
    return imported


def _detokenize_paths(values: list[object], cwd: Path, home: Path) -> tuple[list[str], list[str]]:
    resolved_values: list[str] = []
    unresolved: list[str] = []
    for value in values:
        token = str(value)
        resolved, ok = detokenize_path(token, cwd, home)
        resolved_values.append(resolved)
        if not ok:
            unresolved.append(token)
    return resolved_values, unresolved


def _infer_surface_kind(op_name: str) -> str:
    if op_name in ("enable_mcp_server", "disable_mcp_server"):
        return "mcp_server"
    if op_name == "upsert_hook":
        return "hook"
    return "surface"


def _load_patch_document(target: PatchTarget) -> dict[str, Any]:
    if target.file_format == "json":
        if not target.file_path.exists():
            return {}
        try:
            data = json.loads(target.file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return load_toml(target.file_path)


def _control_plane_item(
    domain: str,
    entity_id: str,
    action: str,
    mutation: ControlPlaneMutationResult,
    audit_event_id: int | None,
) -> dict[str, Any]:
    return {
        "domain": domain,
        "entity_id": entity_id,
        "action": action,
        "patch_id": mutation.patch_id,
        "applied": mutation.applied,
        "diff": mutation.diff,
        "audit_event_id": audit_event_id,
    }


def bundle_has_no_secret_values(bundle: dict[str, Any]) -> bool:
    """Return True when serialized bundle contains no obvious secret literals."""
    text = json.dumps(bundle).lower()
    forbidden_markers = ("password=", "api_key=", "secret=", "bearer ")
    return not any(marker in text for marker in forbidden_markers)


def _patch_item(domain: str, entity_id: str, result: PatchResult) -> dict[str, Any]:
    return {
        "domain": domain,
        "entity_id": entity_id,
        "action": "patch",
        "patch_id": result.patch_id,
        "applied": result.applied,
        "diff": result.diff,
        "audit_event_id": result.audit_event_id,
        "validation": result.validation,
    }


def _import_run_templates(
    ctx: ImportExportContext,
    bundle: dict[str, Any],
    cwd: Path,
    home: Path,
    *,
    dry_run: bool,
    unresolved_paths: list[str],
) -> list[dict[str, Any]]:
    if ctx.run_template_store is None:
        return []
    raw_templates = bundle.get("run_templates", [])
    if not isinstance(raw_templates, list):
        return []
    items: list[dict[str, Any]] = []
    for raw in raw_templates:
        if not isinstance(raw, dict):
            continue
        payload = dict(raw)
        template_cwd = payload.get("cwd", PROJECT_ROOT_TOKEN)
        if isinstance(template_cwd, str):
            resolved, ok = detokenize_path(template_cwd, cwd, home)
            if not ok:
                unresolved_paths.append(template_cwd)
            payload["cwd"] = resolved
        request = RunTemplateInput(
            name=str(payload.get("name", "")),
            harness_id=str(payload.get("harness_id", "")),
            cwd=str(payload.get("cwd", str(cwd))),
            message_template=str(payload.get("message_template", "")),
            profile_name=payload.get("profile_name"),
            required_variables=[
                str(item) for item in payload.get("required_variables", []) if isinstance(item, str)
            ],
            approval_policy_hint=str(payload.get("approval_policy_hint", "")),
        )
        if dry_run:
            items.append(
                {
                    "domain": "run_template",
                    "entity_id": request.name,
                    "action": "upsert",
                    "applied": False,
                }
            )
            continue
        existing = {
            template.name: template
            for template in ctx.run_template_store.list_templates(cwd=str(cwd))
        }
        if request.name in existing:
            record = ctx.run_template_store.update(existing[request.name].id, request)
        else:
            record = ctx.run_template_store.create(request)
        items.append(
            {
                "domain": "run_template",
                "entity_id": record.name,
                "action": "upsert",
                "applied": True,
            }
        )
    return items
