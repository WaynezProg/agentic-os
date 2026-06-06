"""Configuration Scope Mapper.

Reads agentic-os config files across scopes (user/project/local),
merges them with priority resolution, and provides diff/explain views.
Does NOT modify any config files.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCOPES = ("managed", "user", "project", "local")
CONFIG_PATCH_SCOPES = ("user", "project", "local")
SCOPE_PRIORITY = {"local": 4, "project": 3, "user": 2, "managed": 1}
AGENTIC_CONFIG_SCHEMA_HARNESS = "agentic_os"


@dataclass(frozen=True)
class ConfigEntry:
    key: str
    value: Any
    scope: str
    source: str


@dataclass(frozen=True)
class ConfigView:
    harness_id: str
    entries: list[ConfigEntry] = field(default_factory=list)
    scopes_present: list[str] = field(default_factory=list)


def resolve_write_path(
    scope: str,
    cwd: str | None = None,
    home_dir: Path | None = None,
) -> Path:
    """Return config.toml path for a writable scope (user/project/local)."""
    if scope not in CONFIG_PATCH_SCOPES:
        msg = f"invalid scope: {scope}"
        raise ValueError(msg)
    paths = resolve_paths("shell", cwd, home_dir)
    path = paths.get(scope)
    if path is None:
        msg = f"invalid scope: {scope}"
        raise ValueError(msg)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resolve_paths(
    harness_id: str, cwd: str | None = None, home_dir: Path | None = None
) -> dict[str, Path | None]:
    """Resolve config file paths for each scope."""
    cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
    base_home = home_dir or Path.home()
    return {
        "managed": Path("/etc/agentic-os") / "config.toml",
        "user": base_home / ".agentic-os" / "config.toml",
        "project": cwd_path / ".agentic-os" / "config.toml",
        "local": cwd_path / ".agentic-os.local" / "config.toml",
    }


def read_config(path: Path) -> dict[str, Any]:
    """Read a TOML config file, returning empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def effective(
    harness_id: str,
    cwd: str | None = None,
    home_dir: Path | None = None,
) -> ConfigView:
    """Compute effective config by merging scopes with priority.

    Higher priority scope (local > project > user > managed) overrides lower.
    """
    cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
    base_home = home_dir or Path.home()
    paths: dict[str, Path] = {
        "managed": Path("/etc/agentic-os") / "config.toml",
        "user": base_home / ".agentic-os" / "config.toml",
        "project": cwd_path / ".agentic-os" / "config.toml",
        "local": cwd_path / ".agentic-os.local" / "config.toml",
    }
    all_entries: list[ConfigEntry] = []
    scopes_present: list[str] = []

    for scope_name in SCOPES:
        path = paths.get(scope_name)
        if path is None or not path.exists():
            continue
        config = read_config(path)
        if not config:
            continue
        scopes_present.append(scope_name)
        for key, value in config.items():
            all_entries.append(
                ConfigEntry(
                    key=key,
                    value=value,
                    scope=scope_name,
                    source=str(path),
                )
            )

    # Merge: higher priority wins
    merged: dict[str, ConfigEntry] = {}
    for entry in all_entries:
        existing = merged.get(entry.key)
        if existing is None or SCOPE_PRIORITY.get(entry.scope, 0) > SCOPE_PRIORITY.get(
            existing.scope, 0
        ):
            merged[entry.key] = entry

    return ConfigView(
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
    """Compare two scopes for the same harness."""
    base_home = home_dir or Path.home()
    cwd_path = Path(cwd).resolve() if cwd else Path.cwd()
    paths: dict[str, Path] = {
        "managed": Path("/etc/agentic-os") / "config.toml",
        "user": base_home / ".agentic-os" / "config.toml",
        "project": cwd_path / ".agentic-os" / "config.toml",
        "local": cwd_path / ".agentic-os.local" / "config.toml",
    }
    path_a = paths.get(scope_a)
    path_b = paths.get(scope_b)
    config_a = read_config(path_a) if path_a and path_a.exists() else {}
    config_b = read_config(path_b) if path_b and path_b.exists() else {}

    keys_a = set(config_a.keys())
    keys_b = set(config_b.keys())

    added = []
    removed = []
    modified = []

    for key in keys_b - keys_a:
        added.append({"key": key, "value": config_b[key], "scope": scope_b})

    for key in keys_a - keys_b:
        removed.append({"key": key, "value": config_a[key], "scope": scope_a})

    for key in keys_a & keys_b:
        if config_a[key] != config_b[key]:
            modified.append(
                {
                    "key": key,
                    "before": {"value": config_a[key], "scope": scope_a},
                    "after": {"value": config_b[key], "scope": scope_b},
                }
            )

    return {"added": added, "removed": removed, "modified": modified}


def explain(
    harness_id: str, cwd: str | None = None, home_dir: Path | None = None
) -> list[dict[str, Any]]:
    """Explain where each effective config value comes from."""
    view = effective(harness_id, cwd, home_dir)
    return [
        {
            "key": e.key,
            "value": e.value,
            "scope": e.scope,
            "source": e.source,
        }
        for e in view.entries
    ]
