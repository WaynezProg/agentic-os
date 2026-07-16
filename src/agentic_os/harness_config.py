"""Read harness-native configuration files (read-only).

Separate from agentic-os config scope mapper (`config_scope.py`).
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_os.catalog import SUPPORTED_HARNESSES
from agentic_os.control_plane import _redact_value
from agentic_os.patch_engine import PatchOp
from agentic_os.safe_edit import PatchTarget

HARNESS_CONFIG_SCOPES = ("user", "project", "local")
SCOPE_PRIORITY = {"local": 3, "project": 2, "user": 1}

_JSON_SETTINGS_NAME = {
    "claude": "settings.json",
    "qwen": "settings.json",
    "opencode": "config.json",
    "cursor": "cli-config.json",
}
_TOML_CONFIG_NAME = "config.toml"
_CURSOR_CONFIG_FILES = ("cli-config.json", "mcp.json", "hooks.json")


@dataclass(frozen=True)
class HarnessConfigEntry:
    key: str
    value: Any
    scope: str
    source: str


@dataclass(frozen=True)
class HarnessConfigView:
    harness_id: str
    entries: list[HarnessConfigEntry] = field(default_factory=list)
    scopes_present: list[str] = field(default_factory=list)


def _scope_base_dir(harness: str, scope: str, cwd: Path, home: Path) -> Path | None:
    if harness not in SUPPORTED_HARNESSES:
        return None
    if scope == "user":
        return home / _HARNESS_SCOPES_USER_REL[harness]
    if scope == "project":
        return cwd / _HARNESS_SCOPES_PROJECT_REL[harness]
    if scope == "local":
        return cwd / _HARNESS_SCOPES_LOCAL_REL[harness]
    return None


def _config_files_for_scope(harness: str, scope: str, cwd: Path, home: Path) -> list[Path]:
    base = _scope_base_dir(harness, scope, cwd, home)
    if base is None:
        return []
    if harness == "cursor":
        return [base / name for name in _CURSOR_CONFIG_FILES if (base / name).exists()]
    if harness in _JSON_SETTINGS_NAME:
        path = base / _JSON_SETTINGS_NAME[harness]
        return [path] if path.exists() else []
    path = base / _TOML_CONFIG_NAME
    return [path] if path.exists() else []


def _config_file_for_scope(harness: str, scope: str, cwd: Path, home: Path) -> Path | None:
    paths = _config_files_for_scope(harness, scope, cwd, home)
    return paths[0] if paths else None


# Relative paths under home (user) or cwd (project/local)
_HARNESS_SCOPES_USER_REL = {
    "claude": Path(".claude"),
    "codex": Path(".codex"),
    "opencode": Path(".config/opencode"),
    "qwen": Path(".qwen"),
    "openclaw": Path(".openclaw"),
    "hermes": Path(".hermes"),
    "cursor": Path(".cursor"),
}
_HARNESS_SCOPES_PROJECT_REL = {
    "claude": Path(".claude"),
    "codex": Path(".codex"),
    "opencode": Path(".opencode"),
    "qwen": Path(".qwen"),
    "openclaw": Path(".openclaw"),
    "hermes": Path(".hermes"),
    "cursor": Path(".cursor"),
}
_HARNESS_SCOPES_LOCAL_REL = {
    "claude": Path(".claude/local"),
    "codex": Path(".codex/local"),
    "opencode": Path(".opencode/local"),
    "qwen": Path(".qwen/local"),
    "openclaw": Path(".openclaw/local"),
    "hermes": Path(".hermes/local"),
    "cursor": Path(".cursor/local"),
}


def read_harness_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if path.suffix == ".json" or path.name.endswith(".json"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}


def effective(
    harness_id: str,
    cwd: str | None = None,
    home_dir: Path | None = None,
) -> HarnessConfigView:
    if harness_id not in SUPPORTED_HARNESSES:
        return HarnessConfigView(harness_id=harness_id)

    cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
    home = home_dir or Path.home()
    all_entries: list[HarnessConfigEntry] = []
    scopes_present: list[str] = []

    for scope_name in HARNESS_CONFIG_SCOPES:
        paths = _config_files_for_scope(harness_id, scope_name, cwd_path, home)
        if not paths:
            continue
        scope_has_config = False
        for path in paths:
            config = read_harness_config_file(path)
            if not config:
                continue
            scope_has_config = True
            for key, value in config.items():
                all_entries.append(
                    HarnessConfigEntry(
                        key=key,
                        value=_redact_value(value, key),
                        scope=scope_name,
                        source=str(path),
                    )
                )
        if scope_has_config and scope_name not in scopes_present:
            scopes_present.append(scope_name)

    merged: dict[str, HarnessConfigEntry] = {}
    for entry in all_entries:
        existing = merged.get(entry.key)
        if existing is None or SCOPE_PRIORITY.get(entry.scope, 0) > SCOPE_PRIORITY.get(
            existing.scope, 0
        ):
            merged[entry.key] = entry

    return HarnessConfigView(
        harness_id=harness_id,
        entries=list(merged.values()),
        scopes_present=scopes_present,
    )


def diff(
    harness_id: str,
    cwd: str | None = None,
    scope_a: str = "user",
    scope_b: str = "project",
    home_dir: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
    home = home_dir or Path.home()

    def _merged_scope_config(scope: str) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for path in _config_files_for_scope(harness_id, scope, cwd_path, home):
            merged.update(read_harness_config_file(path))
        return merged

    config_a = _merged_scope_config(scope_a)
    config_b = _merged_scope_config(scope_b)
    config_a = {k: _redact_value(v, k) for k, v in config_a.items()}
    config_b = {k: _redact_value(v, k) for k, v in config_b.items()}

    keys_a = set(config_a.keys())
    keys_b = set(config_b.keys())
    added = [{"key": key, "value": config_b[key], "scope": scope_b} for key in keys_b - keys_a]
    removed = [{"key": key, "value": config_a[key], "scope": scope_a} for key in keys_a - keys_b]
    modified = [
        {
            "key": key,
            "before": {"value": config_a[key], "scope": scope_a},
            "after": {"value": config_b[key], "scope": scope_b},
        }
        for key in keys_a & keys_b
        if config_a[key] != config_b[key]
    ]
    return {"added": added, "removed": removed, "modified": modified}


def explain(
    harness_id: str,
    cwd: str | None = None,
    home_dir: Path | None = None,
) -> list[dict[str, Any]]:
    view = effective(harness_id, cwd, home_dir)
    return [
        {
            "key": entry.key,
            "value": entry.value,
            "scope": entry.scope,
            "source": entry.source,
        }
        for entry in view.entries
    ]


def _default_config_file_name(harness: str, file_name: str | None = None) -> str:
    if harness == "cursor":
        return file_name or "cli-config.json"
    if harness in _JSON_SETTINGS_NAME:
        return _JSON_SETTINGS_NAME[harness]
    return _TOML_CONFIG_NAME


def resolve_write_path(
    harness: str,
    scope: str,
    cwd: Path,
    *,
    home: Path | None = None,
    file_name: str | None = None,
) -> tuple[Path, str]:
    """Return (path, format) for harness-native config writes."""
    if harness not in SUPPORTED_HARNESSES:
        msg = f"unsupported harness: {harness}"
        raise ValueError(msg)
    if scope not in HARNESS_CONFIG_SCOPES:
        msg = f"invalid scope: {scope}"
        raise ValueError(msg)
    home_path = home or Path.home()
    base = _scope_base_dir(harness, scope, cwd, home_path)
    if base is None:
        msg = f"unsupported harness: {harness}"
        raise ValueError(msg)

    resolved_name = _default_config_file_name(harness, file_name)
    if harness == "cursor" and resolved_name not in _CURSOR_CONFIG_FILES:
        msg = f"unsupported cursor config file: {resolved_name}"
        raise ValueError(msg)
    expected_name = _default_config_file_name(harness)
    if harness != "cursor" and file_name is not None and file_name != expected_name:
        msg = f"unsupported config file for {harness}: {file_name}"
        raise ValueError(msg)

    path = base / resolved_name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    fmt = "toml" if path.suffix == ".toml" else "json"
    return path, fmt


def harness_config_patch_target(
    harness: str,
    scope: str,
    cwd: Path,
    *,
    home: Path | None = None,
    file_name: str | None = None,
) -> PatchTarget:
    file_path, file_format = resolve_write_path(
        harness,
        scope,
        cwd,
        home=home,
        file_name=file_name,
    )
    return PatchTarget(
        harness_id=harness,
        cwd=cwd,
        scope=scope,
        target_kind="harness_config",
        kind=infer_patch_kind(harness, file_path),
        file_path=file_path,
        file_format=file_format,
    )


def build_harness_config_patch(
    harness: str,
    scope: str,
    cwd: Path,
    raw_ops: list[dict[str, object]],
    *,
    home: Path | None = None,
    file_name: str | None = None,
) -> tuple[PatchTarget, list[PatchOp], dict[str, object]]:
    if not raw_ops:
        raise ValueError("ops must not be empty")
    target = harness_config_patch_target(
        harness,
        scope,
        cwd,
        home=home,
        file_name=file_name,
    )
    ops: list[PatchOp] = []
    for raw in raw_ops:
        op = raw.get("op")
        path = raw.get("path")
        if not isinstance(op, str) or not isinstance(path, str):
            raise ValueError("patch op and path must be strings")
        ops.append(PatchOp(op=op, path=path, value=raw.get("value")))
    return target, ops, {
        "scope": scope,
        "file": target.file_path.name,
        "ops": [{"op": op.op, "path": op.path} for op in ops],
    }


def infer_patch_kind(harness: str, file_path: Path) -> str:
    """Map a harness config file to schema-registry kind."""
    if harness == "cursor":
        if file_path.name == "mcp.json":
            return "mcp_server"
        if file_path.name == "hooks.json":
            return "hook"
    return "harness_config"
