# iOS Remote Companion (P12.5c)

Minimal SwiftUI client for the Remote Access Adapter. All traffic goes to
`remote_gateway` with `Authorization: Bearer` — never to the Mac LAN IP.

Clients must **not** send `X-Agentic-OS-Gateway`. That header is a gateway →
agentd trust marker: the reference gateway strips inbound values and sets
`X-Agentic-OS-Gateway: 1` on upstream requests.

## Pairing flow

1. Desktop (localhost operator): **Start pairing** → high-entropy `pairing_code`
   (`secrets.token_urlsafe(16)` from agentd).
2. iOS: POST `{remote_gateway}/remote/pairing/complete` with JSON body only
   (gateway adds trust header upstream):

```json
{"pairing_code": "<code from desktop>", "device_name": "wayne-iphone"}
```

3. Store returned `auth_token` in iOS Keychain (service `agentic-os`, account
   `{remote_gateway}:{device_id}`). Revoke on desktop invalidates the token.

## API surface

| Call | Client auth |
|------|-------------|
| `GET {gateway}/health` | optional Bearer |
| `GET {gateway}/events` | Bearer required |
| `POST {gateway}/remote/pairing/complete` | JSON body only; gateway sets trust header |

## Open in Xcode

1. File → New → Project → iOS App (SwiftUI, Swift).
2. Copy `RemoteCompanion/*.swift` into the app target (replace default files).
3. Set minimum iOS 17.
4. Run on simulator or device against a configured `remote_gateway`.

CLI smoke without Xcode:

```bash
bash scripts/smoke-remote-client.sh https://127.0.0.1:8443 "$TOKEN"
```

## Status states

| UI state | Meaning |
|----------|---------|
| `connected` | `/health` OK and `/events` returned SSE preamble |
| `unauthorized` / `revoked` | Bearer rejected (revoked device) |
| `disconnected` | No Keychain token |
| `error` | Network or gateway misconfiguration |
