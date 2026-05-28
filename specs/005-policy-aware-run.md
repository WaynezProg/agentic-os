# 005 — Harness Launch Policy-Aware Run (P3.5 Hardening)

> Before any Harness Run starts, agentic-os evaluates declarative Harness Launch
> Policy and records allow / deny / approval_required decisions as run or audit
> events.

## Motivation

P3 delivered a policy evaluation engine (`POST /policy/evaluate`), a Shared
Capability Catalog, and per-harness launch policies. But the engine is not wired
into the Harness Run creation path: `POST /sessions` calls
`registry.build_run()` then `supervisor.start()` with no policy check in between.
This means a deny policy can be queried but never enforced at launch time.

Existing route and field names still use `sessions` and `agent_id`; those are
compatibility labels for Harness Sessions and Harness Instance Registry ids.

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P3.5 | launch policy gate on run creation | Harness Launch Policy applied before spawning a run | allow / deny / approval-required audit trail | per-tool runtime enforcement |

## Scope

Three changes, all additive:

### 1. Harness Launch Policy gate on `POST /sessions`

After `registry.build_run()` succeeds, the API handler evaluates the harness
instance's launch policy with `cwd` from the rendered run. The evaluation
request uses only the fields available at run-start time (`agent_id`, `cwd`);
per-tool and per-model checks remain outside this Harness Manager layer.

| Decision            | HTTP response | Behaviour                                     |
|---------------------|---------------|-----------------------------------------------|
| `allow`             | 200           | Proceed to `supervisor.start()` as before.    |
| `deny`              | 403           | Record `policy_denied` event, return error.   |
| `approval_required` | 409           | Record `policy_approval_required` event, return error. |
| No policy configured| 200           | Allow by default (open-by-default principle).  |

The `policy_denied` and `policy_approval_required` events are recorded against a
"shadow" Harness Session that is created in `queued` status and immediately
marked `failed`, so the attempt is auditable.

Run-level approval uses the reserved policy tool name `session.start`. If
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

- Live per-tool / per-model enforcement inside an underlying harness.
- P3.7 is Harness Instance Profile schema; P4 is Fleet Control Plane Goals
  (see `specs/008-harness-fleet-control-plane-goals.md`).
- Pending / approval workflow with human-in-the-loop (future).
- LLM summary, vector DB, Electron, Tauri.
