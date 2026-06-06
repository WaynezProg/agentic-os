# 034 — Remote HTTPS / Token Transport Hardening (P15)

Status: Implemented
Date: 2026-06-07
Depends on: P12 (`specs/030-remote-access-adapter.md`), P12.5 (`specs/031-keychain-ios-companion.md`)
Blocks: P16 (APNs push notifications)

## Positioning

Bearer tokens are in daily use on desktop and iOS remote clients. Sending a token
over cleartext `http://` to a non-loopback gateway is unacceptable — any network
observer can capture the credential.

P15 adds **client-side transport policy**: remote clients refuse to send Bearer
tokens (or complete pairing that stores a token) unless the gateway URL is HTTPS,
or `http://` targeting loopback only (local smoke against the reference Caddyfile).

Server-side gateway/agentd behavior is unchanged. This slice is client enforcement only.

## Contract

| Rule | Desktop (Rust) | iOS (Swift) |
|------|----------------|-------------|
| `https://*` | allowed | allowed |
| `http://127.0.0.1:*` | allowed | allowed |
| `http://localhost:*` | allowed | allowed |
| `http://[::1]:*` | allowed | allowed |
| `http://<non-loopback>` | **rejected** before any Bearer request or Keychain write | same |
| missing / empty gateway | rejected (unchanged) | unchanged |

Enforcement points (desktop):

- `remote::validate_remote_gateway` — shared gate
- `gateway_url` / `gateway_request_with_token` / `gateway_events_probe`
- `connection::connection_profile`, `probe_remote_connection`, `api_request` (remote mode)
- `complete_remote_pairing` before Keychain write

Enforcement points (iOS):

- `normalizedGatewayURL` before pairing, probe, or any `RemoteClient` call

## Security posture

| Owns | Does not own |
|------|--------------|
| Client-side HTTPS / loopback-http policy | Certificate pinning, mTLS |
| Reject cleartext Bearer to remote hosts | Server-side TLS termination choices |
| Documented rule in README + this spec | APNs push (P16) |

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| `http://evil.example` rejected on desktop before network | `cargo test` in `apps/desktop/src-tauri` |
| `https://evil.example` accepted (URL shape only) | same |
| `http://127.0.0.1:8443` accepted | same |
| iOS `normalizedGatewayURL` same rules | manual / unit test in Swift if added |
| P12–P14 remote tests unchanged | `uv run pytest tests/test_remote_access.py -q` |

## P12 boundary (frozen)

Pairing API, gateway middleware, reference Caddyfile, and loopback-only `agentd` are
**frozen**. P15 does not change server routes or gateway config.
