# 043 — Approval Workbench (P24)

Status: Complete
Date: 2026-06-07
Depends on: human approval workflow (`specs/009-human-approval-workflow.md`), approval queue (`specs/015-approval-queue.md`, `specs/016-approval-queue.md`), remote approval loop (`specs/032-remote-approval-loop.md`)
Blocks: —

## Positioning

Approvals today are a list with approve/reject buttons. P24 turns it into a **review
workbench**: each request shows enough context to make a decision without leaving the page.

## Scope

| Owns | Does not own |
|------|--------------|
| Per-request: trigger reason, source session, argv, cwd, policy decision/reason | Approval state machine (009) |
| approve / reject / **retry** with audit links (`agentctl sessions events <id>`) | RBAC, notifications |
| Remote-mode parity via gateway approval stream (032) | In-harness live tool approval |

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Workbench renders trigger reason + source session + argv + cwd + policy result | `tests/test_web.py` |
| approve/reject/retry call the gated endpoints | `tests/test_api.py` |
| Audit link resolves to the session event trail | manual |
| Works in remote mode over the gateway stream | manual remote |

## Conflicts & resolutions

- **Retry bypassing the policy gate** — P3.6 closed the retry bypass; a workbench retry must not
  reopen it. **→ Resolution**: the retry button calls `POST /sessions/{id}/retry` (which
  re-evaluates policy) and renders the returned `decision`/`reason`/`session_id` inline. No other
  respawn path is exposed in the workbench.
- **argv/cwd redaction** — argv may contain secrets. **→ Resolution**: display the redacted argv
  from the approval/audit record (already passed through `_redact_value` in audit metadata); the
  workbench never reconstructs raw argv.
- **Remote parity** — **→ Resolution**: approve/reject/retry go through the gateway and are subject
  to the `034` HTTPS transport policy and the P14 token lifecycle; the workbench consumes the `032`
  approval event stream for live updates.
