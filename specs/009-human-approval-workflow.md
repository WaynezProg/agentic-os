# 009 -- Human Approval Workflow (P7)

Status: Planned
Date: 2026-05-29

## Positioning

P7 turns the existing `approval_required` launch-policy decision into a durable
operator workflow. P3.5/P3.6 already prevent the run from spawning and return a
shadow session id. P7 keeps that safety property, stores a pending approval
request, and lets the single local operator approve or reject it later.

This is still a local single-user Harness Manager feature. It is not RBAC, not a
remote approval system, and not live in-harness tool approval.

## Goals

1. **Durable approval requests** -- every launch or retry that returns
   `approval_required` creates an approval record with the blocked shadow
   session id, agent id, cwd, argv, reason, and status.

2. **Explicit operator decision** -- the operator can list, inspect, approve,
   and reject pending approvals through API, CLI, and the static UI.

3. **No automatic spawn before approval** -- the original request never starts a
   harness process. Approval starts a new Harness Run from the stored request
   payload and links it back to the approval id and original shadow session.

4. **Auditable lifecycle** -- approval requested, approved, rejected, and
   started-after-approval events are written to the governance audit trail.

5. **Retry parity** -- `POST /sessions/{id}/retry` and `POST /sessions` use the
   same approval request path when policy requires approval.

## Approval States

| State | Meaning | Terminal |
|-------|---------|----------|
| `pending` | Waiting for operator decision | no |
| `approved` | Operator approved and a new session was started | yes |
| `rejected` | Operator rejected; no process was started | yes |
| `expired` | Request is no longer actionable because its source session or policy context changed | yes |

P7 does not need a background expiry worker. Expiry is checked opportunistically
when an approval is read or acted on.

## API Contract

New routes:

- `GET /approvals` -- list approval requests, defaulting to pending-first order.
- `GET /approvals/{approval_id}` -- show one approval request.
- `POST /approvals/{approval_id}/approve` -- atomically marks approved and
  starts a new Harness Run from stored argv/env/cwd.
- `POST /approvals/{approval_id}/reject` -- marks rejected with optional reason.

Existing run routes change only when policy returns `approval_required`:

- `POST /sessions` returns HTTP 409 with `{decision, session_id, approval_id}`.
- `POST /sessions/{id}/retry` returns the same shape.

## Data Model

New SQLite table:

```sql
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  source_session_id TEXT NOT NULL,
  approved_session_id TEXT,
  agent_id TEXT NOT NULL,
  cwd TEXT NOT NULL,
  argv_json TEXT NOT NULL,
  env_json TEXT NOT NULL DEFAULT '{}',
  reason TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
  decision_reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

The table stores rendered argv/env because the operator approves the exact
request that was blocked. Policy is still re-evaluated at approval time; if the
policy no longer allows approval, the approval becomes `expired`.

## CLI and UI

CLI:

```bash
agentctl approvals list
agentctl approvals show <approval_id>
agentctl approvals approve <approval_id>
agentctl approvals reject <approval_id> --reason "not needed"
```

UI:

- Add an Approvals section to the existing Skills / MCP or Fleet surface.
- Show pending approvals with agent, cwd, reason, source session, age, and
  approve/reject buttons.
- Do not add chat, notifications, multi-user review queues, or remote delivery.

## Governance

P7 extends P6 governance:

- `approval_requested` links `approval_id` and `source_session_id`.
- `approval_approved` links `approval_id`, `source_session_id`, and
  `approved_session_id`.
- `approval_rejected` links `approval_id` and `source_session_id`.
- `run_started_after_approval` links `approval_id` and `approved_session_id`.

`GET /audit/policy-coverage` must treat a source shadow session with a matching
`policy_evaluated` event as covered. Approved follow-up sessions also get their
own policy evaluation event.

## Non-Goals

- No multi-user approvers, roles, signatures, or tenant separation.
- No notification system, email, Discord, Slack, or browser push.
- No live per-tool approval inside OpenClaw, Hermes, Codex, Claude Code, Gemini
  CLI, or OpenCode.
- No scheduler or background worker.
