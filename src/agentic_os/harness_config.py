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
from agentic_os.control_plane import _SECRET_KEY_PATTERN, _redact_text

HARNESS_CONFIG_SCOPES = ("user", "project", "local")
SCOPE_PRIORITY = {"local": 3, "project": 2, "user": 1}

_JSON_SETTINGS_NAME = {
    "claude": "settings.json",
    "qwen": "settings.json",
    "opencode": "config.json",
}
_TOML_CONFIG_NAME = "config.toml"


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


def _config_file_for_scope(harness: str, scope: str, cwd: Path, home: Path) -> Path | None:
    if harness not in SUPPORTED_HARNESSES:
        return None
    if scope == "user":
        base = home / _HARNESS_SCOPES_USER_REL[harness]
    elif scope == "project":
        base = cwd / _HARNESS_SCOPES_PROJECT_REL[harness]
    elif scope == "local":
        base = cwd / _HARNESS_SCOPES_LOCAL_REL[harness]
    else:
        return None
    if harness in _JSON_SETTINGS_NAME:
        return base / _JSON_SETTINGS_NAME[harness]
    return base / _TOML_CONFIG_NAME


# Relative paths under home (user) or cwd (project/local)
_HARNESS_SCOPES_USER_REL = {
    "claude": Path(".claude"),
    "codex": Path(".codex"),
    "opencode": Path(".config/opencode"),
    "qwen": Path(".qwen"),
    "openclaw": Path(".openclaw"),
    "hermes": Path(".hermes"),
}
_HARNESS_SCOPES_PROJECT_REL = {
    "claude": Path(".claude"),
    "codex": Path(".codex"),
    "opencode": Path(".opencode"),
    "qwen": Path(".qwen"),
    "openclaw": Path(".openclaw"),
    "hermes": Path(".hermes"),
}
_HARNESS_SCOPES_LOCAL_REL = {
    "claude": Path(".claude/local"),
    "codex": Path(".codex/local"),
    "opencode": Path(".opencode/local"),
    "qwen": Path(".qwen/local"),
    "openclaw": Path(".openclaw/local"),
    "hermes": Path(".hermes/local"),
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


def _redact_value(value: Any, key: str | None = None) -> Any:
    if isinstance(value, str):
        if key and _SECRET_KEY_PATTERN.search(key):
            return "[REDACTED]"
        return _redact_text(value)
    if isinstance(value, dict):
        return {str(k): _redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


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
        path = _config_file_for_scope(harness_id, scope_name, cwd_path, home)
        if path is None or not path.exists():
            continue
        config = read_harness_config_file(path)
        if not config:
            continue
        scopes_present.append(scope_name)
        for key, value in config.items():
            all_entries.append(
                HarnessConfigEntry(
                    key=key,
                    value=_redact_value(value, key),
                    scope=scope_name,
                    source=str(path),
                )
            )

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
    path_a = _config_file_for_scope(harness_id, scope_a, cwd_path, home)
    path_b = _config_file_for_scope(harness_id, scope_b, cwd_path, home)
    config_a = read_harness_config_file(path_a) if path_a else {}
    config_b = read_harness_config_file(path_b) if path_b else {}
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
