# P12 Remote Access Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire remote access to local `agentd` through a transport-agnostic Remote Access Adapter — pairing, Bearer auth, device revoke, `GET /events` SSE — while keeping `agentd` on `127.0.0.1` only.

**Architecture:** Pairing + device registry live in `agentd` (SQLite under state dir). External clients reach the daemon only via an operator-provided **remote gateway / reverse tunnel** that terminates TLS and forwards `Authorization: Bearer`. Desktop stores tokens in macOS Keychain; settings UI drives pairing/revoke. Reference gateway config lives in `examples/remote-gateway/` (Caddy template, not a vendored tunnel product). iOS companion is a thin Swift HTTP+SSE client against `gateway_url`.

**Tech Stack:** FastAPI/Starlette SSE, SQLite remote device store, Tauri 2 + `keyring`/`security-framework`, SwiftUI + URLSession, Caddy/nginx reference configs.

**Design reference:** `docs/superpowers/specs/2026-06-07-p12-remote-access-adapter-design.md`  
**Phase contract:** `specs/030-remote-access-adapter.md`

**Depends on:** P11.5 merged (`specs/029-packaged-macos-app.md`)

---

## File structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/agentic_os/remote_store.py` | Create | SQLite: pairing codes, devices, tokens |
| `src/agentic_os/remote_access.py` | Create | Pairing lifecycle, token issue/revoke, validation |
| `src/agentic_os/api.py` | Modify | `/remote/*` routes, `GET /events` SSE, optional auth dependency |
| `src/agentic_os/daemon.py` | Modify | Reject non-loopback `--host` in production path |
| `tests/test_remote_access.py` | Create | Pairing, auth, revoke API tests |
| `tests/test_events_sse.py` | Create | SSE stream shape + auth gate |
| `tests/test_daemon_bind.py` | Create | Loopback-only bind guard |
| `examples/remote-gateway/README.md` | Create | Operator docs (any tunnel product) |
| `examples/remote-gateway/Caddyfile` | Create | Reference reverse proxy + Bearer passthrough + SSE |
| `apps/desktop/src-tauri/src/remote.rs` | Create | Keychain read/write for remote token |
| `apps/desktop/src-tauri/src/settings.rs` | Modify | Token excluded from TOML serialize |
| `apps/desktop/src-tauri/src/lib.rs` | Modify | Tauri commands: pairing start, list/revoke devices |
| `apps/web/desktop-settings.html` | Modify | Connection mode, pairing UX, no plain token field |
| `apps/ios/RemoteCompanion/` | Create | Minimal SwiftUI client (pair + health + SSE) |
| `specs/030-remote-access-adapter.md` | Modify | Status → Implemented when done |
| `README.md` | Modify | P12 setup section + gateway example link |

---

## Task 1: Remote device store

**Files:**
- Create: `src/agentic_os/remote_store.py`
- Create: `src/agentic_os/remote_access.py`
- Test: `tests/test_remote_access.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_remote_access.py
from agentic_os.remote_access import RemoteAccessService


def test_pairing_start_and_complete(tmp_path):
    svc = RemoteAccessService(tmp_path / ".agentic-os")
    started = svc.start_pairing(ttl_seconds=300)
    assert len(started["pairing_code"]) == 6
    completed = svc.complete_pairing(
        pairing_code=started["pairing_code"],
        device_name="iphone-test",
    )
    assert completed["device_id"]
    assert completed["auth_token"]
    assert svc.validate_token(completed["auth_token"]) == completed["device_id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_remote_access.py::test_pairing_start_and_complete -q`  
Expected: FAIL (`ModuleNotFoundError` or `RemoteAccessService` missing)

- [ ] **Step 3: Implement store + service**

```python
# src/agentic_os/remote_store.py
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


class RemoteDeviceStore:
    def __init__(self, state_dir: Path) -> None:
        self._db = state_dir / "remote_devices.sqlite3"
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code TEXT PRIMARY KEY,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                """
            )
```

```python
# src/agentic_os/remote_access.py — core methods
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from agentic_os.remote_store import RemoteDeviceStore


class RemoteAccessService:
    def __init__(self, state_dir: Path) -> None:
        self._store = RemoteDeviceStore(state_dir)

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def start_pairing(self, *, ttl_seconds: int = 300) -> dict[str, str]:
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        self._store.insert_pairing_code(code, expires.isoformat())
        return {"pairing_code": code, "expires_at": expires.isoformat()}

    def complete_pairing(self, *, pairing_code: str, device_name: str) -> dict[str, str]:
        if not self._store.consume_pairing_code(pairing_code):
            raise ValueError("invalid_or_expired_pairing_code")
        device_id = secrets.token_urlsafe(16)
        auth_token = secrets.token_urlsafe(32)
        self._store.insert_device(
            device_id=device_id,
            device_name=device_name,
            token_hash=self._hash_token(auth_token),
        )
        return {"device_id": device_id, "auth_token": auth_token}

    def validate_token(self, auth_token: str) -> str | None:
        return self._store.device_id_for_token_hash(self._hash_token(auth_token))

    def revoke_device(self, device_id: str) -> bool:
        return self._store.revoke_device(device_id)

    def list_devices(self) -> list[dict[str, str | None]]:
        return self._store.list_devices()
```

Implement `insert_pairing_code`, `consume_pairing_code`, `insert_device`, `device_id_for_token_hash`, `revoke_device`, `list_devices` on `RemoteDeviceStore`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_remote_access.py::test_pairing_start_and_complete -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/remote_store.py src/agentic_os/remote_access.py tests/test_remote_access.py
git commit -m "feat: add remote device store and pairing service (P12)"
```

---

## Task 2: Remote HTTP API routes

**Files:**
- Modify: `src/agentic_os/api.py`
- Test: `tests/test_remote_access.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_pairing_api_flow(client):
    start = client.post("/remote/pairing/start")
    assert start.status_code == 200
    code = start.json()["pairing_code"]
    done = client.post(
        "/remote/pairing/complete",
        json={"pairing_code": code, "device_name": "test-device"},
    )
    assert done.status_code == 200
    token = done.json()["auth_token"]
    devices = client.get("/remote/devices")
    assert devices.status_code == 200
    assert len(devices.json()["devices"]) == 1
    revoke = client.delete(f"/remote/devices/{done.json()['device_id']}")
    assert revoke.status_code == 200
    health = client.get("/health", headers={"Authorization": f"Bearer {token}"})
    assert health.status_code == 401  # revoked token rejected on protected route
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_remote_access.py::test_pairing_api_flow -q`  
Expected: FAIL (404 on `/remote/pairing/start`)

- [ ] **Step 3: Add routes + Bearer dependency**

Wire `RemoteAccessService` in `create_app`. Add:

| Method | Path | Auth | Body / response |
|--------|------|------|-----------------|
| POST | `/remote/pairing/start` | none (localhost operator) | `{pairing_code, expires_at}` |
| POST | `/remote/pairing/complete` | none | `{pairing_code, device_name}` → `{device_id, auth_token}` |
| GET | `/remote/devices` | none (localhost) | `{devices: [{device_id, device_name, created_at, revoked_at}]}` |
| DELETE | `/remote/devices/{device_id}` | none (localhost) | `{revoked: true}` |

Add optional dependency `require_remote_bearer` used by protected remote-facing routes:

```python
def require_remote_bearer(
    authorization: str | None = Header(default=None),
    remote: RemoteAccessService = Depends(get_remote_service),
) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    device_id = remote.validate_token(authorization.removeprefix("Bearer ").strip())
    if device_id is None:
        raise HTTPException(status_code=401, detail="invalid_or_revoked_token")
    return device_id
```

Pairing routes remain **localhost-only** (no Bearer): check `request.client.host` in `{"127.0.0.1", "::1"}` or reject with 403. Remote clients never call these directly — only the Mac operator or desktop app via local API.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_remote_access.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add remote pairing and device revoke API (P12)"
```

---

## Task 3: GET /events SSE stream

**Files:**
- Modify: `src/agentic_os/api.py`
- Test: `tests/test_events_sse.py`

- [ ] **Step 1: Write failing SSE test**

```python
import json

def test_events_sse_requires_auth(client):
    resp = client.get("/events")
    assert resp.status_code == 401


def test_events_sse_streams_audit_event(client, monkeypatch):
    start = client.post("/remote/pairing/start").json()
    done = client.post(
        "/remote/pairing/complete",
        json={"pairing_code": start["pairing_code"], "device_name": "sse-client"},
    ).json()
    token = done["auth_token"]
    with client.stream("GET", "/events", headers={"Authorization": f"Bearer {token}"}) as stream:
        first = next(stream.iter_lines())
        assert first.startswith(":")
        # after a config_patch audit event is written, expect `data: {...}` line
```

Use a helper in test to append one `config_patch` audit event, then assert one `data:` line parses as JSON with `domain == "config_patch"`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_events_sse.py -q`  
Expected: FAIL (404 or no stream)

- [ ] **Step 3: Implement SSE endpoint**

```python
from starlette.responses import StreamingResponse

@app.get("/events")
async def events_stream(
    device_id: str = Depends(require_remote_bearer),
    store: ControlPlaneStore = Depends(get_control_plane_store),
):
    async def generate():
        yield ": connected\n\n"
        last_id = 0
        while True:
            rows = store.list_audit_events_since(last_id, domain="config_patch", limit=20)
            for row in rows:
                last_id = max(last_id, row["id"])
                payload = json.dumps({**row, "remote_device_id": device_id})
                yield f"data: {payload}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream")
```

Add `list_audit_events_since` to the store layer (or query existing audit table with `id > ?`). Keep polling interval at 1s for P12 — no WebSocket upgrade.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_events_sse.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add authenticated GET /events SSE for remote clients (P12)"
```

---

## Task 4: Loopback bind guard + reference gateway

**Files:**
- Modify: `src/agentic_os/daemon.py`
- Create: `examples/remote-gateway/README.md`
- Create: `examples/remote-gateway/Caddyfile`
- Create: `tests/test_daemon_bind.py`

- [ ] **Step 1: Write bind guard test**

```python
from typer.testing import CliRunner
from agentic_os.daemon import app

runner = CliRunner()

def test_serve_rejects_public_bind():
    result = runner.invoke(app, ["serve", "--host", "0.0.0.0"])
    assert result.exit_code != 0
    assert "127.0.0.1" in result.output
```

- [ ] **Step 2: Implement guard in `serve()`**

```python
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}

def serve(host: str = typer.Option("127.0.0.1", "--host"), ...):
    if host not in _LOOPBACK:
        raise typer.BadParameter("agentd must bind loopback only (127.0.0.1); use a remote gateway for external access.")
    ...
```

Allow override only when `AGENTIC_OS_ALLOW_PUBLIC_BIND=1` (test/dev escape hatch, documented in README).

- [ ] **Step 3: Add reference gateway docs**

`examples/remote-gateway/README.md` — document:
- Operator picks any reverse tunnel (Tailscale Serve, Cloudflare Tunnel, ngrok, self-hosted Caddy, etc.)
- Minimum: HTTPS + Bearer passthrough + SSE buffering disabled
- `gateway_url` points to public HTTPS entry; tunnel forwards to `http://127.0.0.1:8767`

`examples/remote-gateway/Caddyfile` — local reference:

```caddy
:8443 {
    tls internal
    @unauth not header Authorization "Bearer *"
    respond @unauth 401
    reverse_proxy 127.0.0.1:8767 {
        flush_interval -1
        transport http {
            versions 1.1
        }
    }
}
```

Note: Bearer validation at gateway is optional for P12 merge gate — **agentd validates Bearer on `/events` and any route using `require_remote_bearer`**. Gateway may add a second layer; document both patterns.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_daemon_bind.py tests/test_remote_access.py tests/test_events_sse.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: enforce loopback bind and add reference remote gateway docs (P12)"
```

---

## Task 5: Desktop keychain + connection mode

**Files:**
- Create: `apps/desktop/src-tauri/src/remote.rs`
- Modify: `apps/desktop/src-tauri/src/settings.rs`
- Modify: `apps/desktop/src-tauri/src/lib.rs`
- Modify: `apps/web/desktop-settings.html`

- [ ] **Step 1: Write failing Rust test for token exclusion**

```rust
#[test]
fn settings_toml_excludes_token() {
    let settings = DesktopSettings::default();
    let raw = toml::to_string(&settings).unwrap();
    assert!(!raw.contains("token"));
}
```

Adjust `RemoteSettings` — remove `token` from serialized form; keep in memory struct optional or use separate keychain API.

- [ ] **Step 2: Implement keychain helpers**

Add `keyring = "3"` to `Cargo.toml`.

```rust
// apps/desktop/src-tauri/src/remote.rs
const SERVICE: &str = "dev.agentic-os.desktop";
const TOKEN_ACCOUNT: &str = "remote-auth-token";

pub fn save_remote_token(token: &str) -> Result<(), String> {
    keyring::Entry::new(SERVICE, TOKEN_ACCOUNT)
        .map_err(|e| e.to_string())?
        .set_password(token)
        .map_err(|e| e.to_string())
}

pub fn load_remote_token() -> Result<Option<String>, String> { ... }
pub fn clear_remote_token() -> Result<(), String> { ... }
```

- [ ] **Step 3: Tauri commands**

```rust
#[tauri::command]
fn start_remote_pairing() -> Result<String, String> {
    // POST http://127.0.0.1:8767/remote/pairing/start via reqwest blocking
}

#[tauri::command]
fn list_remote_devices() -> Result<String, String> { ... }

#[tauri::command]
fn revoke_remote_device(device_id: String) -> Result<(), String> { ... }
```

Add `reqwest` with `blocking` feature to `Cargo.toml`.

- [ ] **Step 4: Connection mode in settings UI**

Update `desktop-settings.html`:
- Radio: `local` | `remote`
- On save: if `remote`, derive `event_stream_url = gateway_url.trim_end('/') + '/events'`
- Remove plain token input; show pairing code from `start_remote_pairing`
- Device list + revoke buttons call new Tauri commands

Webview URL switch (in `lib.rs` setup or tray): when `connection.mode == "remote"`, navigate main window to `gateway_url` instead of local UI URL. Local daemon still runs on loopback.

- [ ] **Step 5: Run tests**

Run: `cd apps/desktop/src-tauri && cargo test && cd ../../.. && uv run pytest -q && uv run ruff check .`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git commit -m "feat: wire desktop remote settings with keychain and pairing UX (P12)"
```

---

## Task 6: iOS companion MVP

**Files:**
- Create: `apps/ios/RemoteCompanion/` (Xcode project or Swift Package executable)
- Create: `apps/ios/RemoteCompanion/Sources/RemoteClient.swift`
- Create: `apps/ios/RemoteCompanion/Sources/ContentView.swift`
- Modify: `README.md`

- [ ] **Step 1: Define Swift client contract (manual smoke script first)**

`scripts/smoke-remote-client.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
GATEWAY_URL="${1:?gateway_url}"
TOKEN="${2:?token}"
curl -sf -H "Authorization: Bearer ${TOKEN}" "${GATEWAY_URL}/health"
curl -sfN -H "Authorization: Bearer ${TOKEN}" "${GATEWAY_URL}/events" | head -1
```

- [ ] **Step 2: Implement minimal SwiftUI app**

`RemoteClient.swift`:
- `pair(gatewayUrl:pairingCode:)` → POST `{gateway}/remote/pairing/complete` — **Note:** pairing complete is localhost-only on agentd; iOS must call through gateway only if operator exposes pairing route. For P12 MVP: document that pairing completes via gateway proxy to localhost, OR iOS sends code to desktop via Tauri command (`complete_pairing_for_code`) and receives token out-of-band (QR/deep link).

**Locked approach for P12:** Desktop displays pairing code; iOS app sends `{pairing_code, device_name}` to **`{gateway_url}/remote/pairing/complete`**; reference Caddy forwards all `/remote/*` to agentd; agentd pairing routes accept requests when `X-Forwarded-For` is loopback OR add gateway shared secret header `X-Agentic-OS-Gateway: 1` set by reference Caddy config. Implement gateway trust header in pairing route guard (replace strict localhost-only check from Task 2 when header present).

- [ ] **Step 3: iOS UI**

- Fields: Gateway URL, Pairing code, Device name
- Button: Pair → stores token in Keychain
- Shows: `/health` status + first SSE comment line

- [ ] **Step 4: README P12 section**

Document: start agentd → configure tunnel → set `gateway_url` → desktop Start Pairing → iOS Pair → verify health + SSE.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add iOS remote companion MVP and smoke script (P12)"
```

---

## Task 7: Spec closure + merge gate

**Files:**
- Modify: `specs/030-remote-access-adapter.md`
- Modify: `README.md`

- [ ] **Step 1: Update spec status**

Change `Status: Planned` → `Status: Implemented` with verification commands.

- [ ] **Step 2: Run full CI gate**

```bash
uv run pytest -q && uv run ruff check .
cd apps/desktop/src-tauri && cargo test
```

- [ ] **Step 3: Manual merge gate checklist**

| # | Check | Command |
|---|-------|---------|
| 1 | agentd loopback only | `uv run agentd serve --host 0.0.0.0` → fails |
| 2 | Pairing issues token | `pytest tests/test_remote_access.py -q` |
| 3 | Revoke invalidates token | same |
| 4 | SSE works with Bearer | `pytest tests/test_events_sse.py -q` |
| 5 | Unauthenticated `/events` → 401 | same |
| 6 | Local desktop unchanged | `pnpm desktop:dev` smoke |
| 7 | Remote via gateway fixture | `bash scripts/smoke-remote-client.sh https://localhost:8443 $TOKEN` |
| 8 | Token not in desktop.toml | inspect `~/.agentic-os/desktop.toml` after save |

- [ ] **Step 4: Commit**

```bash
git commit -m "docs: mark P12 remote access adapter implemented"
```

---

## Verification commands

```bash
# Automated
uv run pytest tests/test_remote_access.py tests/test_events_sse.py tests/test_daemon_bind.py -q
uv run pytest -q && uv run ruff check .
cd apps/desktop/src-tauri && cargo test

# Reference gateway (operator machine)
caddy run --config examples/remote-gateway/Caddyfile
uv run agentd serve  # 127.0.0.1:8767

# End-to-end remote smoke
TOKEN=$(curl -s -X POST http://127.0.0.1:8767/remote/pairing/start | jq -r .pairing_code | \
  xargs -I{} curl -s -X POST http://127.0.0.1:8767/remote/pairing/complete \
  -H 'Content-Type: application/json' \
  -d "{\"pairing_code\":\"{}\",\"device_name\":\"smoke\"}" | jq -r .auth_token)
bash scripts/smoke-remote-client.sh https://127.0.0.1:8443 "$TOKEN"
```

---

## Spec coverage self-review

| Spec requirement | Task |
|------------------|------|
| `gateway_url`, `auth_token`, `pairing_code`, `device_id` inputs | 2, 5, 6 |
| Transport-agnostic (no vendored tunnel) | 4 |
| `agentd` on `127.0.0.1` only | 4 |
| Auth on every remote request | 2, 3 |
| Pairing gate | 1, 2, 6 |
| Revoke without daemon restart | 1, 2, 5 |
| `GET /events` SSE over gateway | 3, 4 |
| Local mode unchanged | 5 |
| Token not in plain `desktop.toml` | 5 |
| iOS companion | 6 |

---

## Out of scope (explicit)

- Vendoring frp / Tailscale / Cloudflare / ngrok binaries
- Hosted multi-tenant relay SaaS
- RBAC beyond single-operator device list
- Harness runtime or new agent features
- Web UI redesign for remote mode (desktop webview URL switch only)
