# Reference remote gateway (P12)

Transport-agnostic reverse tunnel / HTTPS proxy. The **gateway is not an auth
boundary by itself** — it must strip client-supplied trust headers and agentd
enforces Bearer tokens on all gateway-marked API traffic.

## Requirements

1. External clients reach **`remote_gateway`** over HTTPS. Desktop and iOS clients
   (P15) reject cleartext `http://` to non-loopback hosts before sending Bearer tokens.
2. Gateway forwards to **`http://127.0.0.1:8767`** (agentd stays on loopback).
3. Gateway **strips** inbound `X-Agentic-OS-Gateway` and **sets** `X-Agentic-OS-Gateway: 1`
   on upstream requests it forwards (never accept client-spoofed values).
4. Gateway **blocks** `/remote/pairing/start`, `/remote/devices`, and device revoke paths.
5. Pass through **`Authorization: Bearer`** unchanged.
6. agentd middleware requires valid Bearer for all other gateway-proxied routes.
7. `/remote/pairing/complete` is the only pairing route exposed via gateway; pairing codes
   are high-entropy with rate limiting on failed attempts.
8. For SSE (`GET /events`), disable response buffering (`flush_interval -1` in Caddy).

## Local smoke with bundled Caddyfile

```bash
uv run agentd serve
caddy run --config examples/remote-gateway/Caddyfile
```

Pair locally (operator only), complete via gateway, then:

```bash
bash scripts/smoke-remote-client.sh https://127.0.0.1:8443 "$TOKEN"
```

## agentd bind rule

`agentd serve --host` must stay on loopback (`127.0.0.1`). Non-loopback bind fails unless
`AGENTIC_OS_ALLOW_PUBLIC_BIND=1` (tests/dev only).
