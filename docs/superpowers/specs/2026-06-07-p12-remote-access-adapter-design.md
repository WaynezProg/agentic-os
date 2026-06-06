# P12 — Remote Access Adapter Design

Date: 2026-06-07
Status: Approved for planning
Author: agentic-os team
Builds on: P11.5 (`specs/029-packaged-macos-app.md`)
Blocks: —

## Summary

Add **remote access** to local `agentd` through a pluggable **Remote Access Adapter**.
External clients (iOS companion first) reach the daemon via a **remote gateway** /
**reverse tunnel** — never by exposing `agentd` directly.

The adapter contract is **transport-agnostic**: frp, Tailscale, Cloudflare Tunnel, ngrok,
and self-hosted reverse proxies are implementation options, not phase requirements.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Daemon bind | `127.0.0.1` only; remote never widens bind address |
| External entry | Remote gateway / reverse tunnel with auth + pairing + revoke |
| Adapter inputs | `gateway_url`, `auth_token`, `pairing_code`, `device_id` |
| Tunnel product | Not specified; operator chooses implementation |
| Daemon changes | Proxy-only; no new harness/agent features in P12 |
| Event stream | `GET /events` SSE proxied through gateway (same auth) |

## Architecture

```
iOS / remote client
        │  HTTPS + auth token
        ▼
Remote gateway / reverse tunnel   ← operator-provided (any product)
        │  localhost forward
        ▼
agentd @ 127.0.0.1:8767           ← unchanged bind; never exposed
```

## Remote Access Adapter contract

### Inputs

| Field | Description |
|-------|-------------|
| `gateway_url` | Public or tailnet HTTPS base URL for proxied API |
| `auth_token` | Secret presented on every remote request |
| `pairing_code` | Short-lived code shown on Mac for device binding |
| `device_id` | Stable ID assigned after pairing completes |

### Security invariants

1. **Loopback only** — `agentd` does not listen on LAN or WAN interfaces.
2. **Gateway mandatory** — no direct remote URL to daemon port.
3. **Auth on every request** — gateway rejects missing/invalid tokens.
4. **Pairing gate** — new devices require successful pairing before API access.
5. **Revoke** — operator can drop a device/token without reinstalling the app.

### Gateway responsibilities

- TLS termination (or trust upstream TLS, e.g. Cloudflare edge).
- Token validation (Bearer or HMAC — exact scheme in implementation plan).
- Reverse proxy to `http://127.0.0.1:8767` (and UI port if needed).
- Optional pairing API endpoint (may live on gateway or separate helper service).
- Pass through SSE for `GET /events` without buffering violations.

### Explicit non-goals

- Shipping or endorsing a specific tunnel binary
- Hosted multi-tenant relay SaaS
- Cloud sync of daemon state
- RBAC beyond single-operator token + device list
- Changing harness runtime or adding agent features

## Desktop + iOS surfaces

### `desktop.toml` `[remote]`

Reserved in P11; wired in P12:

```toml
[remote]
enabled = false
gateway_url = ""
# token stored via keychain / secure store, not plain text in file
pairing_code = ""   # ephemeral, display-only during pairing window
device_id = ""      # this Mac's gateway identity if applicable
connection_mode = "local"  # "local" | "remote"
event_stream_url = ""      # derived from gateway_url + /events
```

### iOS companion

- Pairing UX: enter or scan pairing code → receive token + device_id.
- All API calls target `gateway_url`, not Mac IP.
- SSE client for session/config events.

## P11 / P11.5 boundary (already shipped)

P11/P11.5 own local shell + `desktop.toml` placeholders only.
P12 adds connection logic, gateway helper docs, and iOS client — not daemon bind changes.

## Risks

| Risk | Mitigation |
|------|------------|
| Operator picks insecure tunnel (no TLS) | Document minimum: HTTPS + token required |
| SSE over reverse proxy buffering | Gateway config docs; nginx `proxy_buffering off` etc. |
| Token in plain `desktop.toml` | Keychain/secure store in Tauri; spec forbids committed secrets |
| Confusion with Harness Adapter Contract (024) | Product language: "Remote Access Adapter" vs "Harness Adapter Contract" |

## References

- Phase spec: `specs/030-remote-access-adapter.md`
- P11 design: `docs/superpowers/specs/2026-06-07-p11-desktop-app-shell-design.md`
- P11.5 design: `docs/superpowers/specs/2026-06-07-p11.5-packaged-macos-app-design.md`
