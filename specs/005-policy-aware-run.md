# 005 — Policy-Aware Run (P3.5 Hardening)

> Before any session starts, agentic-os evaluates declarative policy and records
> allow / deny / approval_required decisions as session or audit events.

## Motivation

P3 delivered a policy evaluation engine (`POST /policy/evaluate`) and a registry
of skills, MCP servers, and per-agent policies.  But the engine is not wired into
the session creation path — `POST /sessions` calls `registry.build_run()` then
`supervisor.start()` with no policy check in between.  This means a deny policy
can be queried but never enforced.

## Scope

Three changes, all additive:

### 1. Policy gate on `POST /sessions`

After `registry.build_run()` succeeds, the API handler evaluates the agent's
policy with `cwd` from the rendered run.  The evaluation request uses only the
fields available at session-start time (`agent_id`, `cwd`); per-tool and per-model
checks remain a future runtime concern.

| Decision            | HTTP response | Behaviour                                     |
|---------------------|---------------|-----------------------------------------------|
| `allow`             | 200           | Proceed to `supervisor.start()` as before.    |
| `deny`              | 403           | Record `policy_denied` event, return error.   |
| `approval_required` | 409           | Record `policy_approval_required` event, return error. |
| No policy configured| 200           | Allow by default (open-by-default principle).  |

The `policy_denied` and `policy_approval_required` events are recorded against a
"shadow" session that is created in `queued` status and immediately marked
`failed`, so the attempt is auditable.

Run-level approval uses the reserved policy tool name `session.start`.  If
`approval_required_tool_names` contains `session.start` or `*`, a session start
that otherwise passes the cwd policy returns `approval_required`.

### 2. Session events API

Expose `GET /sessions/{id}/events` returning the existing `store.list_events()`
data.  Add matching client method and CLI command (`agentctl sessions events`).

### 3. UI: Run Session form + Events display

- Agents tab: each agent row gets a **Run** button.  Clicking it shows a minimal
  form (agent pre-filled, cwd input, message textarea, submit).
- The form POSTs to `/sessions`.  On 403/409 the UI shows the policy denial
  reason inline.
- Logs tab: below the session detail `<dl>`, render a collapsible "Events" list
  fetched from `GET /sessions/{id}/events`.

## Out of scope

- Per-tool / per-model runtime enforcement (future P4).
- Pending / approval workflow with human-in-the-loop (future).
- LLM summary, vector DB, Electron, Tauri.
