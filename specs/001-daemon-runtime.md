# 001 Daemon Runtime

Status: Awaiting written spec review
Date: 2026-05-27

## Positioning

`agentic-os` is a local Harness Manager substrate. P0 proves one thing:
configured harness instances can be launched, observed, stopped, and replayed
through a stable daemon/CLI contract.

It is not a Claude OS clone, a second OpenClaw, or an agent runtime. Claude OS is
useful as a reference for simplified run state, knowledge-base layering,
capability catalogs, and lifecycle ideas, but P0 does not build memory, RAG,
Shared Capability Catalog management, Harness Launch Policy, Kanban, chat UI,
or repo-wide indexing.

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P0 | daemon, CLI, configured runners, process/log/session records | Harness Instance Registry and Harness Run lifecycle | local launch, stop, retry, logs, artifacts | harness internals, planning, tool execution |

## Goals

- Register local harness instances such as OpenClaw, Hermes, Codex, Claude Code,
  Gemini CLI, and OpenCode.
- Start a harness run from a selected working directory.
- Track each run as a Harness Session with durable metadata.
- Capture stdout and stderr as append-only logs.
- Stop the entire process group for a running session.
- Keep artifacts under a per-session folder.
- Provide a CLI that works before any web UI exists.

## Non-Goals

- No React/Tauri/Electron UI in P0.
- No memory extraction or promotion pipeline in P0.
- No Shared Capability Catalog install or Harness Launch Policy editing in P0.
- No merged chat UI across agents.
- No full repo embedding or semantic indexing.
- No remote multi-user mode, auth, or RBAC.

## Components

```text
agentic-os
├── agentd
│   ├── harness instance registry
│   ├── harness run lifecycle manager
│   ├── process supervisor
│   ├── log writer
│   └── artifact manager
├── agentctl
│   └── CLI client for daemon/API operations
└── storage
    ├── SQLite metadata
    ├── JSONL logs
    └── per-session artifact folders
```

## Harness Instance Registry

The registry is configuration, not code. The current TOML and API labels still
use `agents` for compatibility; conceptually each record is a harness instance
definition:

- `id`: stable id, for example `openclaw`.
- `label`: display name.
- `command`: executable and default argv template.
- `cwd_mode`: whether caller-provided cwd is required, optional, or ignored.
- `env`: explicit environment additions.
- `stop_policy`: process-group termination behavior.
- `health_command`: optional command for quick availability checks.

Example:

```toml
[[agents]]
id = "openclaw"
label = "OpenClaw"
command = ["openclaw", "agent", "--message", "{{message}}", "--json"]
cwd_mode = "required"
stop_policy = "process_group"

[[agents]]
id = "hermes"
label = "Hermes"
command = ["hermes", "chat", "--query", "{{message}}", "--quiet", "--source", "agentic-os"]
cwd_mode = "optional"
stop_policy = "process_group"
```

P0 must not hardcode every harness behavior into the CLI. Harness-specific
launch quirks can exist in profiles later, but the first registry should be
data-driven enough to add a basic command runner without changing code.

## Harness Run Lifecycle

Harness Session states:

- `queued`: accepted by daemon, not started.
- `running`: process started and pid/process group recorded.
- `stopping`: stop requested.
- `succeeded`: process exited with code `0`.
- `failed`: process exited with non-zero code or launch error.
- `stopped`: terminated by user request.

Minimal Harness Session metadata:

```text
session_id
agent_id
cwd
argv
status
pid
pgid
exit_code
started_at
ended_at
last_updated_at
artifact_dir
stdout_log
stderr_log
summary_one_liner
```

`summary_one_liner` is optional in P0. If no summarizer exists, it stays empty. Do not add a large session-state blob.

## Process Control

`agentd` owns process launch and supervision for harness runs. The UI or CLI
never directly spawns long-running harness processes.

Rules:

- Start each run in a new process group.
- Record `pid` and `pgid` before returning success.
- Stream stdout and stderr to separate JSONL logs.
- Keep raw process output; parsing is optional and additive.
- Stop sends `SIGTERM` to the process group.
- If still running after timeout, send `SIGKILL`.
- A daemon restart must reconcile sessions by checking recorded pids.

P0 does not need distributed scheduling. SQLite plus local process inspection is enough.

## Log Storage

Logs are append-only JSONL. Do not keep complete logs in React state later.

Stdout line example:

```json
{"ts":"2026-05-27T10:00:00+08:00","stream":"stdout","session_id":"s_abc123","line":"..."}
```

Stderr line example:

```json
{"ts":"2026-05-27T10:00:01+08:00","stream":"stderr","session_id":"s_abc123","line":"..."}
```

CLI behavior:

- `agentctl logs <session_id>` prints merged chronological logs.
- `agentctl logs <session_id> --stream stdout` prints only stdout.
- `agentctl logs <session_id> --follow` tails new log entries.

## Artifact Folder

Each session gets:

```text
.agentic-os/sessions/<session_id>/
├── session.json
├── stdout.jsonl
├── stderr.jsonl
└── artifacts/
```

Artifact capture is passive in P0. The daemon creates the folder and records the
path; harness-specific artifact discovery can come later.

## SQLite Metadata

P0 tables:

```sql
agents(id, label, enabled, command_json, cwd_mode, env_json, stop_policy, created_at, updated_at)
sessions(id, agent_id, cwd, argv_json, status, pid, pgid, exit_code, artifact_dir, stdout_log, stderr_log, summary_one_liner, started_at, ended_at, updated_at)
events(id, session_id, event_type, message, metadata_json, created_at)
```

The JSONL logs remain the source of truth for process output. SQLite stores pointers and queryable state.

## CLI Commands

Required P0 commands:

```bash
agentctl agents list
agentctl agents show <agent_id>
agentctl run <agent_id> --cwd <path> --message <text>
agentctl sessions list
agentctl sessions show <session_id>
agentctl logs <session_id>
agentctl logs <session_id> --follow
agentctl stop <session_id>
agentctl retry <session_id>
```

Acceptance examples:

```bash
agentctl agents list
agentctl run openclaw --cwd ~/Projects/demo --message "只輸出 OK"
agentctl sessions list
agentctl logs <session_id>
agentctl stop <session_id>
```

## Failure Handling

Launch failure:

- session becomes `failed`;
- stderr records the launch error;
- `events` records `launch_failed`.

Agent command exits non-zero:

- session becomes `failed`;
- exit code is stored;
- logs remain readable.

Stop timeout:

- daemon escalates from `SIGTERM` to `SIGKILL`;
- session becomes `stopped`;
- `events` records escalation.

Daemon restart:

- daemon scans `running` sessions;
- if pid/pgid is gone, mark session `failed` with `daemon_reconciled_missing_process`;
- if still alive, keep `running` and reconnect log tailing only when possible.

Invalid cwd:

- reject before process launch;
- no process is spawned;
- session can be omitted or recorded as `failed` depending on API implementation, but the CLI must show a clear error.

## P0 Verification

The first implementation is not complete until these pass:

- Unit tests for registry loading and session state transitions.
- Unit tests for command template rendering.
- Unit tests for log append/read/follow behavior.
- Integration test running a harmless local command through `agentd`.
- Manual smoke with one real agent command, preferably OpenClaw or Hermes.

## Future Phases

P1 adds run-to-memory pipeline:

```text
raw logs/transcript -> session summary -> review queue -> approved memory -> searchable KB
```

P2 adds thin UI over the daemon.

P3 adds the Shared Capability Catalog, Harness Launch Policy, model allowlist,
approval rules, data scope, rate limits, and readonly mode.

P4 should add Harness Instance Profile documents for management metadata only.
Profiles may describe `id/name`, `config_path`, `workspace_roots`,
`launch_command`, `health_command`, `attach_command`, `log_paths`, and
`default_provider`; they must not describe planner, executor, tool loop, browser
driver, memory reasoning, or task decomposition behavior.
