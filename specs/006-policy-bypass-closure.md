# 006 — Policy Bypass Closure (P3.6)

> A policy-denied Harness Session must not be retryable into a running process.
> Retry and all future Harness Run start paths must evaluate Harness Launch
> Policy before spawning.

## Motivation

P3.5 added a Harness Launch Policy gate on `POST /sessions`, but
`POST /sessions/{id}/retry` calls `supervisor.retry()` which calls
`supervisor.start()` directly, bypassing the policy check entirely. A denied
Harness Session (status=failed, pid=None) can be retried into a live process
even after the policy that denied it is still active.

Existing route and field names still use `sessions` and `agent_id`; those are
compatibility labels for Harness Sessions and Harness Instance Registry ids.

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P3.6 | retry bypass closure and clearer policy errors | all run-start paths share the same launch gate | retry policy audit, CLI/UI error display | approval workflow or harness-internal enforcement |

## Scope

### 1. Retry policy gate

`POST /sessions/{id}/retry` must evaluate Harness Launch Policy using the
previous Harness Session's `agent_id` and `cwd` before spawning. On deny -> 403
+ audit session + `policy_denied` event. On approval_required -> 409 + audit
session + `policy_approval_required` event. Same behaviour as the
`POST /sessions` gate.

### 2. CLI error display

When `agentctl run` or `agentctl retry` receives 403 or 409, the CLI currently
shows `HTTP 403: <reason>`.  It must also show `decision` and `session_id` so
the operator can inspect the audit trail.

### 3. UI error display

When the Run form or Retry button receives 403 or 409, the UI must show the
`decision`, `reason`, and `session_id` (as a clickable link to the Logs tab).

### 4. Spec / README update

- Rename `specs/005-policy-aware-run.md` to match the actual file on disk.
- Add P3.5 / P3.6 section to README under the existing phase documentation.

## Acceptance criteria

- denied Harness Session cannot be retried into a running process
- retry after policy tightening is denied
- approval_required retry returns 409 and records policy_approval_required
- CLI prints decision + session_id on 403/409
- UI run/retry error shows audit session_id
