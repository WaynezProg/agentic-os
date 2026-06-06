# 031 — Keychain Token Storage + iOS Companion (P12.5)

Status: Implemented
Date: 2026-06-07
Depends on: P12 (`specs/030-remote-access-adapter.md`)
Blocks: —

## Sub-phases

| Slice | Scope | Status |
|-------|-------|--------|
| P12.5a | macOS Keychain token vault; pairing complete → Keychain; revoke → delete; `desktop.toml` audit | Done |
| P12.5b | `connection.mode=remote` reconnect via `remote_gateway` + Bearer (`/health`, `/events`) | Done |
| P12.5c | iOS skeleton + README fix + iOS Keychain | Done |

Keychain account: service `agentic-os`, account `{remote_gateway}:{device_id}`.

Desktop webview must not invoke raw token read/write commands. Tauri exposes
only `remote_token_status` (bool), `connection_api_fetch`, `probe_remote_connection`,
`complete_remote_pairing`, and `revoke_remote_device`.

## Positioning

P12 shipped pairing, gateway Bearer boundary, and desktop remote settings placeholders.
P12.5 closes the **token persistence gap**: `auth_token` must not live in desktop UI
placeholders or plain `desktop.toml`; macOS Keychain owns runtime secrets. iOS gets a
minimal companion skeleton wired to the existing pairing + SSE contract — not a full App
Store product.

| Owns | Does not own |
|------|--------------|
| macOS Keychain read/write for `auth_token` after pairing | App Store release, push notifications |
| Remove desktop placeholder token flow | New daemon API surface beyond P12 contract |
| iOS companion skeleton (pairing complete, Bearer API, SSE consumer) | Bundling a specific tunnel product |
| `desktop.toml` stays: `remote_gateway`, `tunnel_provider`, `device_id` only | Cloud sync, multi-user RBAC |

## Acceptance criteria (draft)

| Criterion | Verification |
|-----------|--------------|
| Paired token persisted in Keychain, not `desktop.toml` | Settings file audit + manual smoke |
| Desktop reconnect uses Keychain token for gateway API | Manual remote mode smoke |
| iOS skeleton completes pairing via gateway and calls `/health` + `/events` | Device/simulator smoke |
| Revoke on desktop invalidates iOS token | Manual revoke smoke |

## P12 boundary (already shipped)

Pairing API, gateway middleware, reference Caddyfile, and loopback-only `agentd` are
**frozen** in P12. P12.5 adds persistence and client skeleton only.
