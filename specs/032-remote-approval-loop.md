# 032 — Remote Approval Loop (P13)

Status: Implemented
Date: 2026-06-07
Depends on: P7 (`specs/016-approval-queue.md`), P12 (`specs/030-remote-access-adapter.md`)
Blocks: —

## Positioning

P7 shipped the approval request lifecycle (`approval_requested → approved | rejected |
expired`) with localhost API/CLI/UI. P12 shipped the Remote Access Adapter: a paired
device reaches `agentd` through the reference gateway with a Bearer token, and the
remote `/events` SSE stream pushes `config_patch` audit events.

The gap: the remote event stream is hardcoded to `domain="config_patch"`, so a paired
operator **never sees pending approvals** and gets no signal that a harness launch is
waiting. Meanwhile the approve/reject routes (`/approvals*`) are already reachable
through the gateway with a valid Bearer token — but that behavior is **implicit and
untested**, so it can regress silently.

P13 closes the loop: surface approval lifecycle events on the remote stream, and make
the remote approve/reject contract **explicit and test-covered**. This is the
"approve a harness launch from your phone" use case the P12 stack was built for.

## Security posture (conscious decision)

A paired device holding a valid Bearer token **may list and resolve approvals**
(`GET /approvals`, `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject`).
This is the intended feature, not an accident: approving a launch remotely is the
point of the mobile companion. Mitigations stay as in P12 — tokens are revocable,
`agentd` is loopback-only, and the gateway is the only public ingress.

Device-lifecycle admin routes (`/remote/pairing/start`, `/remote/devices`,
`/remote/devices/*`) remain **localhost-only** and are rejected when presented through
the gateway. P13 does not widen the admin boundary.

| Owns | Does not own |
|------|--------------|
| Approval lifecycle events on the remote `/events` stream | New approval state machine (P7 owns it) |
| Explicit, tested remote approve/reject via gateway + Bearer | RBAC, per-action re-authentication, push notifications |
| Stream-selection contract (which audit events reach remote) | iOS UI polish, APNs delivery (P14+) |
| Backward-compatible `config_patch` streaming | Cloud sync, multi-user roles |

## Contract

Remote `/events` stream emits, ordered by audit `id`:

- all `config_patch` domain events (unchanged from P12), and
- `governance` domain events whose `event_type` is one of:
  `approval_requested`, `approval_approved`, `approval_rejected`,
  `approval_expired`, `run_started_after_approval`.

Other `governance` events (e.g. `policy_evaluated`) are **not** streamed remotely.
Each streamed payload keeps the P12 shape plus `remote_device_id`.

Remote approve/reject reuse the existing P7 routes; no new endpoints. Auth is the P12
gateway Bearer boundary (a valid, non-revoked token is required; admin routes blocked).

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Stream selection returns `config_patch` + allowlisted `governance` approval events | `tests/test_remote_approval_loop.py` (store method) |
| Stream selection excludes non-allowlisted `governance` events (`policy_evaluated`) | same |
| Gateway + Bearer client can `GET /approvals` | `tests/test_remote_approval_loop.py` |
| Gateway + Bearer client can resolve an approval (`reject` → 200, status `rejected`) | same |
| Gateway request without Bearer is rejected (401) on `/approvals` | same |
| Admin device routes still blocked through gateway (403) | `tests/test_remote_access.py` (P12, unchanged) |

## P12 boundary (frozen)

Pairing API, gateway middleware, reference Caddyfile, loopback-only `agentd`, and the
P7 approval state machine are **frozen**. P13 adds stream selection + contract tests
only — no new daemon endpoints, no state-machine changes.
