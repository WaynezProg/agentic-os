from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agentic_os.patch_engine import PatchEngine, PatchOp
from agentic_os.safe_edit import PatchTarget
from agentic_os.toml_io import load_toml

PROFILE_HARNESS_ID = "agentic_os"
PROFILE_KIND = "run_profile"


class RunProfileInput(BaseModel):
    name: str
    harness_id: str
    provider: str
    model: str
    default_env: dict[str, str] = Field(default_factory=dict)
    message_prefix: str = ""
    max_tokens_budget: int | None = None
    notes: str = ""
    cwd_root: str | None = None
    cwd_prefix: str | None = None
    repo_glob: str | None = None


@dataclass(frozen=True)
class ResolvedRunProfile:
    name: str
    harness_id: str
    provider: str
    model: str
    message: str
    default_env: dict[str, str]
    max_tokens_budget: int | None = None


@dataclass(frozen=True)
class ProfileBindRequest:
    run_profile: str


@dataclass(frozen=True)
class ProfileFileBundle:
    run_profiles: dict[str, RunProfileInput]
    project_bindings: list[tuple[str, str]]


@dataclass(frozen=True)
class ProfileBinding:
    project_path: str
    run_profile: str


def global_profile_path() -> Path:
    return Path.home() / ".agentic-os" / "profiles.toml"


def local_profile_path(cwd: str | Path | None) -> Path:
    resolved = Path(cwd or Path.cwd()).resolve()
    return resolved / ".agentic-os" / "profiles.toml"


def list_profiles(cwd: str | Path | None) -> dict[str, RunProfileInput]:
    result: dict[str, RunProfileInput] = {}
    for profile in _load_profiles_from_path(global_profile_path()):
        result[profile.name] = profile
    for profile in _load_profiles_from_path(local_profile_path(cwd)):
        result[profile.name] = profile
    return result


def list_project_bindings(cwd: str | Path | None) -> list[tuple[str, str]]:
    merged: dict[str, str] = {}
    for project_path, profile_name in _load_bindings_from_path(global_profile_path()):
        merged[project_path] = profile_name
    for project_path, profile_name in _load_bindings_from_path(local_profile_path(cwd)):
        merged[project_path] = profile_name
    return [(project_path, profile_name) for project_path, profile_name in merged.items()]


def show_profile(name: str, cwd: str | Path | None) -> RunProfileInput | None:
    return list_profiles(cwd).get(name)


def profile_scope_map(cwd: str | Path | None) -> dict[str, str]:
    scopes: dict[str, str] = {}
    for profile in _load_profiles_from_path(global_profile_path()):
        scopes[profile.name] = "global"
    for profile in _load_profiles_from_path(local_profile_path(cwd)):
        scopes[profile.name] = "local"
    return scopes


def resolve_profile_scope(name: str, cwd: str | Path | None) -> str | None:
    return profile_scope_map(cwd).get(name)


def profile_file_path(scope: str, cwd: str | Path | None) -> Path:
    if scope not in {"local", "global"}:
        raise ValueError(f"unsupported profile scope: {scope}")
    return global_profile_path() if scope == "global" else local_profile_path(cwd)


def profile_patch_target(scope: str, cwd: Path) -> PatchTarget:
    file_path = profile_file_path(scope, cwd)
    return PatchTarget(
        harness_id=PROFILE_HARNESS_ID,
        cwd=cwd,
        scope=scope,
        target_kind=PROFILE_KIND,
        kind=PROFILE_KIND,
        file_path=file_path,
        file_format="toml",
    )


def profile_to_document_value(profile: RunProfileInput) -> dict[str, Any]:
    payload = profile.model_dump(exclude={"name"})
    result: dict[str, Any] = {
        "harness_id": payload["harness_id"],
        "provider": payload["provider"],
        "model": payload["model"],
    }
    if payload.get("default_env"):
        result["default_env"] = payload["default_env"]
    if payload.get("message_prefix"):
        result["message_prefix"] = payload["message_prefix"]
    if payload.get("max_tokens_budget") is not None:
        result["max_tokens_budget"] = payload["max_tokens_budget"]
    if payload.get("notes"):
        result["notes"] = payload["notes"]
    if payload.get("cwd_root"):
        result["cwd_root"] = payload["cwd_root"]
    if payload.get("cwd_prefix"):
        result["cwd_prefix"] = payload["cwd_prefix"]
    if payload.get("repo_glob"):
        result["repo_glob"] = payload["repo_glob"]
    return result


def project_profiles_document(bindings: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"project_path": project_path, "run_profile": profile_name} for project_path, profile_name in bindings]


def upsert_profile_ops(profile: RunProfileInput) -> list[PatchOp]:
    return [
        PatchOp(
            op="merge",
            path="run_profiles",
            value={profile.name: profile_to_document_value(profile)},
        )
    ]


def bind_project_profile_ops(
    bundle: ProfileFileBundle,
    project_path: str,
    run_profile: str,
) -> list[PatchOp]:
    resolved_project = str(Path(project_path).resolve())
    filtered = [entry for entry in bundle.project_bindings if entry[0] != resolved_project]
    filtered.append((resolved_project, run_profile))
    return [
        PatchOp(op="remove", path="project_profiles"),
        PatchOp(op="merge", path="project_profiles", value=project_profiles_document(filtered)),
    ]


def delete_profile_ops(
    name: str,
    bundle: ProfileFileBundle,
    *,
    cascade: bool,
) -> list[PatchOp]:
    ops: list[PatchOp] = [PatchOp(op="remove", path=f"run_profiles.{name}")]
    if cascade:
        filtered = [entry for entry in bundle.project_bindings if entry[1] != name]
        ops.extend(
            [
                PatchOp(op="remove", path="project_profiles"),
                PatchOp(
                    op="merge",
                    path="project_profiles",
                    value=project_profiles_document(filtered),
                ),
            ]
        )
    return ops


def bound_projects_for_profile(bundle: ProfileFileBundle, name: str) -> list[str]:
    return [project_path for project_path, profile_name in bundle.project_bindings if profile_name == name]


def profile_scope_diff(
    scope: str,
    other_scope: str,
    cwd: Path,
    *,
    name: str | None = None,
) -> dict[str, Any]:
    doc_a = load_toml(profile_file_path(scope, cwd))
    doc_b = load_toml(profile_file_path(other_scope, cwd))
    if name is not None:
        before = doc_a.get("run_profiles", {}).get(name)
        after = doc_b.get("run_profiles", {}).get(name)
        return {
            "scope": scope,
            "other_scope": other_scope,
            "name": name,
            "before": before,
            "after": after,
        }
    return {
        "scope": scope,
        "other_scope": other_scope,
        "diff": PatchEngine.diff(doc_a, doc_b),
    }


def resolve_project_profile(
    cwd: str | None,
    bindings: list[tuple[str, str]],
) -> str | None:
    if not cwd:
        return None
    resolved = str(Path(cwd).resolve())
    matched: tuple[int, str] | None = None
    for project_path, profile_name in bindings:
        normalized = _normalize_project_path(project_path)
        if resolved == normalized or resolved.startswith(normalized + "/"):
            if matched is None or len(normalized) > matched[0]:
                matched = (len(normalized), profile_name)
    if matched is None:
        return None
    return matched[1]


def resolve_profile(
    requested_profile: str | None,
    cwd: str | None,
    message: str,
    run_profiles: dict[str, RunProfileInput],
    project_bindings: list[tuple[str, str]],
    fallback_agent_id: str,
) -> tuple[str | None, ResolvedRunProfile | None, str]:
    resolved_name = requested_profile
    binding_matched = False
    if resolved_name is None:
        resolved_name = resolve_project_profile(cwd, project_bindings)
        binding_matched = resolved_name is not None

    profile = run_profiles.get(resolved_name) if resolved_name is not None else None

    if profile is None:
        if requested_profile is not None or binding_matched:
            raise ValueError(f"unknown run profile: {resolved_name}")
        profile = run_profiles.get("default")
        if profile is None:
            profile = run_profiles.get(fallback_agent_id)
        if profile is None:
            return None, None, message
        resolved_name = profile.name

    return (
        profile.name,
        ResolvedRunProfile(
            name=profile.name,
            harness_id=profile.harness_id,
            provider=profile.provider,
            model=profile.model,
            message=f"{profile.message_prefix}{message}",
            default_env=dict(profile.default_env),
            max_tokens_budget=profile.max_tokens_budget,
        ),
        f"{profile.message_prefix}{message}",
    )


def _normalize_project_path(project_path: str) -> str:
    return str(Path(project_path).resolve())


def _load_profiles_from_path(profile_path: Path) -> list[RunProfileInput]:
    return list(_read_bundle(profile_path).run_profiles.values())


def _load_bindings_from_path(profile_path: Path) -> list[tuple[str, str]]:
    return _read_bundle(profile_path).project_bindings


def _read_bundle(profile_path: Path) -> ProfileFileBundle:
    if not profile_path.exists():
        return ProfileFileBundle(run_profiles={}, project_bindings=[])

    raw = tomllib.loads(profile_path.read_text(encoding="utf-8"))
    profiles: dict[str, RunProfileInput] = {}
    for profile_name, payload in raw.get("run_profiles", {}).items():
        if not isinstance(profile_name, str) or not isinstance(payload, dict):
            continue
        profile = _parse_profile(profile_name, payload)
        if profile is not None:
            profiles[profile.name] = profile

    bindings: list[tuple[str, str]] = []
    for row in raw.get("project_profiles", []):
        if not isinstance(row, dict):
            continue
        project_path = row.get("project_path")
        profile_name = row.get("run_profile")
        if not isinstance(project_path, str) or not isinstance(profile_name, str):
            continue
        bindings.append((_normalize_project_path(project_path), profile_name))

    return ProfileFileBundle(run_profiles=profiles, project_bindings=bindings)


def _parse_profile(profile_name: str, payload: dict[str, Any]) -> RunProfileInput | None:
    required = {"harness_id", "provider", "model"}
    if not required.issubset(payload):
        return None

    default_env = payload.get("default_env")
    if not isinstance(default_env, dict):
        default_env = {}
    else:
        default_env = {
            key: str(value) for key, value in default_env.items() if isinstance(key, str)
        }

    message_prefix = payload.get("message_prefix")
    if not isinstance(message_prefix, str):
        message_prefix = ""

    max_tokens_budget = payload.get("max_tokens_budget")
    if max_tokens_budget is not None and not isinstance(max_tokens_budget, int):
        return None

    cwd_root = payload.get("cwd_root")
    if not isinstance(cwd_root, str):
        cwd_root = None

    cwd_prefix = payload.get("cwd_prefix")
    if not isinstance(cwd_prefix, str):
        cwd_prefix = None

    repo_glob = payload.get("repo_glob")
    if not isinstance(repo_glob, str):
        repo_glob = None

    notes = payload.get("notes")
    if not isinstance(notes, str):
        notes = ""

    return RunProfileInput(
        name=profile_name,
        harness_id=payload["harness_id"],
        provider=payload["provider"],
        model=payload["model"],
        default_env=default_env,
        message_prefix=message_prefix,
        max_tokens_budget=max_tokens_budget,
        notes=notes,
        cwd_root=cwd_root,
        cwd_prefix=cwd_prefix,
        repo_glob=repo_glob,
    )


