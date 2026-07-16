from __future__ import annotations

from dataclasses import dataclass

from agentic_os.adapter_contract import SEMANTIC_HARNESS_IDS


@dataclass(frozen=True)
class EnvironmentAdapter:
    id: str
    label: str
    tool_kind: str
    binary_name: str
    config_relative_path: str
    desktop_app_names: tuple[str, ...] = ()
    ide_app_names: tuple[str, ...] = ()
    cli: bool = True
    config: bool = True
    capabilities: bool = True
    runtime: bool = False
    desktop: bool = False
    ide: bool = False
    native_sessions: bool = False


_ADAPTERS = (
    EnvironmentAdapter(
        id="claude",
        label="Claude Code",
        tool_kind="vibe_coding",
        binary_name="claude",
        config_relative_path=".claude",
        desktop_app_names=("Claude.app",),
        desktop=True,
        native_sessions=True,
    ),
    EnvironmentAdapter(
        id="codex",
        label="Codex",
        tool_kind="vibe_coding",
        binary_name="codex",
        config_relative_path=".codex",
        desktop_app_names=("Codex.app", "ChatGPT.app"),
        desktop=True,
        native_sessions=True,
    ),
    EnvironmentAdapter(
        id="cursor",
        label="Cursor",
        tool_kind="vibe_coding",
        binary_name="cursor",
        config_relative_path=".cursor",
        desktop_app_names=("Cursor.app",),
        ide_app_names=("Cursor.app",),
        desktop=True,
        ide=True,
    ),
    EnvironmentAdapter(
        id="hermes",
        label="Hermes",
        tool_kind="agentic_runtime",
        binary_name="hermes",
        config_relative_path=".hermes",
        runtime=True,
    ),
    EnvironmentAdapter(
        id="openclaw",
        label="OpenClaw",
        tool_kind="agentic_runtime",
        binary_name="openclaw",
        config_relative_path=".openclaw",
        runtime=True,
    ),
    EnvironmentAdapter(
        id="opencode",
        label="OpenCode",
        tool_kind="vibe_coding",
        binary_name="opencode",
        config_relative_path=".config/opencode",
        desktop_app_names=("OpenCode.app",),
        desktop=True,
    ),
    EnvironmentAdapter(
        id="qwen",
        label="Qwen",
        tool_kind="vibe_coding",
        binary_name="qwen",
        config_relative_path=".qwen",
    ),
)
_BY_ID = {adapter.id: adapter for adapter in _ADAPTERS}

if tuple(_BY_ID) != SEMANTIC_HARNESS_IDS:
    raise RuntimeError("environment adapters must match SEMANTIC_HARNESS_IDS")


def iter_adapters() -> tuple[EnvironmentAdapter, ...]:
    return _ADAPTERS


def get_adapter(
    environment_id: str,
    *,
    required: bool = True,
) -> EnvironmentAdapter | None:
    adapter = _BY_ID.get(environment_id)
    if adapter is None and required:
        raise KeyError(f"unknown environment adapter: {environment_id}")
    return adapter
