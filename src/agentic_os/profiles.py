from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


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


def upsert_run_profile(
    profile: RunProfileInput,
    *,
    scope: str = "local",
    cwd: str | Path | None = None,
) -> RunProfileInput:
    if scope not in {"local", "global"}:
        raise ValueError(f"unsupported profile scope: {scope}")

    profile_path = global_profile_path() if scope == "global" else local_profile_path(cwd)
    bundle = _read_bundle(profile_path)
    run_profiles = dict(bundle.run_profiles)
    run_profiles[profile.name] = profile
    _write_bundle(
        profile_path,
        ProfileFileBundle(run_profiles=run_profiles, project_bindings=bundle.project_bindings),
    )
    return profile


def bind_project_profile(
    project_path: str,
    run_profile: str,
    cwd: str | Path | None,
) -> None:
    resolved_project = str(Path(project_path).resolve())
    local_path = local_profile_path(cwd)
    bundle = _read_bundle(local_path)
    filtered = [entry for entry in bundle.project_bindings if entry[0] != resolved_project]
    filtered.append((resolved_project, run_profile))
    updated = ProfileFileBundle(run_profiles=bundle.run_profiles, project_bindings=filtered)
    _write_bundle(local_path, updated)


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


def _write_bundle(profile_path: Path, bundle: ProfileFileBundle) -> None:
    lines: list[str] = []

    for profile_name in sorted(bundle.run_profiles.keys()):
        profile = bundle.run_profiles[profile_name]
        lines.append(f'[run_profiles."{_escape_toml_key(profile_name)}"]')
        lines.append(f"harness_id = {json.dumps(profile.harness_id)}")
        lines.append(f"provider = {json.dumps(profile.provider)}")
        lines.append(f"model = {json.dumps(profile.model)}")
        lines.append(f"message_prefix = {json.dumps(profile.message_prefix)}")
        lines.append(f"default_env = {_format_inline_table(profile.default_env)}")
        if profile.max_tokens_budget is not None:
            lines.append(f"max_tokens_budget = {profile.max_tokens_budget}")
        if profile.cwd_root is not None:
            lines.append(f"cwd_root = {json.dumps(profile.cwd_root)}")
        if profile.cwd_prefix is not None:
            lines.append(f"cwd_prefix = {json.dumps(profile.cwd_prefix)}")
        if profile.repo_glob is not None:
            lines.append(f"repo_glob = {json.dumps(profile.repo_glob)}")
        if profile.notes:
            lines.append(f"notes = {json.dumps(profile.notes)}")
        lines.append("")

    for project_path, profile_name in bundle.project_bindings:
        lines.append("[[project_profiles]]")
        lines.append(f"project_path = {json.dumps(project_path)}")
        lines.append(f"run_profile = {json.dumps(profile_name)}")
        lines.append("")

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _format_inline_table(values: dict[str, str]) -> str:
    if not values:
        return "{}"
    entries = [f"{json.dumps(k)} = {json.dumps(v)}" for k, v in sorted(values.items())]
    return "{ " + ", ".join(entries) + " }"


def _escape_toml_key(value: str) -> str:
    return value.replace("\\", r"\\").replace('"', r"\"")
