# 004 Shared Capability Catalog And Harness Launch Policy

Status: Draft
Date: 2026-05-28

## Positioning

P3 turns the P2 placeholder Skills / MCP interface into the Shared Capability
Catalog and Harness Launch Policy surface for registry and policy decisions.

It is still not an orchestrator, not a second OpenClaw, and not an agent
runtime. `agentd` may store catalog records and evaluate whether a requested
launch capability should be allowed, denied, or require approval, but it does
not execute catalog entries, start MCP servers, run tools, enforce harness
loops, summarize with an LLM, index repositories, or replace Hermes, OpenClaw,
Codex, Claude Code, Gemini CLI, or OpenCode.

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P3 | catalog/policy registries and evaluator | Shared Capability Catalog plus Harness Launch Policy | descriptive capability records, deterministic policy decisions | installing capabilities, starting MCP servers, live tool enforcement |

## Goals

- Store a durable local Shared Capability Catalog for skill-like and MCP-like
  capabilities.
- Store durable per-harness Harness Launch Policy.
- Expose deterministic policy evaluation through daemon API and `agentctl`.
- Let the thin UI display catalog entries, Harness Launch Policy summary, and
  evaluation results by calling daemon API only.
- Keep command and environment previews safe for local display.

## Non-Goals

- No second orchestrator or scheduler.
- No MCP server process ownership in the UI or daemon P3 policy layer.
- No external tool execution during policy evaluation.
- No Redis, external vector DB, embeddings, RAG, cloud sync, or LLM summarizer.
- No Electron, Tauri, React build pipeline, or browser-side subprocess work.
- No multi-user auth, RBAC, remote sync, or hosted control plane.
- No chat UI, Kanban, IDE, full repo indexing, or runtime hook into Hermes or
  OpenClaw internals.

## Shared Capability Catalog: Skill Records

The Shared Capability Catalog is a local catalog of capabilities known to
`agentic-os`. Skill-like records are descriptive and declarative. They do not
install a skill, invoke a skill, or copy files into an underlying harness.

Skill record:

```text
id
label
description
source
entrypoint
tags
enabled
created_at
updated_at
```

Rules:

- `id` is the stable path-safe identifier.
- `label` is display text.
- `description` is local documentation only.
- `source` identifies the local origin, for example `workspace` or `builtin`.
- `entrypoint` is a non-secret command or file hint. It is not executed.
- `tags` are exact-match labels for UI and CLI display.
- `enabled=false` keeps the record durable but policy evaluation denies it.

API contract:

```http
GET  /skills
GET  /skills/{skill_id}
POST /skills/{skill_id}
POST /skills/{skill_id}/disable
```

`POST /skills/{skill_id}` upserts a registry record. The request body may omit
optional fields; omitted values get deterministic defaults.

## Shared Capability Catalog: MCP Server Records

MCP server records are part of the Shared Capability Catalog. They store
display-safe metadata only. They do not start, stop, proxy, or supervise MCP
server processes.

MCP server record:

```text
id
label
description
transport
command_preview
url
env_keys
enabled
created_at
updated_at
```

Rules:

- `transport` is one of `stdio`, `http`, or `sse`.
- `command_preview` is a redacted, non-executable preview for humans.
- `url` is optional and may be stored only when it does not contain embedded
  credentials.
- `env_keys` stores environment variable names only, never values.
- `enabled=false` keeps the record durable but policy evaluation denies it.

API contract:

```http
GET  /mcp
GET  /mcp/{server_id}
POST /mcp/{server_id}
POST /mcp/{server_id}/disable
```

## Harness Launch Policy

Policy is per harness instance id and declarative. A missing policy denies by
default. Existing storage/API field names still use `agent_id`; that field maps
to the Harness Instance Registry id and does not mean ownership of harness
internals.

Policy record:

```text
agent_id
enabled
readonly
allowed_skill_ids
allowed_mcp_server_ids
allowed_tool_names
approval_required_tool_names
allowed_model_ids
cwd_roots
rate_limit_per_minute
created_at
updated_at
```

Rules:

- `enabled=false` denies every evaluation for the harness instance.
- Empty allowlists deny the corresponding requested capability.
- `*` means all currently enabled registry entries or all values for that
  field, depending on field type.
- `approval_required_tool_names` upgrades an otherwise allowed tool request to
  `approval_required`.
- `readonly=true` denies known write-capable tool names even if they appear in
  the allowlist.
- `cwd_roots` is data scope. When a cwd is supplied, it must be under one of
  the configured roots.
- `rate_limit_per_minute` is declarative in P3. The evaluator denies values
  less than `1`; it does not keep request counters.

API contract:

```http
GET  /policy
GET  /policy/{agent_id}
POST /policy/{agent_id}
POST /policy/evaluate
```

## Model Allowlist

Model selection is a policy input, not a runtime action. The evaluator checks
`model_id` against `allowed_model_ids` when a model is requested.

P3 does not call model providers, refresh catalogs, validate credentials, or
change any underlying harness model setting.

## Tool Approval Rules

Policy evaluation returns one of:

```text
allow
deny
approval_required
```

Decision precedence:

1. missing or disabled policy -> `deny`
2. disabled or unknown requested catalog record -> `deny`
3. allowlist mismatch -> `deny`
4. cwd outside data scope -> `deny`
5. readonly write-tool request -> `deny`
6. approval-required tool match -> `approval_required`
7. all requested checks pass -> `allow`

Evaluation is deterministic for the same stored registry/policy state and the
same request body.

## Data Scope

`cwd_roots` limits where an agent may operate. The evaluator normalizes paths
lexically with `expanduser` and `resolve(strict=False)`. It must not scan the
filesystem, index directories, read large logs, or check repository contents.

## Rate Limit

P3 stores `rate_limit_per_minute` as a declarative control-plane value. It is
shown in CLI/UI summaries and validated by the evaluator. P3 does not implement
runtime counters or throttling.

## Readonly Mode

Readonly mode is a deterministic policy rule. Known write-capable tool names
include:

```text
write
edit
apply_patch
exec
spawn
subprocess
mcp.write
browser.click
browser.type
```

Readonly mode denies those names before approval rules are considered.

## Failure Handling

- Unknown catalog/policy ids return `404` on read routes.
- Invalid request bodies return FastAPI validation errors.
- Unsafe ids are rejected by the CLI client before making an HTTP request.
- Disable routes are idempotent for existing records.
- Policy evaluation never executes external tools and never throws for a
  denied request; it returns a structured `deny` result with a reason.
- Existing P0/P1/P2 sessions, logs, memory, and UI contracts remain compatible.

## Secret Handling

Secrets must not be written to SQLite, logs, README, examples, or tests.

Rules:

- MCP env values are never accepted; only `env_keys` may be stored.
- Command previews are redacted before storage and display.
- URLs with embedded username/password are redacted before storage.
- Redaction covers common key names such as `token`, `secret`, `password`,
  `apikey`, `api_key`, and `authorization`.
- Redaction is best-effort display safety, not a secret manager.

## Verification

P3 is complete when:

- storage tests cover registry CRUD, disable behavior, redaction, and policy
  evaluation decisions;
- API tests cover catalog and policy read/upsert/disable/evaluate routes;
- CLI tests cover `skills`, `mcp`, and `policy` commands with concise list
  output;
- UI tests verify the Skills / MCP tab calls daemon APIs as the Shared
  Capability Catalog view and does not spawn
  processes;
- end-to-end tests still prove the P0/P1 daemon and CLI paths work;
- `rtk uv run pytest -q` passes;
- `rtk uv run ruff check .` passes.
