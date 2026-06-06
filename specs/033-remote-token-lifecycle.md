# 033 — Remote Token Lifecycle Hardening (P14)

Status: Implemented
Date: 2026-06-07
Depends on: P12 (`specs/030-remote-access-adapter.md`)
Blocks: —

## Positioning

P12 issued a per-device `auth_token` that lives forever until an operator revokes the
device. There is no expiry and no way to refresh a token without deleting and re-pairing
the device (losing its identity and history). That is two pieces of security debt:

- **No expiry**: a leaked token is valid indefinitely unless someone notices and revokes.
- **No rotation**: responding to a *suspected* leak forces a full revoke + re-pair, which
  drops the device record.

P14 adds the **mechanism** for both — opt-in token TTL and in-place token rotation —
without changing any default P12 behavior. A token with no TTL behaves exactly as in P12.

## Backward compatibility (hard requirement)

- `expires_at` is a new **nullable** column on `devices`. `NULL` means "never expires",
  which is the P12 default and the value for every existing paired device.
- Existing `remote_devices.sqlite3` files are migrated in place (`ALTER TABLE ADD COLUMN`
  when the column is absent); no data loss, no re-pairing.
- Pairing still defaults to **no expiry**. A TTL is only applied when explicitly requested.
- No P12 route, request model, or response shape is removed or repurposed.

## Contract

| Capability | Behavior |
|------------|----------|
| Token expiry | `validate_token` rejects a token whose device `expires_at` is in the past; `NULL` or future `expires_at` validates |
| Pairing TTL (opt-in) | `complete_pairing(ttl_seconds=…)` sets `expires_at`; default `None` keeps P12 forever-tokens |
| Rotation | `POST /remote/devices/{id}/rotate` (localhost-only) issues a new `auth_token`, invalidates the old one, preserves `device_id`/name/`created_at` |
| Revoked devices | cannot be rotated; rotation returns 404 |
| Device listing | `GET /remote/devices` adds `expires_at` (additive field) |

## Security posture

`POST /remote/devices/{id}/rotate` is an **operator/admin** action and is **localhost-only**,
exactly like `pairing/start`, `devices`, and revoke. It is rejected (403) when presented
through the gateway. The rotate path is added to `is_remote_admin_route`.

| Owns | Does not own |
|------|--------------|
| Token `expires_at` column + migration | Default-on TTL policy (left to a future decision) |
| In-place token rotation (localhost admin) | Client-side https enforcement (P15) |
| Expiry surfaced in device listing | Automatic re-pair / silent refresh UX, push notifications |

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Past `expires_at` → token invalid; `NULL`/future → valid | `tests/test_remote_token_lifecycle.py` |
| Legacy device (no expiry) still validates after migration | same |
| Rotation issues new token, old token invalid, `device_id` preserved | same |
| Rotation on revoked/missing device → 404 | same |
| Rotate route is localhost-only (gateway → 403) | same |
| All P12 remote tests unchanged and passing | `tests/test_remote_access.py` |

## P12 boundary (frozen)

Pairing API shape, gateway middleware trust model, reference Caddyfile, and loopback-only
`agentd` are **frozen**. P14 adds a nullable column, one localhost-only route, and opt-in
TTL — additive only.
