# Reference remote gateway (P12)

This directory documents a **transport-agnostic** remote gateway setup. Use any reverse
tunnel or HTTPS proxy you prefer (Tailscale Serve, Cloudflare Tunnel, ngrok, Caddy, nginx).

## Requirements

1. External clients reach **`gateway_url`** over HTTPS.
2. Gateway forwards to **`http://127.0.0.1:8767`** (agentd stays on loopback).
3. Set header **`X-Agentic-OS-Gateway: 1`** on proxied `/remote/*` routes so pairing works
   through the tunnel (agentd rejects non-local pairing without this header).
4. Pass through **`Authorization: Bearer`** unchanged.
5. For SSE (`GET /events`), disable response buffering (`flush_interval -1` in Caddy).

## Local smoke with bundled Caddyfile

```bash
uv run agentd serve
caddy run --config examples/remote-gateway/Caddyfile
```

Pair locally, then:

```bash
bash scripts/smoke-remote-client.sh https://127.0.0.1:8443 "$TOKEN"
```

## agentd bind rule

`agentd serve --host` must stay on loopback (`127.0.0.1`). Non-loopback bind fails unless
`AGENTIC_OS_ALLOW_PUBLIC_BIND=1` (tests/dev only).
