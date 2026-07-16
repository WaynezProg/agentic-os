# Desktop Transport and Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local and remote Desktop connections behaviorally equivalent, restore authenticated remote events, surface startup failures, and harden the packaged WebView.

**Architecture:** One Rust request builder handles all supported verbs and response semantics. Remote Desktop events use bounded authenticated polling through the Keychain-backed bridge; SSE remains for native clients.

**Tech Stack:** Tauri 2, Rust 1.77+, reqwest blocking client with rustls, macOS Keychain, FastAPI, vanilla JavaScript, cargo test, pytest.

## Global Constraints

- Remote bearer tokens never enter JavaScript or `desktop.toml`.
- Non-loopback remote gateways require HTTPS.
- Local `agentd` remains loopback-only.
- Supported verbs are GET, POST, PUT, PATCH, DELETE.
- WebView CSP must permit only packaged assets, Tauri IPC, and configured API connections.
- Packaged mode does not start a UI HTTP server.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/desktop/src-tauri/src/remote.rs` | Shared request builder and gateway security |
| `apps/desktop/src-tauri/src/connection.rs` | Local/remote profile routing |
| `apps/desktop/src-tauri/src/lib.rs` | Tauri commands and lifecycle error events |
| `apps/desktop/src-tauri/tauri.conf.json` | Window dimensions and CSP |
| `src/agentic_os/remote_api.py` | Authenticated bounded event polling |
| `apps/web/api.js` | Transport-neutral request helpers |
| `apps/web/ui/approval-workbench.js` | Poll remote events through Rust bridge |
| `tests/test_remote_admin_routes.py` | Poll auth and event filtering |
| `tests/test_web.py` | No direct remote EventSource and method contract |
| Rust module tests | Verb, URL, profile, and security behavior |

### Task 1: One Rust request builder with full verb support

**Interfaces:**

- Produces:
  `remote::request(base_url, method, path, body, bearer) -> Result<String, String>`.
- Consumed by local and remote connection paths.

- [x] **Step 1: Add Rust tests**

In `remote.rs` test module add:

```rust
#[test]
fn supported_methods_include_put_and_patch() {
    for method in ["GET", "POST", "PUT", "PATCH", "DELETE"] {
        assert!(is_supported_method(method));
    }
    assert!(!is_supported_method("TRACE"));
}

#[test]
fn normalize_path_adds_one_leading_slash() {
    assert_eq!(normalize_path("health"), "/health");
    assert_eq!(normalize_path("/health"), "/health");
}
```

- [x] **Step 2: Verify current failure**

```bash
cd apps/desktop/src-tauri
cargo test supported_methods_include_put_and_patch
```

Expected: compile failure because helpers do not exist.

- [x] **Step 3: Implement shared method helpers**

Add:

```rust
pub fn is_supported_method(method: &str) -> bool {
    matches!(
        method.to_ascii_uppercase().as_str(),
        "GET" | "POST" | "PUT" | "PATCH" | "DELETE"
    )
}

fn normalize_path(path: &str) -> String {
    if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    }
}
```

Replace `post_json`, `get_json`, `delete_json`, and gateway verb switches with
one private request builder using `client.request(reqwest::Method, url)`.
Keep thin compatibility wrappers for current callers.

- [x] **Step 4: Use configured local URL**

Change `connection::api_request()` so local mode passes
`settings.local.api_url` into the shared builder. Remove the fixed/env-only URL
from normal Desktop requests; lifecycle scripts may continue using their
managed loopback port.

- [x] **Step 5: Run Rust tests**

```bash
cd apps/desktop/src-tauri
cargo test
```

- [x] **Step 6: Commit**

```bash
git add apps/desktop/src-tauri/src/remote.rs apps/desktop/src-tauri/src/connection.rs
git commit -m "fix: unify desktop HTTP transport"
```

### Task 2: Authenticated event polling endpoint

**Interfaces:**

- Adds `GET /events/poll?after_id=<int>&limit=<int>`.
- Uses the same bearer validation and remote-event allowlist as SSE.

- [x] **Step 1: Write API tests**

Add to `tests/test_remote_approval_loop.py`, reusing that file's `_audit()`,
`_pair_device()`, `GATEWAY_HEADERS`, and `make_client()` helpers:

```python
def test_event_poll_requires_bearer(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/events/poll", headers=GATEWAY_HEADERS)
    assert response.status_code == 401


def test_event_poll_returns_allowed_events_after_cursor(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    token = _pair_device(client)
    audit = _audit(tmp_path)
    first = audit.record(
        "config_patch", "agentic-os", "config_patched", "one", {}
    )
    audit.record(
        "governance", "shell", "policy_evaluated", "hidden", {}
    )
    third = audit.record(
        "governance", "shell", "approval_requested", "three",
        {"approval_id": "ap_3"},
    )
    response = client.get(
        f"/events/poll?after_id={first.id}",
        headers={**GATEWAY_HEADERS, "Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert [event["id"] for event in response.json()["events"]] == [third.id]
```

- [x] **Step 2: Implement route**

In `remote_api.py` add:

```python
@app.get("/events/poll")
def events_poll(
    after_id: int = 0,
    limit: int = 50,
    device_id: str = Depends(require_remote_bearer),
) -> dict[str, object]:
    bounded = max(1, min(limit, 200))
    rows = audit_store.list_remote_stream_events_after_id(after_id, limit=bounded)
    events = [_audit_event_payload(row, device_id=device_id) for row in rows]
    return {
        "events": events,
        "after_id": max([after_id, *[row.id for row in rows]]),
    }
```

- [x] **Step 3: Verify**

```bash
rtk uv run pytest tests/test_remote_admin_routes.py tests/test_remote_approval_loop.py -q
rtk uv run ruff check src/agentic_os/remote_api.py
```

- [x] **Step 4: Commit**

```bash
git add src/agentic_os/remote_api.py tests/test_remote_admin_routes.py tests/test_remote_approval_loop.py
git commit -m "feat: add authenticated event polling"
```

### Task 3: Web remote event client

**Interfaces:**

- Produces: polling lifecycle in `ApprovalWorkbench`.
- Consumes: `/events/poll` through `Ao.apiFetch`.

- [ ] **Step 1: Add static Web contract tests**

In `tests/test_web.py` assert:

```python
def test_remote_approval_events_use_authenticated_bridge() -> None:
    js = APPROVAL_WORKBENCH_JS.read_text(encoding="utf-8")
    assert "EventSource" not in js
    assert 'Ao.buildEndpoint("eventsPoll")' in js
    assert "after_id" in js
    assert "setTimeout" in js
```

Add `eventsPoll: "/events/poll"` to the endpoint-map assertion.

- [ ] **Step 2: Verify current failure**

```bash
rtk uv run pytest tests/test_web.py -k remote_approval_events -q
```

- [ ] **Step 3: Replace EventSource**

In `approval-workbench.js`, maintain:

```javascript
let eventCursor = 0;
let pollTimer = null;
let pollBackoffMs = 1500;
```

`pollRemoteEvents()` calls:

```javascript
const data = await Ao.apiFetch(
  `${Ao.buildEndpoint("eventsPoll")}?after_id=${eventCursor}&limit=50`
);
```

Process events using the existing event handler, advance `eventCursor`, reset
backoff on success, and retry with a capped 15-second delay on failure. Stop the
timer when connection mode leaves remote.

- [ ] **Step 4: Verify JavaScript**

```bash
node --check apps/web/ui/approval-workbench.js
rtk uv run pytest tests/test_web.py tests/test_remote_approval_loop.py -q
```

- [ ] **Step 5: Commit**

```bash
git add apps/web/api.js apps/web/ui/approval-workbench.js tests/test_web.py
git commit -m "fix: bridge remote approval events through Keychain auth"
```

### Task 4: Immediate lifecycle error visibility

**Interfaces:**

- Tauri setup emits `connection-state` with startup failure detail immediately.

- [ ] **Step 1: Extract startup outcome**

Change `daemon::reconcile_stack()` and `daemon::start_stack()` to return a
typed result:

```rust
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StackStartResult {
    pub daemon_started: bool,
    pub detail: String,
}
```

The result reports `ok`, `port_occupied:<pid>`, or the bounded script error.

- [ ] **Step 2: Emit setup result**

In `lib.rs` setup, emit an initial `connection-state` payload before spawning
the supervisor. Do not discard startup errors.

- [ ] **Step 3: Add Rust unit tests**

Test result parsing and ensure error detail is bounded to 512 characters.

- [ ] **Step 4: Verify**

```bash
cd apps/desktop/src-tauri
cargo test
```

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/src-tauri/src/daemon.rs apps/desktop/src-tauri/src/lib.rs apps/desktop/src-tauri/src/supervisor.rs
git commit -m "fix: surface desktop startup failures"
```

### Task 5: Window and CSP hardening

- [ ] **Step 1: Add config assertions**

Extend `tests/test_desktop_bundle.py`:

```python
def test_tauri_window_and_csp_are_production_safe() -> None:
    config = json.loads((ROOT / "apps/desktop/src-tauri/tauri.conf.json").read_text())
    window = config["app"]["windows"][0]
    assert window["width"] == 1280
    assert window["height"] == 820
    assert window["minWidth"] == 960
    assert window["minHeight"] == 640
    csp = config["app"]["security"]["csp"]
    assert csp
    assert "default-src 'self'" in csp
    assert "connect-src" in csp
```

- [ ] **Step 2: Update Tauri config**

Set:

```json
{
  "width": 1280,
  "height": 820,
  "minWidth": 960,
  "minHeight": 640
}
```

Use a CSP verified against current Tauri 2 documentation. It must allow
packaged scripts/styles/images, Tauri IPC, loopback API connections, and HTTPS
remote gateways while rejecting arbitrary script origins.

- [ ] **Step 3: Verify**

```bash
rtk uv run pytest tests/test_desktop_bundle.py -q
cd apps/desktop/src-tauri && cargo test
```

- [ ] **Step 4: Commit**

```bash
git add apps/desktop/src-tauri/tauri.conf.json tests/test_desktop_bundle.py
git commit -m "security: harden desktop window and CSP"
```

### Task 6: Complete transport verification

- [ ] **Step 1: Run transport suites**

```bash
rtk uv run pytest tests/test_remote_admin_routes.py tests/test_remote_approval_loop.py tests/test_remote_token_lifecycle.py tests/test_web.py tests/test_desktop_bundle.py tests/test_desktop_scripts.py -q
cd apps/desktop/src-tauri && cargo test
```

- [ ] **Step 2: Run remote smoke**

Start the local daemon and reference gateway, pair a temporary device, then run:

```bash
bash scripts/smoke-remote-client.sh https://127.0.0.1:8443 "$TOKEN"
```

Verify GET, POST, PUT, DELETE, and `/events/poll` through the Desktop bridge.

- [ ] **Step 3: Record evidence**

Append the exact test outputs and any credential-independent release boundary to
`decision_log.md`.

- [ ] **Step 4: Commit**

```bash
git add decision_log.md
git commit -m "docs: record desktop transport verification"
```

## Self-Review

- Spec coverage: Task 1 covers verb and local URL parity; Tasks 2 and 3 restore
  authenticated remote events without exposing tokens to JavaScript; Task 4
  surfaces lifecycle failures; Task 5 hardens the WebView; Task 6 proves both
  local and remote paths.
- Placeholder scan: no deferred implementation markers remain. Remote smoke
  uses a paired temporary device and the existing reference gateway.
- Type consistency: all transport layers use the same five HTTP verbs and
  `/events/poll` cursor names (`after_id`, `limit`).
