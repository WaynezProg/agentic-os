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
