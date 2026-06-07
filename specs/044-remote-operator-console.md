# 044 — Remote Operator Console (P25)

Status: Complete
Date: 2026-06-07
Depends on: remote access adapter (`specs/030-remote-access-adapter.md`), remote approval loop (`specs/032-remote-approval-loop.md`), remote token lifecycle (`specs/033-remote-token-lifecycle.md`), HTTPS hardening (`specs/034-remote-https-hardening.md`)
Blocks: —

## Positioning

In remote mode the Web UI must show a **remote-safe** surface: gateway status, token
status, the approval event stream, and only the actions that are valid remotely. It must
**hide localhost-only admin actions** rather than offer them and fail with 403.

## Scope

| Owns | Does not own |
|------|--------------|
| Display: gateway reachability, token status (P14 `expires_at`), approval stream (032) | Server-side gateway/agentd behavior (frozen) |
| Enumerate + gate remote-safe vs localhost-only actions in the UI | Certificate pinning / mTLS |
| Apply HTTPS/loopback transport policy (034) on every remote call | Token issuance internals |

## Localhost-only actions to hide in remote mode

From `remote_api.py` / `remote_gateway.require_localhost_operator`: device pairing
complete, token **rotate**, and any `remote_admin_localhost_only` route.

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Remote mode hides localhost-only admin actions | `tests/test_web.py` + `tests/test_remote_access.py` |
| Token status shown without leaking token value | redaction assertion |
| Approval stream renders live over the gateway | manual remote |
| All remote calls obey HTTPS/loopback policy (034) | manual |

## Conflicts & resolutions

- **Gating source of truth drifts** — a hardcoded JS list of localhost-only actions will fall out of
  sync with the backend guards. **→ Resolution**: add a minimal `GET /remote/affordances` returning
  `{localhost_only: [action_ids]}` derived from the **same constant** that `require_localhost_operator`
  enforces (extract that set into one shared module so route guard and affordance list cannot
  diverge). The UI gates purely from this response.
- **Token leakage** — **→ Resolution**: render status + `expires_at` only; the token value is never
  sent to the client (already true) and the console must not request it.
- **Transport** — **→ Resolution**: every remote action routes through the `034` gate (HTTPS or
  loopback-http only); no cleartext Bearer to a non-loopback host.
