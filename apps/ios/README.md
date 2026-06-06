# iOS Remote Companion (P12 MVP)

SwiftUI client scaffold for the Remote Access Adapter. All traffic goes to `gateway_url`
with `Authorization: Bearer` — never to the Mac LAN IP.

## Pairing flow

1. Desktop: **Start pairing** → 6-digit code.
2. iOS: POST `{gateway_url}/remote/pairing/complete` with header `X-Agentic-OS-Gateway: 1`
   (set by reference Caddy/nginx config) and body:

```json
{"pairing_code": "123456", "device_name": "wayne-iphone"}
```

3. Store returned `auth_token` in Keychain; use `device_id` for display/revoke on desktop.

## API surface

| Call | Auth |
|------|------|
| `GET {gateway}/health` | optional |
| `GET {gateway}/events` | Bearer required |
| `POST {gateway}/remote/pairing/complete` | gateway header |

Full implementation tracked in-repo after P12 merge gate; until then use
`scripts/smoke-remote-client.sh` for contract verification.
