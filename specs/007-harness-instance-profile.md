# 007 — Harness Instance Profile (P4)

Status: Draft
Date: 2026-05-28

## Positioning

P4 defines Harness Instance Profile documents for Harness Manager metadata. A
profile describes how `agentic-os` can locate, launch, health-check, attach to,
and inspect logs for one configured harness instance such as `openclaw@work`.

P4 is not a harness, not a second OpenClaw, and not an agent runtime. It does
not define runtime behavior inside OpenClaw, Hermes, Codex, Claude Code, Gemini
CLI, OpenCode, or any other underlying harness.

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P4 | Harness Instance Profile spec | management metadata for each harness instance | config path, workspace roots, launch/health/attach/log commands, default provider | harness internals, planning, tool execution |

## Allowed Fields

Harness Instance Profile may describe only these fields:

```text
id
name
config_path
workspace_roots
launch_command
health_command
attach_command
log_paths
default_provider
```

Field meanings:

- `id`: stable path-safe id, for example `openclaw@work`.
- `name`: human-readable display name.
- `config_path`: local configuration file or directory used by the harness.
- `workspace_roots`: allowed local workspace roots for this harness instance.
- `launch_command`: command preview used to start a Harness Run.
- `health_command`: command preview used to verify the harness is reachable.
- `attach_command`: command preview used to attach to an existing harness
  context.
- `log_paths`: known local log paths for operator inspection.
- `default_provider`: default model/provider label for display and policy input.

Example:

```toml
id = "openclaw@work"
name = "OpenClaw Work"
config_path = "~/.openclaw/config.toml"
workspace_roots = ["~/work", "~/bootstrap"]
launch_command = ["openclaw", "agent", "--message", "{{message}}"]
health_command = ["openclaw", "status"]
attach_command = ["openclaw", "attach"]
log_paths = ["~/.openclaw/logs"]
default_provider = "openai"
```

## Forbidden Fields

Harness Instance Profile must not describe or imply ownership of:

- tool loop, planner, executor, browser driver, memory reasoning, or task
  decomposition;
- internal prompt routing, model reasoning, agent memory, autonomous planning,
  task queues, or tool execution;
- MCP server process ownership, capability installation, credentials, secrets,
  or remote sync.

Those belong to the underlying harness or future explicit specs, not the Harness
Manager profile layer.

## Compatibility

Existing P0-P3.6 API, CLI, and SQLite names remain unchanged. P4 is a
positioning and schema-language spec for management metadata; adopting it must
not require changing current API routes, CLI commands, runtime architecture, or
SQLite tables.
