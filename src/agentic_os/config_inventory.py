"""Config inventory: read non-secret config summaries per tool (P34).

Reads tool-specific config files to extract model, provider, and
system prompt path. Explicitly does NOT read API keys, tokens, or
session state.

Each tool has a dedicated reader function. If the config format is
unknown or changes, the reader returns parse_error instead of
silently falling back.
"""
from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConfigSummary:
    config_source: str
    model: str | None = None
    provider: str | None = None
    system_prompt_path: str | None = None
    parse_error: str | None = None


# Dispatch table: agent_id -> reader function
_READERS: dict[str, Callable[[str], ConfigSummary]] = {}


def _register_reader(agent_id: str):
    """Decorator to register a config reader for an agent."""
    def decorator(func):
        _READERS[agent_id] = func
        return func
    return decorator


def read_config_summary(agent_id: str, config_path: str) -> ConfigSummary:
    """Read non-secret config summary for a tool.

    Dispatches to agent-specific reader. Returns ConfigSummary with
    parse_error if config cannot be read.
    """
    path = Path(config_path).expanduser()
    if not path.exists():
        return ConfigSummary(
            config_source=config_path,
            parse_error=f"config path does not exist: {config_path}",
        )

    reader = _READERS.get(agent_id)
    if reader is None:
        # Fallback: try generic JSON then TOML
        return _read_generic_config(config_path)

    try:
        return reader(str(path))
    except Exception as e:
        return ConfigSummary(
            config_source=config_path,
            parse_error=f"reader error: {str(e)[:200]}",
        )


def _read_generic_config(config_path: str) -> ConfigSummary:
    """Fallback: try reading config.json or config.toml."""
    path = Path(config_path)
    if path.is_file():
        # Direct file path — dispatch by extension
        if path.suffix == ".json":
            return _read_generic_json_config(str(path.parent), path.name)
        if path.suffix == ".toml":
            return _read_generic_toml_config(str(path.parent), path.name)
        return ConfigSummary(
            config_source=config_path,
            parse_error=f"unsupported file extension: {path.suffix}",
        )
    if path.is_dir():
        # Try common filenames
        for name in ["config.json", "settings.json", "config.toml"]:
            candidate = path / name
            if candidate.exists():
                if name.endswith(".json"):
                    return _read_generic_json_config(str(path), name)
                return _read_generic_toml_config(str(path), name)
        return ConfigSummary(
            config_source=config_path,
            parse_error="no recognized config file found",
        )
    return ConfigSummary(
        config_source=config_path,
        parse_error="config_path does not exist or is not a regular file/directory",
    )


@_register_reader("claude")
def _read_claude_config(config_path: str) -> ConfigSummary:
    """Read Claude Code settings from ~/.claude/settings.json."""
    path = Path(config_path)
    if not path.exists():
        return ConfigSummary(config_source=config_path, parse_error="path not found")

    # Claude stores config in settings.json
    settings_path = path / "settings.json" if path.is_dir() else path
    if not settings_path.exists():
        return ConfigSummary(
            config_source=str(settings_path),
            parse_error="settings.json not found",
        )

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return ConfigSummary(
            config_source=str(settings_path),
            parse_error=f"JSON parse error: {str(e)[:200]}",
        )

    return ConfigSummary(
        config_source=str(settings_path),
        model=data.get("model"),
        provider=data.get("provider"),
        system_prompt_path=data.get("system_prompt_path"),
    )


@_register_reader("codex")
def _read_codex_config(config_path: str) -> ConfigSummary:
    """Read Codex config from ~/.codex/config.toml."""
    path = Path(config_path)
    if not path.exists():
        return ConfigSummary(config_source=config_path, parse_error="path not found")

    config_file = path / "config.toml" if path.is_dir() else path
    if not config_file.exists():
        return ConfigSummary(
            config_source=str(config_file),
            parse_error="config.toml not found",
        )

    try:
        data = tomllib.loads(config_file.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        return ConfigSummary(
            config_source=str(config_file),
            parse_error=f"TOML parse error: {str(e)[:200]}",
        )

    # Codex stores model in [defaults] section
    defaults = data.get("defaults", {})
    return ConfigSummary(
        config_source=str(config_file),
        model=defaults.get("model"),
        provider=defaults.get("provider"),
    )


@_register_reader("cursor")
def _read_cursor_config(config_path: str) -> ConfigSummary:
    """Read Cursor config (VSCode-style settings.json)."""
    return _read_generic_json_config(config_path, "User/settings.json")


@_register_reader("opencode")
def _read_opencode_config(config_path: str) -> ConfigSummary:
    """Read OpenCode config."""
    return _read_generic_json_config(config_path, "config.json")


@_register_reader("qwen")
def _read_qwen_config(config_path: str) -> ConfigSummary:
    """Read Qwen config."""
    return _read_generic_json_config(config_path, "config.json")


@_register_reader("openclaw")
def _read_openclaw_config(config_path: str) -> ConfigSummary:
    """Read OpenClaw config."""
    return _read_generic_json_config(config_path, "config.json")


@_register_reader("hermes")
def _read_hermes_config(config_path: str) -> ConfigSummary:
    """Read Hermes config."""
    return _read_generic_toml_config(config_path, "config.toml")


def _read_generic_json_config(config_path: str, filename: str) -> ConfigSummary:
    """Read model/provider from a JSON config file."""
    path = Path(config_path)
    if path.is_dir():
        json_path = path / filename
    else:
        json_path = path

    if not json_path.exists():
        return ConfigSummary(
            config_source=str(json_path),
            parse_error=f"{filename} not found",
        )

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return ConfigSummary(
            config_source=str(json_path),
            parse_error=f"JSON parse error: {str(e)[:200]}",
        )

    # Extract known non-secret fields
    return ConfigSummary(
        config_source=str(json_path),
        model=data.get("model") or data.get("defaultModel"),
        provider=data.get("provider") or data.get("defaultProvider"),
        system_prompt_path=data.get("system_prompt_path") or data.get("systemPrompt"),
    )


def _read_generic_toml_config(config_path: str, filename: str) -> ConfigSummary:
    """Read model/provider from a TOML config file."""
    path = Path(config_path)
    if path.is_dir():
        toml_path = path / filename
    else:
        toml_path = path

    if not toml_path.exists():
        return ConfigSummary(
            config_source=str(toml_path),
            parse_error=f"{filename} not found",
        )

    try:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        return ConfigSummary(
            config_source=str(toml_path),
            parse_error=f"TOML parse error: {str(e)[:200]}",
        )

    # Try common TOML structures
    model = (
        data.get("model")
        or data.get("defaults", {}).get("model")
        or data.get("llm", {}).get("model")
    )
    provider = (
        data.get("provider")
        or data.get("defaults", {}).get("provider")
        or data.get("llm", {}).get("provider")
    )

    return ConfigSummary(
        config_source=str(toml_path),
        model=model,
        provider=provider,
    )


def read_inventory(agents: list) -> list[ConfigSummary]:
    """Read config summaries for a list of AgentDefinition objects."""
    results = []
    for agent in agents:
        if not agent.enabled or not agent.config_path:
            continue
        summary = read_config_summary(agent.id, agent.config_path)
        results.append(summary)
    return results
