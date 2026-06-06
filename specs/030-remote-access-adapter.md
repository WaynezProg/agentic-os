# 030 — Remote Access Adapter (P12)

Status: Implemented
Date: 2026-06-07
Depends on: P11.5 (`specs/029-packaged-macos-app.md`)
Blocks: P12.5 (`specs/031-keychain-ios-companion.md`)

## Positioning

P12 adds **remote access** to a local `agentd` via a pluggable **Remote Access Adapter**.
The adapter sits between external clients (iOS companion, future surfaces) and the daemon;
it does **not** change harness runtime, SQLite ownership, or config write semantics.

| Owns | Does not own |
|------|--------------|
| Remote Access Adapter contract (inputs, auth, pairing, revoke) | Harness runtime, agent loop, MCP lifecycle |
| Remote gateway / reverse tunnel wire-up in desktop + iOS | Choosing or shipping a specific tunnel product |
| `desktop.toml` `[remote]` connection logic | Cloud sync, multi-user RBAC, hosted relay SaaS |
| Pairing flow, token storage/use, device revoke | Exposing `agentd` on non-loopback interfaces |
| Event stream client (SSE/WebSocket) over remote gateway | New daemon features beyond proxied existing APIs |

## Remote Access Adapter contract

The adapter is **transport-agnostic**. Implementation may use any reverse tunnel or remote
gateway — frp, Tailscale, Cloudflare Tunnel, ngrok, or a self-hosted reverse proxy — but
the phase spec and product language refer only to **remote gateway** and **reverse tunnel**.

### Inputs

| Field | Role |
|-------|------|
| `remote_gateway` | External HTTPS entry for proxied daemon API + event stream |
| `tunnel_provider` | Operator label for reverse tunnel product (informational; not enforced) |
| `auth_token` | Bearer secret (runtime only; not persisted in `desktop.toml` until P12.5 Keychain) |
| `pairing_code` | One-time or short-lived code to bind a new client device (ephemeral; not persisted) |
| `device_id` | Stable client identifier after successful pairing |

### Security invariants (non-negotiable)

1. **`agentd` binds `127.0.0.1` only** — never `0.0.0.0` or a public interface.
2. **No naked exposure** — all remote traffic enters through the gateway/reverse tunnel.
3. **Auth required** — every proxied request carries valid token credentials.
4. **Pairing required** — new devices must complete pairing before full API access.
5. **Revoke supported** — operator can invalidate a `device_id` / token without reinstall.

### Adapter responsibilities

- Terminate TLS and auth at the **remote gateway** layer.
- Proxy existing daemon HTTP routes (sessions, config patch, health, etc.).
- Proxy `GET /events` (SSE) or equivalent event stream to remote clients.
- Map gateway auth headers → audit `source` (e.g. `ios`) on proxied writes.

### Explicit non-binding

P12 does **not** standardize, vend, or require:

- frp, Tailscale, Cloudflare Tunnel, ngrok, or any named tunnel product
- A specific relay topology (self-hosted vs managed)

Reference implementations may document one tunnel setup in README/examples; the contract
remains product-neutral.

## Components

- **Desktop (Tauri)** — `[remote]` in `desktop.toml`: `remote_gateway`, `tunnel_provider`, `device_id` only; connection mode local vs remote.
- **iOS companion** — HTTP client against `remote_gateway`; pairing UX; SSE consumer.
- **Remote gateway** — reverse tunnel + auth middleware (operator-provided or bundled helper
  script outside core daemon scope).

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| `agentd` listens on `127.0.0.1` only with remote enabled | `lsof` / bind audit |
| Remote client reaches daemon only via `remote_gateway` | Integration smoke through tunnel fixture |
| Unauthenticated requests rejected at gateway | Negative test |
| Pairing flow binds `device_id` and issues token | Manual or integration test |
| Revoke invalidates device without daemon restart | Manual smoke |
| Event stream works over remote gateway | SSE client smoke |
| Local desktop mode unchanged when `[remote]` disabled | P11 regression |

## P11 / P11.5 touchpoints (already reserved)

- `remote.remote_gateway`, `remote.tunnel_provider`, `remote.device_id` in `desktop.toml`
- Event stream derived as `{remote_gateway}/events`, proxied by gateway
- Connection mode switch: local API vs remote gateway

## Design

`docs/superpowers/specs/2026-06-07-p12-remote-access-adapter-design.md`

## Implementation plan

`docs/superpowers/plans/2026-06-07-p12-remote-access-adapter.md`
